from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DebtorUserAssignment(Base):
    __tablename__ = "debtor_user_assignments"
    __table_args__ = (
        UniqueConstraint("empresa", "rut_afiliado", name="uq_debtor_assignment_empresa_rut"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rut_afiliado: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    normalized_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DebtorAssignmentAlias(Base):
    __tablename__ = "debtor_assignment_aliases"
    __table_args__ = (
        UniqueConstraint("empresa", "normalized_label", name="uq_debtor_assignment_alias"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    normalized_label: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DebtorAssignmentAudit(Base):
    __tablename__ = "debtor_assignment_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rut_afiliado: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    previous_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    new_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_file: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), index=True
    )
