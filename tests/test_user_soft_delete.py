from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401 - registra todos los modelos relacionados
from app.db.session import Base
from app.models.operations import CustomerChangeAudit
from app.models.payment import PaymentTransaction
from app.models.reset_token import PasswordResetToken
from app.models.session_history import UserSessionHistory
from app.models.user import User
from app.services.auth_service import authenticate_user, create_user, get_user_by_email
from app.services.user_service import admin_delete_user_service, admin_list_users_service


def _user(email: str, role: str) -> User:
    return User(
        email=email,
        username=email.split("@", 1)[0],
        password_hash="invalid",
        salt="invalid",
        role=role,
        is_active=True,
    )


def test_soft_delete_revokes_access_and_preserves_history_and_email_reuse():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = _user("admin@example.com", "admin")
        target = _user("person@example.com", "supervisor")
        db.add_all([admin, target])
        db.flush()
        db.add(UserSessionHistory(
            user_id=target.id,
            email=target.email,
            username=target.username,
            role=target.role,
        ))
        db.add(PaymentTransaction(
            public_id="payment-test-1",
            idempotency_key="payment-test-key-1",
            empresa="Colmena",
            rut_afiliado="11111111",
            payment_type="Abono",
            amount_clp=1000,
            effective_date=date(2026, 10, 17),
            registered_by_user_id=target.id,
            registered_by_username=target.username,
        ))
        db.add(CustomerChangeAudit(
            empresa="Colmena",
            rut_original="11111111",
            field_name="correo",
            old_value="old@example.test",
            new_value="new@example.test",
            changed_by_user_id=target.id,
            changed_by_username=target.username,
        ))
        db.add(PasswordResetToken(
            user_id=target.id,
            token="123456",
            expires_at=datetime.now() + timedelta(minutes=15),
            used=False,
        ))
        db.execute(text("""
            CREATE TABLE cartera_asignaciones (
                empresa TEXT NOT NULL, user_id INTEGER NOT NULL,
                is_primary BOOLEAN NOT NULL DEFAULT 0, email TEXT, username TEXT,
                updated_at TEXT, updated_by TEXT, PRIMARY KEY (empresa, user_id)
            )
        """))
        db.execute(
            text("INSERT INTO cartera_asignaciones(empresa, user_id) VALUES ('Colmena', :uid)"),
            {"uid": target.id},
        )
        db.commit()
        target_id = int(target.id)

        admin_delete_user_service(db, executor=admin, target_user_id=target_id)

        deleted = db.query(User).filter(User.id == target_id).one()
        assert deleted.deleted_at is not None
        assert deleted.deleted_by_user_id == admin.id
        assert deleted.is_active is False
        assert deleted.email.endswith("@example.com")
        assert get_user_by_email(db, "person@example.com") is None
        assert all(item.id != target_id for item in admin_list_users_service(db))
        assert db.query(PaymentTransaction).filter_by(registered_by_user_id=target_id).count() == 1
        assert db.query(CustomerChangeAudit).filter_by(changed_by_user_id=target_id).count() == 1
        assert db.query(UserSessionHistory).filter_by(user_id=target_id).one().logout_at is None
        assert db.query(PasswordResetToken).filter_by(user_id=target_id).one().used is True
        assert db.execute(
            text("SELECT COUNT(*) FROM cartera_asignaciones WHERE user_id = :uid"),
            {"uid": target_id},
        ).scalar_one() == 0

        replacement = create_user(
            db,
            email="person@example.com",
            username="Nueva Persona",
            password="NuevaClave9",
            role="supervisor",
        )
        assert replacement.email == "person@example.com"
        with pytest.raises(ValueError):
            authenticate_user(db, deleted.email, "NuevaClave9")


def test_soft_delete_protects_self_and_last_active_admin():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = _user("admin@example.com", "admin")
        other_admin = _user("other-admin@example.com", "admin")
        other_admin.is_active = False
        db.add_all([admin, other_admin])
        db.commit()

        with pytest.raises(ValueError, match="propia"):
            admin_delete_user_service(db, executor=admin, target_user_id=admin.id)
        with pytest.raises(ValueError, match="ultimo administrador"):
            admin_delete_user_service(db, executor=other_admin, target_user_id=admin.id)
