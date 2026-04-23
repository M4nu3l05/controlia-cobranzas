from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_deudores_optional_columns(db: Session) -> None:
    """
    Asegura columnas opcionales nuevas en instalaciones existentes
    sin depender de una herramienta externa de migraciones.
    """
    bind = getattr(db, "bind", None)
    dialect_obj = getattr(bind, "dialect", None) if bind is not None else None
    dialect = str(getattr(dialect_obj, "name", "") or "").lower()

    if dialect == "sqlite":
        rows = db.execute(text("PRAGMA table_info(deudores_detalle)")).mappings().all()
        cols = {str(r.get("name") or "").strip() for r in rows}
        if "cart56_dias_pagar" not in cols:
            db.execute(
                text(
                    "ALTER TABLE deudores_detalle "
                    "ADD COLUMN cart56_dias_pagar TEXT NOT NULL DEFAULT ''"
                )
            )
        if "nombre_afil" not in cols:
            db.execute(
                text(
                    "ALTER TABLE deudores_detalle "
                    "ADD COLUMN nombre_afil TEXT NOT NULL DEFAULT ''"
                )
            )
        if "rut_afil" not in cols:
            db.execute(
                text(
                    "ALTER TABLE deudores_detalle "
                    "ADD COLUMN rut_afil TEXT NOT NULL DEFAULT ''"
                )
            )
        if "fecha_pago" not in cols:
            db.execute(
                text(
                    "ALTER TABLE deudores_detalle "
                    "ADD COLUMN fecha_pago TEXT NOT NULL DEFAULT ''"
                )
            )
        db.commit()
        return

    if dialect in {"postgresql", "postgres"}:
        db.execute(
            text(
                "ALTER TABLE deudores_detalle "
                "ADD COLUMN IF NOT EXISTS cart56_dias_pagar VARCHAR(40) NOT NULL DEFAULT ''"
            )
        )
        db.execute(
            text(
                "ALTER TABLE deudores_detalle "
                "ADD COLUMN IF NOT EXISTS nombre_afil VARCHAR(255) NOT NULL DEFAULT ''"
            )
        )
        db.execute(
            text(
                "ALTER TABLE deudores_detalle "
                "ADD COLUMN IF NOT EXISTS rut_afil VARCHAR(32) NOT NULL DEFAULT ''"
            )
        )
        db.execute(
            text(
                "ALTER TABLE deudores_detalle "
                "ADD COLUMN IF NOT EXISTS fecha_pago VARCHAR(40) NOT NULL DEFAULT ''"
            )
        )
        db.commit()
        return

    # Fallback seguro: intentar y continuar si no aplica para el motor.
    try:
        for stmt in (
            "ALTER TABLE deudores_detalle ADD COLUMN cart56_dias_pagar VARCHAR(40)",
            "ALTER TABLE deudores_detalle ADD COLUMN nombre_afil VARCHAR(255)",
            "ALTER TABLE deudores_detalle ADD COLUMN rut_afil VARCHAR(32)",
            "ALTER TABLE deudores_detalle ADD COLUMN fecha_pago VARCHAR(40)",
        ):
            try:
                db.execute(text(stmt))
            except Exception:
                db.rollback()
        db.commit()
    except Exception:
        db.rollback()
