import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Cartao,
    ConversaContexto,
    Estabelecimento,
    HistoricoMensagem,
    Lancamento,
    Setor,
    TransacaoPendente,
)
from app.schemas import ExtracaoLancamento

logger = logging.getLogger(__name__)

SETORES_PADRAO = [
    "mercado", "ferramenta", "lanche", "cursos", "viagem",
    "gasolina", "restaurante", "assinatura", "outros",
]

ESSENTIAL_FIELDS = ["estabelecimento", "setor", "tipo", "valor"]


class LancamentoRepository:
    async def ensure_setores(self, db: AsyncSession) -> None:
        for nome in SETORES_PADRAO:
            exists = await db.scalar(select(Setor).where(Setor.nome == nome))
            if not exists:
                db.add(Setor(nome=nome))
        await db.flush()

    async def get_or_create_setor(self, db: AsyncSession, nome: str) -> Setor:
        nome_norm = nome.lower().strip()
        setor = await db.scalar(select(Setor).where(Setor.nome == nome_norm))
        if not setor:
            setor = Setor(nome=nome_norm)
            db.add(setor)
            await db.flush()
        return setor

    async def get_or_create_estabelecimento(
        self, db: AsyncSession, nome: str, setor_id: int | None = None
    ) -> Estabelecimento:
        nome_norm = nome.strip()
        estab = await db.scalar(
            select(Estabelecimento).where(
                func.lower(Estabelecimento.nome_exibicao) == nome_norm.lower()
            )
        )
        if not estab:
            estab = Estabelecimento(nome_exibicao=nome_norm, setor_id=setor_id)
            db.add(estab)
            await db.flush()
        return estab

    async def get_default_cartao(self, db: AsyncSession) -> Cartao | None:
        return await db.scalar(select(Cartao).where(Cartao.cartao_padrao == "sim").limit(1))

    async def get_any_cartao(self, db: AsyncSession) -> Cartao | None:
        return await db.scalar(select(Cartao).limit(1))

    async def list_cartoes(self, db: AsyncSession) -> list[Cartao]:
        result = await db.scalars(select(Cartao).order_by(Cartao.id))
        return list(result.all())

    async def create_cartao(self, db: AsyncSession, data: dict) -> Cartao:
        cartao = Cartao(**data)
        if cartao.cartao_padrao == "sim":
            others = await db.scalars(select(Cartao).where(Cartao.cartao_padrao == "sim"))
            for c in others:
                c.cartao_padrao = "nao"
        db.add(cartao)
        await db.flush()
        return cartao

    async def create_lancamento(
        self,
        db: AsyncSession,
        extracao: ExtracaoLancamento,
        cartao_id: int,
        origem: str,
        message_id: str | None,
        key_id: str | None,
    ) -> Lancamento:
        setor = await self.get_or_create_setor(db, extracao.setor or "outros")
        estab = await self.get_or_create_estabelecimento(db, extracao.estabelecimento or "Desconhecido", setor.id)
        data_hora = extracao.data_hora or datetime.now(timezone.utc)

        lancamento = Lancamento(
            estabelecimento_id=estab.id,
            setor_id=setor.id,
            cartao_id=cartao_id,
            tipo=extracao.tipo or "a_vista",
            valor=extracao.valor or Decimal("0"),
            parcelas=extracao.parcelas,
            data_hora=data_hora,
            origem=origem,
            message_id=message_id,
            key_id=key_id,
        )
        db.add(lancamento)
        await db.flush()
        return lancamento

    async def get_ultimo_lancamento(self, db: AsyncSession) -> Lancamento | None:
        return await db.scalar(
            select(Lancamento)
            .options(selectinload(Lancamento.estabelecimento), selectinload(Lancamento.setor))
            .order_by(Lancamento.id.desc())
            .limit(1)
        )

    async def delete_lancamento(self, db: AsyncSession, lancamento_id: int) -> bool:
        lanc = await db.get(Lancamento, lancamento_id)
        if lanc:
            await db.delete(lanc)
            return True
        return False

    async def sum_by_setor_mes(self, db: AsyncSession, setor_nome: str, mes: int, ano: int) -> Decimal:
        total = await db.scalar(
            select(func.coalesce(func.sum(Lancamento.valor), 0))
            .join(Setor)
            .where(
                and_(
                    Setor.nome == setor_nome.lower(),
                    extract("month", Lancamento.data_hora) == mes,
                    extract("year", Lancamento.data_hora) == ano,
                )
            )
        )
        return Decimal(str(total or 0))

    async def sum_mes(self, db: AsyncSession, mes: int, ano: int) -> Decimal:
        total = await db.scalar(
            select(func.coalesce(func.sum(Lancamento.valor), 0)).where(
                and_(
                    extract("month", Lancamento.data_hora) == mes,
                    extract("year", Lancamento.data_hora) == ano,
                )
            )
        )
        return Decimal(str(total or 0))

    async def list_recentes(self, db: AsyncSession, limit: int = 20) -> list[Lancamento]:
        result = await db.scalars(
            select(Lancamento)
            .options(selectinload(Lancamento.estabelecimento), selectinload(Lancamento.setor))
            .order_by(Lancamento.data_hora.desc())
            .limit(limit)
        )
        return list(result.all())

    async def gastos_por_setor_mes(self, db: AsyncSession, mes: int, ano: int) -> list[tuple[str, Decimal]]:
        rows = await db.execute(
            select(Setor.nome, func.coalesce(func.sum(Lancamento.valor), 0))
            .join(Lancamento, Lancamento.setor_id == Setor.id)
            .where(
                and_(
                    extract("month", Lancamento.data_hora) == mes,
                    extract("year", Lancamento.data_hora) == ano,
                )
            )
            .group_by(Setor.nome)
            .order_by(func.sum(Lancamento.valor).desc())
        )
        return [(r[0], Decimal(str(r[1]))) for r in rows.all()]


class ConversaRepository:
    async def get_context(self, db: AsyncSession, phone: str) -> ConversaContexto:
        ctx = await db.scalar(select(ConversaContexto).where(ConversaContexto.phone_number == phone))
        if not ctx:
            ctx = ConversaContexto(phone_number=phone, mensagens=[], dados_estado={})
            db.add(ctx)
            await db.flush()
        return ctx

    async def add_message(self, db: AsyncSession, phone: str, role: str, content: str) -> None:
        ctx = await self.get_context(db, phone)
        msgs = list(ctx.mensagens or [])
        msgs.append({"role": role, "content": content})
        ctx.mensagens = msgs[-20:]
        ctx.updated_at = datetime.now(timezone.utc)

    async def set_estado(self, db: AsyncSession, phone: str, estado: str | None, dados: dict | None = None) -> None:
        ctx = await self.get_context(db, phone)
        ctx.estado = estado
        if dados is not None:
            ctx.dados_estado = dados

    async def get_pendente_ativa(self, db: AsyncSession, phone: str) -> TransacaoPendente | None:
        return await db.scalar(
            select(TransacaoPendente)
            .where(and_(TransacaoPendente.phone_number == phone, TransacaoPendente.status == "pendente"))
            .order_by(TransacaoPendente.id.desc())
            .limit(1)
        )

    async def create_pendente(
        self,
        db: AsyncSession,
        phone: str,
        capturados: dict,
        faltantes: list[str],
        origem: str,
        message_id: str | None,
        key_id: str | None,
        historico_id: int | None = None,
    ) -> TransacaoPendente:
        pend = TransacaoPendente(
            phone_number=phone,
            historico_id=historico_id,
            campos_capturados=capturados,
            campos_faltantes=faltantes,
            origem=origem,
            message_id=message_id,
            key_id=key_id,
            status="pendente",
        )
        db.add(pend)
        await db.flush()
        return pend

    async def discard_pendente(self, db: AsyncSession, pendente: TransacaoPendente) -> None:
        pendente.status = "descartado"
        if pendente.historico_id:
            hist = await db.get(HistoricoMensagem, pendente.historico_id)
            if hist:
                hist.status = "descartado"

    async def list_pendentes_hoje(self, db: AsyncSession) -> list[TransacaoPendente]:
        hoje = date.today()
        result = await db.scalars(
            select(TransacaoPendente).where(
                and_(
                    TransacaoPendente.status == "pendente",
                    func.date(TransacaoPendente.created_at) == hoje,
                )
            )
        )
        return list(result.all())

    async def get_cartoes_vencendo(self, db: AsyncSession, meses: int = 3) -> list[Cartao]:
        from dateutil.relativedelta import relativedelta

        limite = date.today() + relativedelta(months=meses)
        result = await db.scalars(
            select(Cartao).where(and_(Cartao.vencimento.isnot(None), Cartao.vencimento <= limite))
        )
        return list(result.all())


lancamento_repo = LancamentoRepository()
conversa_repo = ConversaRepository()
