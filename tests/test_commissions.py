import sys
from datetime import date, datetime, timedelta, timezone
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
from app.models.payment import PaymentTransaction
from app.models.user import User
from app.services.commission_service import (
    commission_summary_service,
    list_commission_rates_service,
    reset_commissions_service,
    save_commission_rates_service,
)


def _pago(db: Session, *, user: User, empresa: str, monto: int, minutos: int = 0) -> PaymentTransaction:
    # `func.now()` en SQLite entrega UTC, igual que el corte de comisiones.
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    indice = db.query(PaymentTransaction).count() + 1
    row = PaymentTransaction(
        public_id=f"public-{indice}",
        idempotency_key=f"idem-{indice}",
        empresa=empresa,
        rut_afiliado="11111111",
        payment_type="Abono a la deuda",
        amount_clp=int(monto),
        effective_date=date.today(),
        observations="",
        registered_by_user_id=int(user.id),
        registered_by_username=str(user.username),
        status="confirmed",
        registered_at=ahora_utc + timedelta(minutes=minutos),
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def commission_context():
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
        ejecutiva = User(
            email="ejecutiva@test.cl",
            username="Ejecutiva",
            password_hash="test",
            salt="test",
            role="ejecutivo",
            is_active=True,
        )
        otra = User(
            email="otra@test.cl",
            username="Otra ejecutiva",
            password_hash="test",
            salt="test",
            role="ejecutivo",
            is_active=True,
        )
        db.add_all([supervisor, ejecutiva, otra])
        db.commit()
        yield db, supervisor, ejecutiva, otra


def test_solo_supervisor_define_los_porcentajes(commission_context):
    db, supervisor, ejecutiva, _otra = commission_context

    with pytest.raises(AuthorizationError):
        save_commission_rates_service(
            db, executor=ejecutiva, rates=[{"empresa": "Cart-56", "percent": 10}]
        )

    save_commission_rates_service(db, executor=supervisor, rates=[{"empresa": "Cart-56", "percent": 10}])
    tasas = {item.empresa: item.percent for item in list_commission_rates_service(db, executor=ejecutiva)}
    assert tasas == {"Cart-56": 10.0}


def test_porcentaje_fuera_de_rango_es_rechazado(commission_context):
    db, supervisor, _ejecutiva, _otra = commission_context

    with pytest.raises(AuthorizationError):
        save_commission_rates_service(
            db, executor=supervisor, rates=[{"empresa": "Cart-56", "percent": 140}]
        )


def test_la_comision_acumula_por_cada_pago_registrado(commission_context):
    db, supervisor, ejecutiva, _otra = commission_context
    save_commission_rates_service(db, executor=supervisor, rates=[{"empresa": "Cart-56", "percent": 10}])

    _pago(db, user=ejecutiva, empresa="Cart-56", monto=100_000)
    propia = commission_summary_service(db, executor=ejecutiva)
    assert [item.comision_clp for item in propia] == [10_000]

    _pago(db, user=ejecutiva, empresa="Cart-56", monto=1_000_000)
    propia = commission_summary_service(db, executor=ejecutiva)
    assert [item.comision_clp for item in propia] == [110_000]
    assert propia[0].monto_pagado_clp == 1_100_000
    assert propia[0].pagos == 2


def test_los_pagos_reversados_no_suman_comision(commission_context):
    db, supervisor, ejecutiva, _otra = commission_context
    save_commission_rates_service(db, executor=supervisor, rates=[{"empresa": "Cart-56", "percent": 10}])

    pago = _pago(db, user=ejecutiva, empresa="Cart-56", monto=500_000)
    pago.status = "reversed"
    db.commit()

    propia = commission_summary_service(db, executor=ejecutiva)
    assert [item.comision_clp for item in propia] == [0]


def test_la_ejecutiva_solo_ve_su_acumulado_y_el_supervisor_ve_todos(commission_context):
    db, supervisor, ejecutiva, otra = commission_context
    save_commission_rates_service(
        db,
        executor=supervisor,
        rates=[{"empresa": "Cart-56", "percent": 10}, {"empresa": "Colmena", "percent": 5}],
    )
    _pago(db, user=ejecutiva, empresa="Cart-56", monto=1_000_000)
    _pago(db, user=otra, empresa="Colmena", monto=2_000_000)

    propia = commission_summary_service(db, executor=ejecutiva)
    assert [(item.username, item.comision_clp) for item in propia] == [("Ejecutiva", 100_000)]

    del_supervisor = commission_summary_service(db, executor=supervisor)
    assert {item.username: item.comision_clp for item in del_supervisor} == {
        "Ejecutiva": 100_000,
        "Otra ejecutiva": 100_000,
    }


def test_el_corte_deja_el_acumulado_en_cero_y_sigue_sumando_despues(commission_context):
    db, supervisor, ejecutiva, _otra = commission_context
    save_commission_rates_service(db, executor=supervisor, rates=[{"empresa": "Cart-56", "percent": 10}])
    _pago(db, user=ejecutiva, empresa="Cart-56", monto=1_000_000, minutos=-10)

    reset_commissions_service(db, executor=supervisor, user_id=None, note="pago de comisiones")

    propia = commission_summary_service(db, executor=ejecutiva)
    assert [item.comision_clp for item in propia] == [0]

    _pago(db, user=ejecutiva, empresa="Cart-56", monto=300_000, minutos=10)
    propia = commission_summary_service(db, executor=ejecutiva)
    assert [item.comision_clp for item in propia] == [30_000]


def test_solo_supervisor_puede_reestablecer(commission_context):
    db, _supervisor, ejecutiva, _otra = commission_context

    with pytest.raises(AuthorizationError):
        reset_commissions_service(db, executor=ejecutiva, user_id=None)


def test_pagos_sin_porcentaje_definido_no_generan_comision(commission_context):
    db, _supervisor, ejecutiva, _otra = commission_context
    _pago(db, user=ejecutiva, empresa="Consalud", monto=800_000)

    propia = commission_summary_service(db, executor=ejecutiva)
    assert [item.comision_clp for item in propia] == [0]
    assert propia[0].monto_pagado_clp == 800_000
