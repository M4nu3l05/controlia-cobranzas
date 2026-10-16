import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion
from app.models.operations import DerivationTracking, UserNotification
from app.models.user import User
from app.services.gestion_service import clear_all_gestiones_service


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


def test_clear_all_gestiones_removes_dependencies_and_resets_states_in_bulk():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _user()
        db.add(user)
        db.flush()
        debtors = [
            DeudorResumen(
                empresa="Consalud", rut_afiliado="1", dv="1", rut_completo="1-1",
                nombre_afiliado="Con saldo", saldo_actual=5000, estado_deudor="Contactado",
            ),
            DeudorResumen(
                empresa="Consalud", rut_afiliado="2", dv="2", rut_completo="2-2",
                nombre_afiliado="Sin deuda", saldo_actual=0, estado_deudor="Contactado",
            ),
        ]
        details = [
            DeudorDetalle(
                empresa="Consalud", rut_afiliado="1", dv="1", rut_completo="1-1",
                nombre_afiliado="Con saldo", saldo_actual=5000, estado_deudor="Contactado",
            ),
            DeudorDetalle(
                empresa="Consalud", rut_afiliado="2", dv="2", rut_completo="2-2",
                nombre_afiliado="Sin deuda", saldo_actual=0, estado_deudor="Contactado",
            ),
        ]
        gestion = DeudorGestion(
            empresa="Consalud", rut_afiliado="1", nombre_afiliado="Con saldo",
            tipo_gestion="Llamada", estado="Gestión asignada", fecha_gestion="16/10/2026",
            assigned_to_user_id=user.id,
        )
        db.add_all([*debtors, *details, gestion])
        db.flush()
        db.add(
            DerivationTracking(
                gestion_id=gestion.id,
                created_by_user_id=user.id,
                assigned_to_user_id=user.id,
                due_at=datetime.now() + timedelta(days=1),
            )
        )
        db.add(
            UserNotification(
                user_id=user.id,
                notification_type="derivation_assigned",
                title="Prueba",
                related_entity_type="gestion",
                related_entity_id=gestion.id,
            )
        )
        db.commit()

        assert clear_all_gestiones_service(db)
        assert db.query(DeudorGestion).count() == 0
        assert db.query(DerivationTracking).count() == 0
        assert db.query(UserNotification).count() == 0
        assert [row.estado_deudor for row in db.query(DeudorResumen).order_by(DeudorResumen.id)] == [
            "Sin Gestión", "Cliente Sin deuda"
        ]
        assert [row.estado_deudor for row in db.query(DeudorDetalle).order_by(DeudorDetalle.id)] == [
            "Sin Gestión", "Cliente Sin deuda"
        ]


def test_admin_clear_worker_keeps_qt_event_loop_responsive(monkeypatch):
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from admin_carteras.view import AdminCarterasWidget

    app = QApplication.instance() or QApplication([])
    widget = AdminCarterasWidget(session=None)
    monkeypatch.setattr(widget, "_confirmar", lambda *_args: True)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)

    calls = []

    def slow_local_clear():
        calls.append("started")
        time.sleep(0.25)
        return True

    monkeypatch.setattr(widget, "_limpiar_gestiones_locales", slow_local_clear)
    ticks = []
    QTimer.singleShot(30, lambda: ticks.append("responsive"))
    widget._accion_limpiar_gestiones()
    first_worker = widget._clear_gestiones_worker
    widget._accion_limpiar_gestiones()

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and widget._clear_gestiones_worker is not None:
        app.processEvents()
        time.sleep(0.01)

    assert ticks == ["responsive"]
    assert calls == ["started"]
    assert first_worker is not None
    assert widget._clear_gestiones_worker is None
    assert widget.btn_limpiar_gestiones.isEnabled()
    widget.close()
