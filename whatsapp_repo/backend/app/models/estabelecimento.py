from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Estabelecimento(Base):
    __tablename__ = "estabelecimentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome_exibicao: Mapped[str] = mapped_column(String(200), nullable=False)
    nome_fatura: Mapped[str | None] = mapped_column(String(300))
    setor_id: Mapped[int | None] = mapped_column(ForeignKey("setores.id"))
    obs: Mapped[str | None] = mapped_column(String(300))

    setor = relationship("Setor", back_populates="estabelecimentos")
    lancamentos = relationship("Lancamento", back_populates="estabelecimento")
