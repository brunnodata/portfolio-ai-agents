from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Cartao(Base):
    __tablename__ = "cartoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    banco_origem: Mapped[str] = mapped_column(String(100), nullable=False)
    ultimos_4_digitos: Mapped[str] = mapped_column(String(4), nullable=False)
    vencimento: Mapped[date | None] = mapped_column(Date)
    bandeira: Mapped[str | None] = mapped_column(String(50))
    limite_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    limite_em_uso: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=0)
    limite_restante: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    qt_assinaturas: Mapped[int] = mapped_column(Integer, default=0)
    valores_futuros: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    cartao_padrao: Mapped[str] = mapped_column(String(3), default="nao")
    obs: Mapped[str | None] = mapped_column(Text)

    lancamentos = relationship("Lancamento", back_populates="cartao")
    faturas = relationship("FaturaImportada", back_populates="cartao")
