from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401
from app.db.session import Base
from app.models.debtor_assignment import DebtorUserAssignment
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.operations import DebtorBirladoTransition, DebtorImportBatch
from app.models.payment import PaymentAllocation, PaymentTransaction
from app.models.user import User
from app.services.deudor_import_service import _add_birlado_only_summaries
from app.services.deudor_service import clear_empresa_deudores_service


def _user() -> User:
    return User(
        email="supervisor@example.test",
        username="Supervisora",
        role="supervisor",
        is_active=True,
        must_change_password=False,
        password_hash="test",
        salt="test",
    )


def _detalle(empresa: str, rut: str, expediente: str) -> DeudorDetalle:
    return DeudorDetalle(
        empresa=empresa,
        rut_afiliado=rut,
        dv="1",
        rut_completo=f"{rut}-1",
        nombre_afiliado="Persona ficticia",
        nro_expediente=expediente,
        copago=100,
        saldo_actual=100,
    )


def _resumen(empresa: str, rut: str) -> DeudorResumen:
    return DeudorResumen(
        empresa=empresa,
        rut_afiliado=rut,
        dv="1",
        rut_completo=f"{rut}-1",
        nombre_afiliado="Persona ficticia",
        copago=100,
        saldo_actual=100,
    )


def test_clear_company_preserves_payment_ledger_and_removes_visible_base():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = _user()
        paid_detail = _detalle("Colmena", "1", "EXP-PAGO")
        birlado_detail = _detalle("Colmena", "2", "EXP-BIRLADO")
        other_detail = _detalle("Consalud", "3", "EXP-OTRA")
        db.add_all(
            [
                user,
                paid_detail,
                birlado_detail,
                other_detail,
                _resumen("Colmena", "1"),
                _resumen("Colmena", "2"),
                _resumen("Consalud", "3"),
            ]
        )
        db.flush()

        transaction = PaymentTransaction(
            public_id="00000000-0000-4000-8000-000000000001",
            idempotency_key="payment-test-1",
            empresa="Colmena",
            rut_afiliado="1",
            payment_type="Pago",
            amount_clp=10,
            effective_date=date(2026, 10, 16),
            registered_by_user_id=user.id,
            registered_by_username=user.username,
        )
        batch = DebtorImportBatch(
            empresa="Colmena",
            source_file="base-ficticia.xlsx",
            file_sha256="a" * 64,
            imported_by_user_id=user.id,
            imported_by_username=user.username,
        )
        db.add_all([transaction, batch])
        db.flush()
        db.add_all(
            [
                PaymentAllocation(
                    transaction_id=transaction.id,
                    deudor_detalle_id=paid_detail.id,
                    expediente=paid_detail.nro_expediente,
                    amount_clp=10,
                    balance_before_clp=100,
                    balance_after_clp=90,
                ),
                DebtorBirladoTransition(
                    import_batch_id=batch.id,
                    detalle_id=birlado_detail.id,
                    empresa="Colmena",
                    rut_afiliado="2",
                    nro_expediente=birlado_detail.nro_expediente,
                    previous_status="Sin Gestión",
                ),
                DebtorUserAssignment(
                    empresa="Colmena",
                    rut_afiliado="1",
                    user_id=user.id,
                    assigned_by_user_id=user.id,
                ),
            ]
        )
        db.commit()
        paid_detail_id = int(paid_detail.id)
        birlado_detail_id = int(birlado_detail.id)

        assert clear_empresa_deudores_service(db, empresa="Colmena") is True

        assert db.query(DeudorResumen).filter(DeudorResumen.empresa == "Colmena").count() == 0
        assert db.query(DeudorDetalle).filter(
            DeudorDetalle.empresa == "Colmena",
            DeudorDetalle.is_active.is_(True),
        ).count() == 0
        archived = db.query(DeudorDetalle).filter(DeudorDetalle.id == paid_detail_id).one()
        assert archived.is_active is False
        assert archived.estado_deudor == "Base eliminada"
        assert db.query(DeudorDetalle).filter(DeudorDetalle.id == birlado_detail_id).count() == 0
        assert db.query(PaymentTransaction).count() == 1
        assert db.query(PaymentAllocation).count() == 1
        assert db.query(DebtorBirladoTransition).count() == 0
        assert db.query(DebtorUserAssignment).count() == 0
        assert db.query(DeudorResumen).filter(DeudorResumen.empresa == "Consalud").count() == 1
        assert db.query(DeudorDetalle).filter(DeudorDetalle.empresa == "Consalud").count() == 1

        assert _add_birlado_only_summaries(db, empresa="Colmena") == 0
        assert db.query(DeudorResumen).filter(DeudorResumen.empresa == "Colmena").count() == 0


def test_clear_company_worker_keeps_qt_responsive(monkeypatch):
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox
    import admin_carteras.view as view_module

    app = QApplication.instance() or QApplication([])
    calls: list[str] = []

    def slow_backend_clear(_session, *, empresa: str):
        calls.append(empresa)
        time.sleep(0.25)
        return f"Se eliminaron los registros de deudores para {empresa}.", ""

    monkeypatch.setattr(view_module, "backend_clear_empresa_deudores_con_estado", slow_backend_clear)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)

    widget = view_module.AdminCarterasWidget(session=None)
    widget._session = SimpleNamespace(auth_source="backend")
    widget.cmb_empresa.setCurrentText("Cruz Blanca")
    monkeypatch.setattr(widget, "_confirmar", lambda *_args: True)
    monkeypatch.setattr(widget, "_limpiar_base_local_empresa", lambda _empresa: True)
    ticks: list[str] = []
    QTimer.singleShot(30, lambda: ticks.append("responsive"))

    widget._accion_limpiar_empresa()
    first_worker = widget._clear_empresa_worker
    widget._accion_limpiar_empresa()

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and widget._clear_empresa_worker is not None:
        app.processEvents()
        time.sleep(0.01)

    assert ticks == ["responsive"]
    assert calls == ["Cruz Blanca"]
    assert first_worker is not None
    assert widget._clear_empresa_worker is None
    assert widget.btn_limpiar_empresa.isEnabled()
    widget.close()


def test_reimport_after_clear_keeps_details_referenced_by_payments():
    from app.services.deudor_import_service import _reparar_estado_inconsistente_empresa

    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = _user()
        paid_detail = _detalle("Colmena", "1", "EXP-PAGO")
        orphan_detail = _detalle("Colmena", "2", "EXP-SUELTO")
        db.add_all([user, paid_detail, orphan_detail])
        db.flush()
        transaction = PaymentTransaction(
            public_id="00000000-0000-4000-8000-000000000002",
            idempotency_key="payment-test-2",
            empresa="Colmena",
            rut_afiliado="1",
            payment_type="Pago",
            amount_clp=10,
            effective_date=date(2026, 10, 16),
            registered_by_user_id=user.id,
            registered_by_username=user.username,
        )
        db.add(transaction)
        db.flush()
        db.add(PaymentAllocation(
            transaction_id=transaction.id,
            deudor_detalle_id=paid_detail.id,
            expediente=paid_detail.nro_expediente,
            amount_clp=10,
            balance_before_clp=100,
            balance_after_clp=90,
        ))
        db.commit()
        paid_detail_id = int(paid_detail.id)
        orphan_detail_id = int(orphan_detail.id)

        # Sin resumen (base eliminada): la reparación no debe violar la FK de pagos.
        _reparar_estado_inconsistente_empresa(db, "Colmena")

        assert db.get(DeudorDetalle, paid_detail_id) is not None
        assert db.get(DeudorDetalle, orphan_detail_id) is None
