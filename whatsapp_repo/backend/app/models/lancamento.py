from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Lancamento(Base):
    __tablename__ = "lancamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    estabelecimento_id: Mapped[int] = mapped_column(ForeignKey("estabelecimentos.id"), nullable=False)
    setor_id: Mapped[int] = mapped_column(ForeignKey("setores.id"), nullable=False)
    cartao_id: Mapped[int] = mapped_column(ForeignKey("cartoes.id"), nullable=False)
    fatura_id: Mapped[int | None] = mapped_column(ForeignKey("faturas_importadas.id"))
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    parcelas: Mapped[str | None] = mapped_column(String(20))
    data_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origem: Mapped[str] = mapped_column(String(30), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(100))
    key_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    estabelecimento = relationship("Estabelecimento", back_populates="lancamentos")
    setor = relationship("Setor", back_populates="lancamentos")
    cartao = relationship("Cartao", back_populates="lancamentos")
    fatura = relationship("FaturaImportada", back_populates="lancamentos")
