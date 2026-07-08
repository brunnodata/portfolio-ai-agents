import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Cartao, Lancamento, Setor
from app.schemas import ExtracaoLancamento, ProjecaoItem

logger = logging.getLogger(__name__)

RECORRENTES_POR_NATUREZA = ("mercado", "gasolina", "lanche")
TIPOS_CONTINUAM = ("assinatura", "fixo", "parcelado")


def parse_parcelas(parcelas: str | None) -> tuple[int, int] | None:
    if not parcelas:
        return None
    match = re.search(r"(\d+)\s*(?:de|/)\s*(\d+)", parcelas, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def mes_key(dt: date) -> str:
    return dt.strftime("%Y-%m")


class ProjecaoService:
    async def calcular_projecoes(self, db: AsyncSession) -> list[ProjecaoItem]:
        hoje = datetime.now(timezone.utc).date()
        projecoes: list[ProjecaoItem] = []
        agregado: dict[str, Decimal] = {}

        lancamentos = await db.scalars(
            select(Lancamento).options(selectinload(Lancamento.setor)).order_by(Lancamento.data_hora.desc())
        )

        for lanc in lancamentos.all():
            if lanc.tipo in ("assinatura", "fixo"):
                for i in range(1, 4):
                    mes = mes_key(hoje + relativedelta(months=i))
                    chave = f"{mes}|{lanc.tipo}"
                    agregado[chave] = agregado.get(chave, Decimal("0")) + lanc.valor

            elif lanc.tipo == "parcelado":
                parsed = parse_parcelas(lanc.parcelas)
                if parsed:
                    atual, total = parsed
                    restantes = total - atual
                    for i in range(1, min(restantes + 1, 4)):
                        mes = mes_key(hoje + relativedelta(months=i))
                        chave = f"{mes}|parcelado"
                        agregado[chave] = agregado.get(chave, Decimal("0")) + lanc.valor

        for setor_nome in RECORRENTES_POR_NATUREZA:
            total_mes = await self._total_setor_mes_atual(db, setor_nome)
            if total_mes > 0:
                mes = mes_key(hoje + relativedelta(months=1))
                chave = f"{mes}|recorrente_{setor_nome}"
                agregado[chave] = agregado.get(chave, Decimal("0")) + total_mes

        cartoes = await db.scalars(select(Cartao))
        for cartao in cartoes:
            if cartao.valores_futuros:
                for mes, valor in cartao.valores_futuros.items():
                    chave = f"{mes}|cartao_futuro"
                    agregado[chave] = agregado.get(chave, Decimal("0")) + Decimal(str(valor))

        for chave, valor in sorted(agregado.items()):
            mes, tipo = chave.split("|", 1)
            projecoes.append(ProjecaoItem(mes=mes, valor=valor.quantize(Decimal("0.01")), tipo=tipo))

        return projecoes

    async def total_projecao_proximo_mes(self, db: AsyncSession) -> Decimal:
        hoje = datetime.now(timezone.utc).date()
        proximo = mes_key(hoje + relativedelta(months=1))
        projecoes = await self.calcular_projecoes(db)
        return sum((p.valor for p in projecoes if p.mes == proximo), Decimal("0"))

    async def calcular_cortes(self, db: AsyncSession) -> dict:
        now = datetime.now(timezone.utc)
        mes, ano = now.month, now.year

        por_tipo_rows = await db.execute(
            select(Lancamento.tipo, func.coalesce(func.sum(Lancamento.valor), 0))
            .where(and_(extract("month", Lancamento.data_hora) == mes, extract("year", Lancamento.data_hora) == ano))
            .group_by(Lancamento.tipo)
            .order_by(func.sum(Lancamento.valor).desc())
        )
        por_tipo_raw = [(r[0], Decimal(str(r[1]))) for r in por_tipo_rows.all()]
        total_mes = sum(v for _, v in por_tipo_raw) or Decimal("1")

        continua = sum(v for t, v in por_tipo_raw if t in TIPOS_CONTINUAM)
        nao_volta = sum(v for t, v in por_tipo_raw if t == "a_vista")

        recorrentes = Decimal("0")
        for setor in RECORRENTES_POR_NATUREZA:
            recorrentes += await self._total_setor_mes_atual(db, setor)

        projecao_proximo = await self.total_projecao_proximo_mes(db)

        return {
            "por_tipo": [
                {"tipo": t, "total": v, "percentual": float(v / total_mes * 100)}
                for t, v in por_tipo_raw
            ],
            "continua_proximo_mes": continua.quantize(Decimal("0.01")),
            "nao_volta_proximo_mes": nao_volta.quantize(Decimal("0.01")),
            "recorrentes_estimados": recorrentes.quantize(Decimal("0.01")),
            "projecao_proximo_mes": projecao_proximo.quantize(Decimal("0.01")),
        }

    async def atualizar_valores_futuros_cartao(
        self, db: AsyncSession, cartao_id: int, extracao: ExtracaoLancamento
    ) -> None:
        cartao = await db.get(Cartao, cartao_id)
        if not cartao or not extracao.valor:
            return

        hoje = datetime.now(timezone.utc).date()
        futuros: dict[str, float] = dict(cartao.valores_futuros or {})

        if extracao.tipo in ("assinatura", "fixo"):
            for i in range(1, 4):
                mes = mes_key(hoje + relativedelta(months=i))
                futuros[mes] = float(futuros.get(mes, 0)) + float(extracao.valor)

        elif extracao.tipo == "parcelado":
            parsed = parse_parcelas(extracao.parcelas)
            if parsed:
                atual, total = parsed
                restantes = total - atual
                for i in range(1, min(restantes + 1, 4)):
                    mes = mes_key(hoje + relativedelta(months=i))
                    futuros[mes] = float(futuros.get(mes, 0)) + float(extracao.valor)

        cartao.valores_futuros = dict(sorted(futuros.items())[:3])

        if cartao.limite_total is not None:
            uso = (cartao.limite_em_uso or Decimal("0")) + extracao.valor
            cartao.limite_em_uso = uso
            cartao.limite_restante = cartao.limite_total - uso

        if extracao.tipo == "assinatura":
            cartao.qt_assinaturas = (cartao.qt_assinaturas or 0) + 1

    async def _total_setor_mes_atual(self, db: AsyncSession, setor_nome: str) -> Decimal:
        now = datetime.now(timezone.utc)
        total = await db.scalar(
            select(func.coalesce(func.sum(Lancamento.valor), 0))
            .join(Setor)
            .where(
                and_(
                    Setor.nome == setor_nome.lower(),
                    extract("month", Lancamento.data_hora) == now.month,
                    extract("year", Lancamento.data_hora) == now.year,
                )
            )
        )
        return Decimal(str(total or 0))


projecao_service = ProjecaoService()
