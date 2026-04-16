from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DeudorGestion(Base):
    __tablename__ = "deudores_gestiones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="")
    rut_afiliado: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    nombre_afiliado: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    tipo_gestion: Mapped[str] = mapped_column(String(80), nullable=False, default="Manual")
    estado: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    fecha_gestion: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    observacion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origen: Mapped[str] = mapped_column(String(80), nullable=False, default="manual")
    assigned_to_user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

