import base64
import sys
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401
from app.core.authorization import AuthorizationError
from app.db.session import Base
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion
from app.models.payment import PaymentAllocation, PaymentReceipt, PaymentReversal, PaymentTransaction
from app.models.user import User
from app.services.deudor_service import registrar_pago_service
from app.services.gestion_service import delete_gestion_service


@pytest.fixture()
def payment_context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        supervisor = User(
            email="supervisor@test.cl",
            username="Supervisora",
            password_hash="test",
            salt="test",
            role="supervisor",
            is_active=True,
        )
        executive = User(
            email="ejecutiva@test.cl",
            username="Ejecutiva",
            password_hash="test",
            salt="test",
            role="ejecutivo",
            is_active=True,
        )
        admin = User(
            email="admin@test.cl",
            username="Admin",
            password_hash="test",
            salt="test",
            role="admin",
            is_active=True,
        )
        db.add_all([supervisor, executive, admin])
        db.flush()
        details = [
            DeudorDetalle(
                empresa="Cart-56",
                rut_afiliado="11111111",
                dv="1",
                rut_completo="11111111-1",
                nombre_afiliado="Persona Demo",
                nro_expediente="EXP-1",
                copago=100,
                total_pagos=0,
                saldo_actual=100,
            ),
            DeudorDetalle(
                empresa="Cart-56",
                rut_afiliado="11111111",
                dv="1",
                rut_completo="11111111-1",
                nombre_afiliado="Persona Demo",
                nro_expediente="EXP-2",
                copago=150,
                total_pagos=0,
                saldo_actual=150,
            ),
        ]
        db.add_all(details)
        db.add(
            DeudorResumen(
                empresa="Cart-56",
                rut_afiliado="11111111",
                dv="1",
                rut_completo="11111111-1",
                nombre_afiliado="Persona Demo",
                copago=250,
                total_pagos=0,
                saldo_actual=250,
            )
        )
        db.commit()
        yield db, supervisor, executive, admin, details


def test_pago_distribuido_es_inmutable_idempotente_y_admite_comprobante(payment_context):
    db, _, executive, _, details = payment_context
    key = "payment-test-key-001"
    receipt = base64.b64encode(b"fake-pdf-content").decode("ascii")

    result = registrar_pago_service(
        db,
        executor=executive,
        rut="11111111",
        empresa="Cart-56",
        expediente="EXP-1",
        tipo_pago="Abono a la deuda",
        monto=250,
        fecha_efectiva=date(2026, 6, 20),
        idempotency_key=key,
        distribucion=[
            {"detalle_id": details[0].id, "monto": 100},
            {"detalle_id": details[1].id, "monto": 150},
        ],
        comprobante_nombre="comprobante.pdf",
        comprobante_tipo="application/pdf",
        comprobante_base64=receipt,
    )
    assert result.transaction_id
    assert db.query(PaymentTransaction).count() == 1
    assert db.query(PaymentAllocation).count() == 2
    assert db.query(PaymentReceipt).count() == 1

    replay = registrar_pago_service(
        db,
        executor=executive,
        rut="11111111",
        empresa="Cart-56",
        expediente="EXP-1",
        tipo_pago="Abono a la deuda",
        monto=250,
        fecha_efectiva=date(2026, 6, 20),
        idempotency_key=key,
    )
    assert replay.idempotent_replay
    assert db.query(PaymentTransaction).count() == 1
    assert sum(int(row.total_pagos) for row in details) == 250


def test_reversa_restauradora_solo_supervisor(payment_context):
    db, supervisor, executive, admin, details = payment_context
    result = registrar_pago_service(
        db,
        executor=executive,
        rut="11111111",
        empresa="Cart-56",
        expediente="EXP-1",
        tipo_pago="Abono a la deuda",
        monto=100,
        idempotency_key="payment-test-key-002",
        detalle_id=details[0].id,
    )

    payment_management = db.query(DeudorGestion).filter_by(origen="backend_pago").one()
    with pytest.raises(AuthorizationError):
        delete_gestion_service(db, gestion_id=payment_management.id, executor=admin)

    delete_gestion_service(db, gestion_id=payment_management.id, executor=supervisor)
    db.refresh(details[0])
    db.refresh(payment_management)
    transaction = db.query(PaymentTransaction).one()
    assert transaction.status == "reversed"
    assert db.query(PaymentReversal).count() == 1
    assert payment_management.estado == "Pago revertido"
    assert db.query(DeudorGestion).count() == 1
    assert int(details[0].total_pagos) == 0
    assert int(details[0].saldo_actual) == 100
