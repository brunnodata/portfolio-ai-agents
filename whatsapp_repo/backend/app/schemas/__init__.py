from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExtracaoLancamento(BaseModel):
    intencao: Literal[
        "novo_gasto", "correcao", "consulta", "resumo_mes", "cadastro_cartao", "confirmacao", "outro"
    ] = "novo_gasto"
    estabelecimento: str | None = None
    item: str | None = None
    setor: str | None = None
    tipo: Literal["a_vista", "assinatura", "fixo", "parcelado"] | None = None
    valor: Decimal | None = None
    parcelas: str | None = None
    data_hora: datetime | None = None
    confianca: float = Field(default=0.0, ge=0.0, le=1.0)
    campos_faltantes: list[str] = Field(default_factory=list)
    resposta_texto: str | None = None
    mudou_contexto: bool = False
    acao_correcao: Literal["apagar", "editar"] | None = None
    campos_correcao: dict[str, Any] | None = None
    lancamento_alvo: Literal["ultimo", "especifico"] | None = None
    tipo_consulta: Literal["limite", "setor", "total_mes"] | None = None


class CartaoCreate(BaseModel):
    banco_origem: str
    ultimos_4_digitos: str
    vencimento: str | None = None
    bandeira: str | None = None
    limite_total: Decimal | None = None
    cartao_padrao: str = "nao"
    obs: str | None = None


class CartaoUpdate(BaseModel):
    banco_origem: str | None = None
    ultimos_4_digitos: str | None = None
    vencimento: str | None = None
    bandeira: str | None = None
    limite_total: Decimal | None = None
    cartao_padrao: str | None = None
    obs: str | None = None


class CartaoResponse(BaseModel):
    id: int
    banco_origem: str
    ultimos_4_digitos: str
    vencimento: str | None = None
    bandeira: str | None = None
    limite_total: float | None = None
    limite_em_uso: float | None = None
    limite_restante: float | None = None
    qt_assinaturas: int = 0
    valores_futuros: dict[str, float] = Field(default_factory=dict)
    cartao_padrao: str
    obs: str | None = None

    model_config = {"from_attributes": True}


class LancamentoResponse(BaseModel):
    id: int
    item: str | None = None
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
    item: str | None = None
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
    descricao: str | None = None


class TipoGasto(BaseModel):
    tipo: str
    total: Decimal
    percentual: float


class CortesAnaliticos(BaseModel):
    por_tipo: list[TipoGasto]
    continua_proximo_mes: Decimal
    nao_volta_proximo_mes: Decimal
    recorrentes_estimados: Decimal
    projecao_proximo_mes: Decimal


class DashboardData(BaseModel):
    kpis: DashboardKPIs
    por_setor: list[SetorGasto]
    lancamentos_recentes: list[LancamentoListItem]
    projecoes: list[ProjecaoItem]
    ofensores: list[SetorGasto]
    cortes: CortesAnaliticos


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
