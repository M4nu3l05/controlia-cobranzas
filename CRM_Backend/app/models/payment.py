from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    empresa: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rut_afiliado: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payment_type: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_clp: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    observations: Mapped[str] = mapped_column(Text, nullable=False, default="")
    registered_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    registered_by_username: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="confirmed", index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("transaction_id", "deudor_detalle_id", name="uq_payment_allocation_detail"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("payment_transactions.id"), nullable=False, index=True)
    deudor_detalle_id: Mapped[int] = mapped_column(ForeignKey("deudores_detalle.id"), nullable=False, index=True)
    expediente: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    amount_clp: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_before_clp: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after_clp: Mapped[int] = mapped_column(Integer, nullable=False)


class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("payment_transactions.id"), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class PaymentReversal(Base):
    __tablename__ = "payment_reversals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("payment_transactions.id"), unique=True, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reversed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    reversed_by_username: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    reversed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
