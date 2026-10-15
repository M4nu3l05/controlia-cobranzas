from __future__ import annotations

import hashlib
import sqlite3
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.migrations import _migration_10_supervisor_portfolio_teams
from app.db.session import Base
from app.models.debtor_assignment import (
    DebtorAssignmentAlias,
    DebtorAssignmentAudit,
    DebtorUserAssignment,
)
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.user import User
from app.services.debtor_assignment_service import (
    apply_debtor_assignments_service,
    preview_debtor_assignments_service,
)
from app.services.user_service import (
    ensure_cartera_assignments_table,
    save_cartera_assignments_service,
)
from admin_carteras.view import _m2_migrate_assignment_teams
from auth.auth_db import _m4_promote_executives


def _user(username: str, role: str = "supervisor", *, active: bool = True) -> User:
    slug = "".join(char.lower() for char in username if char.isalnum())
    return User(
        username=username,
        email=f"{slug}@example.test",
        password_hash="test",
        salt="test",
        role=role,
        is_active=active,
    )


def _workbook(rows: list[dict]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Cartera", index=False)
    return output.getvalue()


def _assignment_tables(engine) -> None:
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            DeudorResumen.__table__,
            DeudorDetalle.__table__,
            DebtorUserAssignment.__table__,
            DebtorAssignmentAlias.__table__,
            DebtorAssignmentAudit.__table__,
        ],
    )


def test_migration_promotes_all_executives_and_preserves_legacy_owner_as_primary():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _assignment_tables(engine)
    with Session(engine) as db:
        legacy_owner = _user("Responsable histórica", "ejecutivo", active=False)
        admin = _user("Administrador", "admin")
        db.add_all([legacy_owner, admin])
        db.flush()
        db.execute(text("""
            CREATE TABLE cartera_asignaciones (
                empresa TEXT PRIMARY KEY,
                user_id INTEGER,
                email TEXT,
                username TEXT,
                updated_at TEXT,
                updated_by TEXT
            )
        """))
        db.execute(
            text("""
                INSERT INTO cartera_asignaciones(empresa, user_id, email, username)
                VALUES ('Consalud', :user_id, :email, :username)
            """),
            {
                "user_id": legacy_owner.id,
                "email": legacy_owner.email,
                "username": legacy_owner.username,
            },
        )
        db.add_all([
            DeudorResumen(
                empresa="Consalud", rut_afiliado="11111111", dv="1",
                rut_completo="11111111-1", nombre_afiliado="Persona prueba",
                ejecutivo_asignado="Nombre antiguo",
            ),
            DeudorDetalle(
                empresa="Consalud", rut_afiliado="11111111", dv="1",
                rut_completo="11111111-1", nombre_afiliado="Persona prueba",
                ejecutivo_asignado="Nombre antiguo",
            ),
            DebtorUserAssignment(
                empresa="Consalud",
                rut_afiliado="11111111",
                user_id=legacy_owner.id,
                assigned_by_user_id=admin.id,
            ),
        ])
        db.commit()

        _migration_10_supervisor_portfolio_teams(db)
        db.commit()
        db.expire_all()

        migrated_owner = db.get(User, legacy_owner.id)
        assert migrated_owner.role == "supervisor"
        assert migrated_owner.is_active is False
        assert db.get(User, admin.id).role == "admin"
        assignment = db.execute(text("""
            SELECT empresa, user_id, is_primary FROM cartera_asignaciones
        """)).mappings().one()
        assert assignment == {
            "empresa": "Consalud",
            "user_id": legacy_owner.id,
            "is_primary": 1,
        }
        assert set(inspect(engine).get_pk_constraint("cartera_asignaciones")["constrained_columns"]) == {
            "empresa", "user_id"
        }
        assert db.query(DeudorResumen).one().ejecutivo_asignado == "Responsable histórica"
        assert db.query(DeudorDetalle).one().ejecutivo_asignado == "Responsable histórica"


def test_local_migrations_promote_inactive_users_and_preserve_primary_assignment():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, role TEXT, is_active INTEGER)")
    con.executemany(
        "INSERT INTO users(id, role, is_active) VALUES (?, ?, ?)",
        [(1, "ejecutivo", 1), (2, "ejecutivo", 0), (3, "admin", 1)],
    )
    con.execute("""
        CREATE TABLE cartera_asignaciones (
            empresa TEXT PRIMARY KEY,
            user_id INTEGER,
            email TEXT,
            username TEXT,
            updated_at TEXT,
            updated_by TEXT
        )
    """)
    con.execute("""
        INSERT INTO cartera_asignaciones(empresa, user_id, username)
        VALUES ('Consalud', 1, 'Responsable local')
    """)

    _m4_promote_executives(con)
    _m2_migrate_assignment_teams(con)

    assert con.execute("SELECT id, role, is_active FROM users ORDER BY id").fetchall() == [
        (1, "supervisor", 1),
        (2, "supervisor", 0),
        (3, "admin", 1),
    ]
    assert con.execute("""
        SELECT empresa, user_id, is_primary FROM cartera_asignaciones
    """).fetchall() == [("Consalud", 1, 1)]
    primary_columns = {
        str(row[1]) for row in con.execute("PRAGMA table_info(cartera_asignaciones)")
        if int(row[5] or 0) > 0
    }
    assert primary_columns == {"empresa", "user_id"}
    con.close()


def test_portfolio_accepts_multiple_active_supervisors_and_one_primary_atomically():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        admin = _user("Administrador", "admin")
        primary = _user("Supervisora titular")
        member = _user("Supervisor integrante")
        inactive = _user("Supervisora inactiva", active=False)
        db.add_all([admin, primary, member, inactive])
        db.commit()
        ensure_cartera_assignments_table(db)

        saved = save_cartera_assignments_service(
            db,
            executor=admin,
            assignments=[
                {"empresa": "Consalud", "user_id": primary.id, "is_primary": True},
                {"empresa": "Consalud", "user_id": member.id, "is_primary": False},
            ],
        )
        assert [(item.user_id, item.is_primary) for item in saved] == [
            (primary.id, True),
            (member.id, False),
        ]

        with pytest.raises(ValueError, match="inactivo"):
            save_cartera_assignments_service(
                db,
                executor=admin,
                assignments=[
                    {"empresa": "Consalud", "user_id": member.id, "is_primary": True},
                    {"empresa": "Colmena", "user_id": inactive.id, "is_primary": True},
                ],
            )

        persisted = db.execute(text("""
            SELECT user_id, is_primary FROM cartera_asignaciones
            WHERE empresa = 'Consalud' ORDER BY is_primary DESC, user_id
        """)).all()
        assert persisted == [(primary.id, 1), (member.id, 0)]


def test_blank_responsible_uses_primary_and_missing_or_unknown_responsible_is_rejected():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _assignment_tables(engine)
    with Session(engine) as db:
        admin = _user("Administrador", "admin")
        primary = _user("Supervisora titular")
        db.add_all([admin, primary])
        db.flush()
        db.add(
            DeudorResumen(
                empresa="Consalud", rut_afiliado="11111111", dv="1",
                rut_completo="11111111-1", nombre_afiliado="Persona prueba",
            )
        )
        db.commit()
        ensure_cartera_assignments_table(db)
        save_cartera_assignments_service(
            db,
            executor=admin,
            assignments=[
                {"empresa": "Consalud", "user_id": primary.id, "is_primary": True},
            ],
        )

        blank = _workbook([{"Rut_Afiliado": "11111111", "Ejecutiva": ""}])
        preview = preview_debtor_assignments_service(
            db, empresa="Consalud", content=blank, source_file="blanco.xlsx"
        )
        assert preview["blank_assignments"] == 1
        assert preview["blank_default_user_id"] == primary.id
        result = apply_debtor_assignments_service(
            db,
            empresa="Consalud",
            content=blank,
            source_file="blanco.xlsx",
            executor=admin,
            expected_file_sha256=hashlib.sha256(blank).hexdigest(),
        )
        assert result["assigned_debtors"] == 1
        assert db.query(DebtorUserAssignment).one().user_id == primary.id
        assert db.query(DeudorResumen).one().ejecutivo_asignado == primary.username

        missing_column = _workbook([{"Rut_Afiliado": "11111111", "Monto": 1000}])
        with pytest.raises(ValueError, match="columnas de RUT y Ejecutiva"):
            preview_debtor_assignments_service(
                db,
                empresa="Consalud",
                content=missing_column,
                source_file="sin_responsable.xlsx",
            )

        unknown = _workbook([
            {"Rut_Afiliado": "11111111", "Ejecutiva": "Nombre no registrado"}
        ])
        with pytest.raises(ValueError, match="deben relacionarse"):
            apply_debtor_assignments_service(
                db,
                empresa="Consalud",
                content=unknown,
                source_file="desconocido.xlsx",
                executor=admin,
                expected_file_sha256=hashlib.sha256(unknown).hexdigest(),
            )
        assert db.query(DebtorUserAssignment).one().user_id == primary.id
