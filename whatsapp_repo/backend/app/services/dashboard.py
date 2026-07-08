import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lancamento
from app.schemas import CortesAnaliticos, DashboardData, DashboardKPIs, LancamentoListItem, SetorGasto, TipoGasto
from app.services.projecao import projecao_service
from app.services.repository import lancamento_repo

logger = logging.getLogger(__name__)


class DashboardService:
    async def get_dashboard_data(
        self,
        db: AsyncSession,
        *,
        setor: str | None = None,
        tipo: str | None = None,
        mes: int | None = None,
        ano: int | None = None,
    ) -> DashboardData:
        now = datetime.now(timezone.utc)
        mes_ref = mes or now.month
        ano_ref = ano or now.year
        mes_ant = mes_ref - 1 if mes_ref > 1 else 12
        ano_ant = ano_ref if mes_ref > 1 else ano_ref - 1

        total_mes = await lancamento_repo.sum_mes(db, mes_ref, ano_ref)
        total_ant = await lancamento_repo.sum_mes(db, mes_ant, ano_ant)
        por_setor_raw = await lancamento_repo.gastos_por_setor_mes(db, mes_ref, ano_ref)

        if setor or tipo:
            recentes = await lancamento_repo.list_filtrados(
                db, setor=setor, tipo=tipo, mes=mes_ref, ano=ano_ref, limit=30
            )
        else:
            recentes = await lancamento_repo.list_recentes(db, 15)

        qtd = await db.scalar(
            select(func.count(Lancamento.id)).where(
                and_(
                    extract("month", Lancamento.data_hora) == mes_ref,
                    extract("year", Lancamento.data_hora) == ano_ref,
                )
            )
        )

        projecao_proximo = await projecao_service.total_projecao_proximo_mes(db)
        dias = max(now.day if mes_ref == now.month and ano_ref == now.year else 30, 1)
        media = total_mes / Decimal(dias)

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

        projecoes = await projecao_service.calcular_projecoes(db)
        cortes_raw = await projecao_service.calcular_cortes(db)
        cortes = CortesAnaliticos(
            por_tipo=[TipoGasto(**t) for t in cortes_raw["por_tipo"]],
            continua_proximo_mes=cortes_raw["continua_proximo_mes"],
            nao_volta_proximo_mes=cortes_raw["nao_volta_proximo_mes"],
            recorrentes_estimados=cortes_raw["recorrentes_estimados"],
            projecao_proximo_mes=cortes_raw["projecao_proximo_mes"],
        )

        return DashboardData(
            kpis=DashboardKPIs(
                total_mes=total_mes,
                total_mes_anterior=total_ant,
                qtd_lancamentos_mes=qtd or 0,
                media_diaria=media.quantize(Decimal("0.01")),
                projecao_mes=projecao_proximo.quantize(Decimal("0.01")),
            ),
            por_setor=por_setor,
            lancamentos_recentes=lanc_items,
            projecoes=projecoes,
            ofensores=por_setor[:3],
            cortes=cortes,
        )


dashboard_service = DashboardService()
