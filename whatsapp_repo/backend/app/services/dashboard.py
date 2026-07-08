import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Lancamento, Setor
from app.schemas import DashboardData, DashboardKPIs, LancamentoListItem, ProjecaoItem, SetorGasto
from app.services.repository import lancamento_repo

logger = logging.getLogger(__name__)


class DashboardService:
    async def get_dashboard_data(self, db: AsyncSession) -> DashboardData:
        now = datetime.now(timezone.utc)
        mes, ano = now.month, now.year
        mes_ant = mes - 1 if mes > 1 else 12
        ano_ant = ano if mes > 1 else ano - 1

        total_mes = await lancamento_repo.sum_mes(db, mes, ano)
        total_ant = await lancamento_repo.sum_mes(db, mes_ant, ano_ant)
        por_setor_raw = await lancamento_repo.gastos_por_setor_mes(db, mes, ano)
        recentes = await lancamento_repo.list_recentes(db, 15)

        qtd = await db.scalar(
            select(func.count(Lancamento.id)).where(
                and_(extract("month", Lancamento.data_hora) == mes, extract("year", Lancamento.data_hora) == ano)
            )
        )
        dias = max(now.day, 1)
        media = total_mes / Decimal(dias)
        projecao = media * Decimal("30")

        total_geral = sum(v for _, v in por_setor_raw) or Decimal("1")
        por_setor = [
            SetorGasto(setor=s, total=t, percentual=float(t / total_geral * 100))
            for s, t in por_setor_raw
        ]

        lanc_items = [
            LancamentoListItem(
                id=l.id,
                estabelecimento=l.estabelecimento.nome_exibicao,
                setor=l.setor.nome,
                tipo=l.tipo,
                valor=l.valor,
                parcelas=l.parcelas,
                data_hora=l.data_hora,
                origem=l.origem,
            )
            for l in recentes
        ]

        projecoes = await self._calcular_projecoes(db)
        ofensores = por_setor[:3]

        return DashboardData(
            kpis=DashboardKPIs(
                total_mes=total_mes,
                total_mes_anterior=total_ant,
                qtd_lancamentos_mes=qtd or 0,
                media_diaria=media.quantize(Decimal("0.01")),
                projecao_mes=projecao.quantize(Decimal("0.01")),
            ),
            por_setor=por_setor,
            lancamentos_recentes=lanc_items,
            projecoes=projecoes,
            ofensores=ofensores,
        )

    async def _calcular_projecoes(self, db: AsyncSession) -> list[ProjecaoItem]:
        from app.models import Cartao

        projecoes: list[ProjecaoItem] = []
        cartoes = await db.scalars(select(Cartao))
        for cartao in cartoes:
            if cartao.valores_futuros:
                for mes, valor in cartao.valores_futuros.items():
                    projecoes.append(ProjecaoItem(mes=mes, valor=Decimal(str(valor)), tipo="cartao_futuro"))

        recorrentes = ("mercado", "gasolina", "lanche")
        now = datetime.now(timezone.utc)
        for setor_nome in recorrentes:
            media = await self._media_setor(db, setor_nome)
            if media > 0:
                projecoes.append(ProjecaoItem(mes=now.strftime("%Y-%m"), valor=media, tipo=f"recorrente_{setor_nome}"))

        return projecoes

    async def _media_setor(self, db: AsyncSession, setor_nome: str) -> Decimal:
        now = datetime.now(timezone.utc)
        total = await lancamento_repo.sum_by_setor_mes(db, setor_nome, now.month, now.year)
        return total


dashboard_service = DashboardService()
