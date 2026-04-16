from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DeudorResumen(Base):
    __tablename__ = "deudores_resumen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    rut_afiliado: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    dv: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    rut_completo: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    nombre_afiliado: Mapped[str] = mapped_column(String(255), nullable=False)

    estado_deudor: Mapped[str] = mapped_column(String(80), nullable=False, default="Sin Gestión")
    bn: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    nro_expediente: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    max_emision_ok: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    min_emision_ok: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    copago: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_pagos: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    saldo_actual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    source_file: Mapped[str] = mapped_column(Text, nullable=False, default="")
    periodo_carga: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="")

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


class DeudorDetalle(Base):
    __tablename__ = "deudores_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    rut_afiliado: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    dv: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    rut_completo: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    nombre_afiliado: Mapped[str] = mapped_column(String(255), nullable=False)

    mail_afiliado: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    bn: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    telefono_fijo_afiliado: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    telefono_movil_afiliado: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    nro_expediente: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="")
    fecha_emision: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    copago: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_pagos: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    saldo_actual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    cart56_fecha_recep: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    cart56_fecha_recep_isa: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    cart56_dias_pagar: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    cart56_mto_pagar: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    mail_emp: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    telefono_empleador: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    estado_deudor: Mapped[str] = mapped_column(String(80), nullable=False, default="Sin Gestión")

    source_file: Mapped[str] = mapped_column(Text, nullable=False, default="")
    periodo_carga: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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

