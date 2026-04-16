from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PasswordRecoveryRequest(Base):
    __tablename__ = "password_recovery_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    requested_email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    target_role: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    required_assistor_role: Mapped[str] = mapped_column(String(30), nullable=False, default="")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    resolution_note: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
