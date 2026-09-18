import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from auth.auth_service import UserSession
from deudores.view import DeudoresWidget
import deudores.worker as deudores_worker


def _item(index: int, *, name: str | None = None) -> dict:
    rut = str(10_000_000 + index)
    return {
        "empresa": "Consalud",
        "rut_afiliado": rut,
        "dv": "1",
        "rut_completo": f"{rut}-1",
        "nombre_afiliado": name or f"Persona {index:05d}",
        "estado_deudor": "Sin Gestión",
        "copago": 1000,
        "total_pagos": 0,
        "saldo_actual": 1000,
        "periodo_carga": "202609",
    }


def _wait_until(app, condition, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_deudores_navigates_all_pages_and_searches_global_dataset(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []

    def fake_page(_session, **params):
        calls.append(dict(params))
        query = str(params.get("q", "")).strip()
        if query:
            return {"items": [_item(5700, name="Objetivo fuera de página")], "total": 1}, ""
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 500))
        total = 5721
        end = min(offset + limit, total)
        return {"items": [_item(index) for index in range(offset, end)], "total": total}, ""

    monkeypatch.setattr(deudores_worker, "backend_list_deudores_page", fake_page)
    session = UserSession(
        user_id=1, email="admin@example.test", username="Admin", role="admin",
        is_active=True, must_change_password=False, access_token="token", auth_source="backend",
    )
    widget = DeudoresWidget(session=session)
    widget.show()

    assert _wait_until(app, lambda: widget._backend_worker is None and widget._backend_total == 5721)
    assert widget.table.model().rowCount() == 500
    assert widget._total_paginas_backend() == 12
    assert widget.table_panel.lbl_paginas.text() == "de 12"
    initial_calls = len(calls)
    time.sleep(0.4)
    app.processEvents()
    assert len(calls) == initial_calls

    widget._ir_a_pagina_backend(11)
    assert _wait_until(app, lambda: widget._backend_worker is None and widget._backend_page_index == 11)
    assert calls[-1]["offset"] == 5500
    assert widget.table.model().rowCount() == 221
    assert "5,501–5,721" in widget.sidebar.lbl_resultados.text()
    page_calls = len(calls)
    time.sleep(0.4)
    app.processEvents()
    assert len(calls) == page_calls
    assert widget._backend_page_index == 11

    widget.sidebar.txt_search.setText("Objetivo fuera de página")
    assert _wait_until(
        app,
        lambda: widget._backend_worker is None
        and widget._backend_total == 1
        and widget._backend_page_index == 0,
    )
    assert calls[-1]["q"] == "Objetivo fuera de página"
    assert calls[-1]["offset"] == 0
    assert widget.table.model().rowCount() == 1
    widget.close()
