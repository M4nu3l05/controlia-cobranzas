import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.user import User
from app.services.user_service import admin_update_user_service


def _user(username: str, role: str, email: str) -> User:
    return User(
        username=username,
        email=email,
        password_hash="test",
        salt="test",
        role=role,
        is_active=True,
    )


def test_admin_can_rename_executive_without_losing_cartera_assignment():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])

    with Session(engine) as db:
        admin = _user("Administrador", "admin", "admin@example.com")
        executive = _user(
            "María Pérez González",
            "supervisor",
            "ejecutiva@example.com",
        )
        db.add_all([admin, executive])
        db.commit()

        db.execute(text("""
            CREATE TABLE cartera_asignaciones (
                empresa TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                is_primary BOOLEAN NOT NULL DEFAULT 0,
                email TEXT,
                username TEXT,
                updated_at TEXT,
                updated_by TEXT,
                PRIMARY KEY (empresa, user_id)
            )
        """))
        db.execute(
            text("""
                INSERT INTO cartera_asignaciones(empresa, user_id, is_primary, email, username)
                VALUES ('Consalud', :user_id, 1, :email, :username)
            """),
            {
                "user_id": executive.id,
                "email": executive.email,
                "username": executive.username,
            },
        )
        db.commit()

        updated = admin_update_user_service(
            db,
            executor=admin,
            target_user_id=executive.id,
            username="María Pérez",
        )

        assignment = db.execute(
            text("SELECT user_id, email, username FROM cartera_asignaciones")
        ).mappings().one()
        assert updated.username == "María Pérez"
        assert assignment["user_id"] == executive.id
        assert assignment["email"] == "ejecutiva@example.com"
        assert assignment["username"] == "María Pérez"


def test_non_admin_cannot_rename_user():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])

    with Session(engine) as db:
        supervisor = _user("Supervisor", "supervisor", "supervisor@example.com")
        executive = _user("Ejecutiva", "ejecutivo", "ejecutiva@example.com")
        db.add_all([supervisor, executive])
        db.commit()

        with pytest.raises(ValueError, match="permiso"):
            admin_update_user_service(
                db,
                executor=supervisor,
                target_user_id=executive.id,
                username="Nombre nuevo",
            )
