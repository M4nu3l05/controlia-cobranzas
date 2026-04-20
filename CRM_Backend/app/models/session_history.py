from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserSessionHistory(Base):
    __tablename__ = "user_session_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    login_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), index=True)
    logout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    auth_source: Mapped[str] = mapped_column(String(40), nullable=False, default="backend")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
