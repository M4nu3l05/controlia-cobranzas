from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401 - registra todos los modelos en Base.metadata
from app.db.session import Base
from app.services.deudor_schema_service import ensure_deudores_optional_columns
from app.services.gestion_service import ensure_gestiones_optional_columns
from app.services.user_service import ensure_cartera_assignments_table


@dataclass(frozen=True)
class BackendMigration:
    version: int
    description: str
    apply: Callable[[Session], None]


LEGACY_TABLES = (
    "users",
    "deudores_resumen",
    "deudores_detalle",
    "deudores_gestiones",
    "email_templates",
    "user_session_history",
    "legal_acceptance_current",
    "legal_acceptance_events",
    "password_recovery_requests",
    "password_reset_tokens",
)

OPERATIONS_TABLES = (
    "customer_change_audit",
    "user_notifications",
    "derivation_tracking",
    "cartera_temporary_replacements",
)

PAYMENT_TABLES = (
    "payment_transactions",
    "payment_allocations",
    "payment_receipts",
    "payment_reversals",
)

MONTHLY_IMPORT_TABLES = (
    "debtor_import_batches",
    "debtor_birlado_transitions",
)


def _create_tables(db: Session, names: tuple[str, ...]) -> None:
    connection = db.connection()
    for name in names:
        Base.metadata.tables[name].create(bind=connection, checkfirst=True)


def _migration_1_legacy_schema(db: Session) -> None:
    _create_tables(db, LEGACY_TABLES)
    ensure_deudores_optional_columns(db)
    ensure_gestiones_optional_columns(db)
    ensure_cartera_assignments_table(db)


def _migration_2_operations(db: Session) -> None:
    _create_tables(db, OPERATIONS_TABLES)


def _migration_3_payment_ledger(db: Session) -> None:
    _create_tables(db, PAYMENT_TABLES)


def _migration_4_monthly_import_control(db: Session) -> None:
    _create_tables(db, MONTHLY_IMPORT_TABLES)


def _migration_5_legacy_debtor_compatibility(db: Session) -> None:
    dialect = db.get_bind().dialect.name
    columns = {
        "deudores_resumen": {
            "ejecutivo_asignado": "VARCHAR(255)",
            "analista_asignado": "VARCHAR(255)",
        },
        "deudores_detalle": {
            "ejecutivo_asignado": "VARCHAR(255)",
            "analista_asignado": "VARCHAR(255)",
            "endoso": "VARCHAR(80)",
            "periodo": "VARCHAR(40)",
            "cuota": "VARCHAR(40)",
            "fecha_vencimiento": "VARCHAR(40)",
            "moneda": "VARCHAR(20)",
            "impago_en_mo": "VARCHAR(80)",
            "observaciones": "TEXT",
            "compania": "VARCHAR(120)",
            "fecha_corte_beneficios": "VARCHAR(40)",
        },
    }
    for table_name, table_columns in columns.items():
        if dialect == "sqlite":
            existing = {
                str(row[1]) for row in db.execute(text(f"PRAGMA table_info({table_name})")).all()
            }
        else:
            existing = {
                str(row[0]) for row in db.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :table_name
                """), {"table_name": table_name}).all()
            }
        for column_name, sql_type in table_columns.items():
            if column_name in existing:
                continue
            db.execute(text(
                f'ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type} NOT NULL DEFAULT \'\''
            ))


MIGRATIONS = (
    BackendMigration(1, "Registrar y completar el esquema CRM heredado", _migration_1_legacy_schema),
    BackendMigration(2, "Auditoría, notificaciones, derivaciones y reemplazos", _migration_2_operations),
    BackendMigration(3, "Libro financiero inmutable de pagos", _migration_3_payment_ledger),
    BackendMigration(4, "Control de cargas mensuales y transiciones a Birlado", _migration_4_monthly_import_control),
    BackendMigration(5, "Compatibilidad con campos históricos de carteras", _migration_5_legacy_debtor_compatibility),
)


def _ensure_migrations_table(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS backend_schema_migrations (
            version INTEGER PRIMARY KEY,
            description VARCHAR(255) NOT NULL,
            applied_at TIMESTAMP NOT NULL
        )
    """))
    db.commit()


def applied_versions(db: Session) -> set[int]:
    _ensure_migrations_table(db)
    return {int(row[0]) for row in db.execute(text(
        "SELECT version FROM backend_schema_migrations ORDER BY version"
    )).all()}


def apply_backend_migrations(db: Session) -> list[int]:
    applied = applied_versions(db)
    executed: list[int] = []
    for migration in sorted(MIGRATIONS, key=lambda item: item.version):
        if migration.version in applied:
            continue
        try:
            migration.apply(db)
            db.execute(
                text("""
                    INSERT INTO backend_schema_migrations(version, description, applied_at)
                    VALUES (:version, :description, CURRENT_TIMESTAMP)
                """),
                {
                    "version": migration.version,
                    "description": migration.description,
                },
            )
            db.commit()
            executed.append(migration.version)
        except Exception:
            db.rollback()
            raise
    return executed
