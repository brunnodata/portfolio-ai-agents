from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HistoricoMensagem(Base):
    __tablename__ = "historico_mensagens"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str | None] = mapped_column(String(100))
    key_id: Mapped[str | None] = mapped_column(String(100))
    tipo_mensagem: Mapped[str] = mapped_column(String(20), nullable=False)
    conteudo_original: Mapped[str | None] = mapped_column(Text)
    conteudo_processado: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="recebido")
    phone_number: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
