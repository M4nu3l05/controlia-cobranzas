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
        db.commit()
        return

    if dialect in {"postgresql", "postgres"}:
        db.execute(
            text(
                "ALTER TABLE deudores_detalle "
                "ADD COLUMN IF NOT EXISTS cart56_dias_pagar VARCHAR(40) NOT NULL DEFAULT ''"
            )
        )
        db.commit()
        return

    # Fallback seguro: intentar y continuar si no aplica para el motor.
    try:
        db.execute(
            text(
                "ALTER TABLE deudores_detalle "
                "ADD COLUMN cart56_dias_pagar VARCHAR(40)"
            )
        )
        db.commit()
    except Exception:
        db.rollback()
