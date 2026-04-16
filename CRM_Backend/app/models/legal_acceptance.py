from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LegalAcceptanceCurrent(Base):
    __tablename__ = "legal_acceptance_current"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    accepted_terms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepted_privacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terms_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    privacy_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    acceptance_source: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="desktop_app")
    client_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")

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


class LegalAcceptanceEvent(Base):
    __tablename__ = "legal_acceptance_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    accepted_terms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepted_privacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terms_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    privacy_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    acceptance_source: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="desktop_app")
    client_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
