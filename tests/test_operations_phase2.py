import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401
from app.core.authorization import can_operate_company
from app.db.session import Base
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.operations import CustomerChangeAudit, DerivationTracking, UserNotification
from app.models.user import User
from app.schemas.gestion import GestionCreateRequest
from app.schemas.operations import ReplacementCreateRequest
from app.services.deudor_service import update_deudor_cliente_service
from app.services.gestion_service import (
    create_gestion_service,
    delete_gestion_service,
    marcar_gestion_asignada_realizada_service,
)
from app.services.operations_service import create_replacement_service


@pytest.fixture()
def operation_context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(
            text(
                """
                CREATE TABLE cartera_asignaciones (
                    empresa TEXT PRIMARY KEY,
                    user_id INTEGER NULL,
                    email TEXT,
                    username TEXT,
                    updated_at TEXT,
                    updated_by TEXT
                )
                """
            )
        )
        users = []
        for email, username, role in (
            ("admin@test.cl", "Admin", "admin"),
            ("supervisor@test.cl", "Super", "supervisor"),
            ("titular@test.cl", "Titular", "ejecutivo"),
            ("otra@test.cl", "Otra", "ejecutivo"),
        ):
            user = User(
                email=email,
                username=username,
                password_hash="test",
                salt="test",
                role=role,
                is_active=True,
                must_change_password=False,
            )
            db.add(user)
            users.append(user)
        db.flush()
        admin, supervisor, titular, otra = users
        db.execute(
            text(
                """
                INSERT INTO cartera_asignaciones(empresa, user_id, email, username)
                VALUES ('Cart-56', :user_id, :email, :username)
                """
            ),
            {"user_id": titular.id, "email": titular.email, "username": titular.username},
        )
        db.add(
            DeudorResumen(
                empresa="Cart-56",
                rut_afiliado="11111111",
                dv="1",
                rut_completo="11111111-1",
                nombre_afiliado="Persona Demo",
                bn="old@example.com",
                copago=1000,
                total_pagos=0,
                saldo_actual=1000,
            )
        )
        db.add(
            DeudorDetalle(
                empresa="Cart-56",
                rut_afiliado="11111111",
                dv="1",
                rut_completo="11111111-1",
                nombre_afiliado="Persona Demo",
                mail_afiliado="old@example.com",
                bn="old@example.com",
                telefono_movil_afiliado="111",
                copago=1000,
                total_pagos=0,
                saldo_actual=1000,
            )
        )
        db.commit()
        yield db, admin, supervisor, titular, otra


def test_edicion_ajena_audita_y_notifica_propietaria(operation_context):
    db, _, _, titular, otra = operation_context
    update_deudor_cliente_service(
        db,
        executor=otra,
        rut="11111111",
        empresa="Cart-56",
        rut_nuevo="11111111-1",
        nombre="Persona Demo",
        correo="new@example.com",
        correo_excel="old@example.com",
        telefono_movil="222",
    )
    assert db.query(CustomerChangeAudit).count() == 2
    notification = db.query(UserNotification).filter_by(
        user_id=titular.id,
        notification_type="customer_data_changed",
    ).one()
    assert "correo" in notification.message


def test_derivacion_guarda_plazo_y_notifica_resultado(operation_context):
    db, _, _, titular, otra = operation_context
    item = create_gestion_service(
        db,
        rut="11111111",
        payload=GestionCreateRequest(
            empresa="Cart-56",
            nombre_afiliado="Persona Demo",
            tipo_gestion="Manual",
            estado="Gestion asignada",
            fecha_gestion="01/01/2026",
            observacion="Contacto recibido por otra cartera",
            assigned_to_user_id=titular.id,
        ),
        executor=otra,
    )
    assert item.derivation_due_at is not None
    tracking = db.query(DerivationTracking).filter_by(gestion_id=item.id).one()
    assert tracking.created_by_user_id == otra.id

    marcar_gestion_asignada_realizada_service(db, gestion_id=item.id, executor=titular)
    assert db.query(UserNotification).filter_by(
        user_id=otra.id,
        notification_type="derivation_completed",
    ).count() == 1


def test_eliminar_derivacion_limpia_tracking_asociado(operation_context):
    db, _, _, titular, otra = operation_context
    item = create_gestion_service(
        db,
        rut="11111111",
        payload=GestionCreateRequest(
            empresa="Cart-56",
            nombre_afiliado="Persona Demo",
            tipo_gestion="Manual",
            estado="Gestion asignada",
            fecha_gestion="01/01/2026",
            observacion="Contacto recibido por otra cartera",
            assigned_to_user_id=titular.id,
        ),
        executor=otra,
    )
    assert db.query(DerivationTracking).filter_by(gestion_id=item.id).count() == 1

    delete_gestion_service(db, gestion_id=item.id, executor=titular)

    assert db.query(DerivationTracking).filter_by(gestion_id=item.id).count() == 0


def test_reemplazo_temporal_habilita_cartera_sin_compartir_credenciales(operation_context):
    db, _, supervisor, _, otra = operation_context
    replacement = create_replacement_service(
        db,
        executor=supervisor,
        payload=ReplacementCreateRequest(
            empresa="Cart-56",
            replacement_user_id=otra.id,
            starts_at=datetime.now() - timedelta(minutes=1),
            ends_at=datetime.now() + timedelta(days=1),
            reason="Vacaciones",
        ),
    )
    assert replacement.is_active
    assert can_operate_company(db, otra, "Cart-56")
