from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FaturaImportada(Base):
    __tablename__ = "faturas_importadas"

    id: Mapped[int] = mapped_column(primary_key=True)
    cartao_id: Mapped[int] = mapped_column(ForeignKey("cartoes.id"), nullable=False)
    arquivo_referencia: Mapped[str | None] = mapped_column(String(500))
    periodo_referencia: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cartao = relationship("Cartao", back_populates="faturas")
    lancamentos = relationship("Lancamento", back_populates="fatura")
