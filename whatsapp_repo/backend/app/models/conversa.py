from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConversaContexto(Base):
    """Memória de conversa por número de telefone (thread WhatsApp)."""

    __tablename__ = "conversa_contexto"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    mensagens: Mapped[list] = mapped_column(JSONB, default=list)
    estado: Mapped[str | None] = mapped_column(String(50))
    dados_estado: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TransacaoPendente(Base):
    """Transações com extração parcial aguardando dados do usuário."""

    __tablename__ = "transacoes_pendentes"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    historico_id: Mapped[int | None] = mapped_column(Integer)
    campos_capturados: Mapped[dict] = mapped_column(JSONB, default=dict)
    campos_faltantes: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pendente")
    origem: Mapped[str | None] = mapped_column(String(30))
    message_id: Mapped[str | None] = mapped_column(String(100))
    key_id: Mapped[str | None] = mapped_column(String(100))
    tentativas_imagem: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
