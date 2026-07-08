from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Setor(Base):
    __tablename__ = "setores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    lancamentos = relationship("Lancamento", back_populates="setor")
    estabelecimentos = relationship("Estabelecimento", back_populates="setor")
