import os
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

import deudores.gestiones_worker as worker_module
from deudores.detalle_dialog import AgregarGestionDialog


def _wait_until(app, condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_slow_management_save_keeps_qt_responsive_and_blocks_duplicate_close(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []

    def slow_save(*_args, **kwargs):
        calls.append(kwargs["client_operation_id"])
        time.sleep(0.25)
        return {"id": 10}, "", False

    monkeypatch.setattr(worker_module, "backend_create_gestion_con_estado", slow_save)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)
    session = SimpleNamespace(auth_source="backend", user_id=7)
    dialog = AgregarGestionDialog(
        rut="12345678",
        nombre="Persona Prueba",
        empresa="Consalud",
        session=session,
    )
    dialog.show()

    ticks = []
    QTimer.singleShot(30, lambda: ticks.append("responsive"))
    dialog._guardar()
    first_worker = dialog._save_worker
    dialog._guardar()
    dialog.reject()

    assert dialog._save_worker is first_worker
    assert dialog.isVisible()
    assert _wait_until(app, lambda: bool(ticks))
    assert _wait_until(app, lambda: dialog._save_worker is None)
    assert calls == [dialog._operation_id]
    assert not dialog.isVisible()
