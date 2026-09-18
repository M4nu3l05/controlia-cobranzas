import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from auth.auth_service import UserSession
from dashboard.container import DashboardWidget
import dashboard.view as general_view


class _SlowResponse:
    ok = True

    def __init__(self, url: str):
        self.url = url

    def raise_for_status(self):
        return None

    def json(self):
        if self.url.endswith("/dashboard/sessions"):
            return {"today": [], "month": []}
        return {
            "periodos_disponibles": [], "total_deudores": 0, "copago_total": 0,
            "total_pagos_total": 0, "saldo_total": 0, "sin_gestion_total": 0,
            "gestionados_total": 0, "cobertura_pct": 0, "pagos_vs_copago_pct": 0,
            "contactados_total": 0, "gestiones_hoy": 0, "gestiones_7d": 0,
            "estado_counts": {}, "tipos_hoy": {}, "health_label": "Sin datos",
            "focus_text": "Sin datos", "companies": [],
        }


def test_admin_dashboard_remains_responsive_with_ten_second_endpoints(monkeypatch):
    app = QApplication.instance() or QApplication([])

    def slow_get(url, **_kwargs):
        time.sleep(10)
        return _SlowResponse(url)

    def slow_commissions(_session):
        time.sleep(10)
        return [], ""

    monkeypatch.setattr(general_view.requests, "get", slow_get)
    monkeypatch.setattr(general_view, "obtener_resumen_comisiones", slow_commissions)
    session = UserSession(
        user_id=1, email="admin@example.test", username="Admin", role="admin",
        is_active=True, must_change_password=False, access_token="token", auth_source="backend",
    )

    started = time.monotonic()
    widget = DashboardWidget(session=session)
    widget.show()
    creation_time = time.monotonic() - started
    event_received = []
    QTimer.singleShot(100, lambda: event_received.append(True))
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert creation_time < 1.0
    assert event_received == [True]
    assert widget.general_dashboard._backend_worker is not None
    assert widget.work_dashboard._worker is None

    deadline = time.monotonic() + 12
    while widget.general_dashboard._backend_worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert widget.general_dashboard._backend_worker is None
    widget.close()
