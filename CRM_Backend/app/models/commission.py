from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CommissionRate(Base):
    """Porcentaje de comisión vigente para una cartera."""

    __tablename__ = "commission_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    percent: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_username: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CommissionReset(Base):
    """Corte de comisiones: los pagos anteriores dejan de acumular."""

    __tablename__ = "commission_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL = corte global para todas las ejecutivas.
    scope_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    total_paid_clp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_commission_clp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_by_username: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
