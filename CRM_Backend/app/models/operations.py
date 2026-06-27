from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CustomerChangeAudit(Base):
    __tablename__ = "customer_change_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rut_original: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    new_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    changed_by_username: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), index=True)


class UserNotification(Base):
    __tablename__ = "user_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, default="", index=True)
    rut_afiliado: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    related_entity_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    related_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class DerivationTracking(Base):
    __tablename__ = "derivation_tracking"
    __table_args__ = (UniqueConstraint("gestion_id", name="uq_derivation_tracking_gestion"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gestion_id: Mapped[int] = mapped_column(ForeignKey("deudores_gestiones.id"), nullable=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    assigned_to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    completed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class CarteraTemporaryReplacement(Base):
    __tablename__ = "cartera_temporary_replacements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    titular_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    replacement_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class DebtorImportBatch(Base):
    __tablename__ = "debtor_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    imported_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    imported_by_username: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    omitted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    birlado_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), index=True)


class DebtorBirladoTransition(Base):
    __tablename__ = "debtor_birlado_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("debtor_import_batches.id"), nullable=False, index=True)
    detalle_id: Mapped[int] = mapped_column(ForeignKey("deudores_detalle.id"), nullable=False, index=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rut_afiliado: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    nro_expediente: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    previous_status: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), index=True)
