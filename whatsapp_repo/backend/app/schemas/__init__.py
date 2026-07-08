from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExtracaoLancamento(BaseModel):
    intencao: Literal[
        "novo_gasto", "correcao", "consulta", "resumo_mes", "cadastro_cartao", "confirmacao", "outro"
    ] = "novo_gasto"
    estabelecimento: str | None = None
    setor: str | None = None
    tipo: Literal["a_vista", "assinatura", "fixo", "parcelado"] | None = None
    valor: Decimal | None = None
    parcelas: str | None = None
    data_hora: datetime | None = None
    confianca: float = Field(default=0.0, ge=0.0, le=1.0)
    campos_faltantes: list[str] = Field(default_factory=list)
    resposta_texto: str | None = None
    mudou_contexto: bool = False


class CartaoCreate(BaseModel):
    banco_origem: str
    ultimos_4_digitos: str
    vencimento: str | None = None
    bandeira: str | None = None
    limite_total: Decimal | None = None
    cartao_padrao: str = "sim"
    obs: str | None = None


class LancamentoResponse(BaseModel):
    id: int
    estabelecimento: str
    setor: str
    tipo: str
    valor: Decimal
    parcelas: str | None
    data_hora: datetime
    origem: str
    cartao_id: int

    model_config = {"from_attributes": True}


class LancamentoListItem(BaseModel):
    id: int
    estabelecimento: str
    setor: str
    tipo: str
    valor: Decimal
    parcelas: str | None
    data_hora: datetime
    origem: str

    model_config = {"from_attributes": True}


class DashboardKPIs(BaseModel):
    total_mes: Decimal
    total_mes_anterior: Decimal
    qtd_lancamentos_mes: int
    media_diaria: Decimal
    projecao_mes: Decimal


class SetorGasto(BaseModel):
    setor: str
    total: Decimal
    percentual: float


class ProjecaoItem(BaseModel):
    mes: str
    valor: Decimal
    tipo: str


class DashboardData(BaseModel):
    kpis: DashboardKPIs
    por_setor: list[SetorGasto]
    lancamentos_recentes: list[LancamentoListItem]
    projecoes: list[ProjecaoItem]
    ofensores: list[SetorGasto]


class WebhookMessage(BaseModel):
    event: str | None = None
    instance: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
