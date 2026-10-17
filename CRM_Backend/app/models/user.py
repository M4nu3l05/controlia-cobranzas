from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=False)

    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    salt: Mapped[str] = mapped_column(String(128), nullable=False)

    role: Mapped[str] = mapped_column(String(30), nullable=False, default="supervisor")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, index=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_by_username: Mapped[str] = mapped_column(String(120), nullable=False, default="")

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
