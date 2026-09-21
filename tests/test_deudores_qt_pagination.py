import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from auth.auth_service import UserSession
from deudores.view import DeudoresWidget
import deudores.worker as deudores_worker
import deudores.view as deudores_view


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
    monkeypatch.setattr(
        deudores_view,
        "list_users",
        lambda _session: [
            {"id": 10, "username": "Ejecutiva Uno", "email": "uno@example.test", "role": "ejecutivo", "is_active": True},
            {"id": 20, "username": "Ejecutiva Dos", "email": "dos@example.test", "role": "ejecutivo", "is_active": True},
        ],
    )
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

    assert _wait_until(app, lambda: widget.sidebar.cmb_filtro_ejecutiva.count() == 3)
    widget.sidebar.cmb_filtro_ejecutiva.setCurrentIndex(
        widget.sidebar.cmb_filtro_ejecutiva.findData(20)
    )
    assert _wait_until(
        app,
        lambda: widget._backend_worker is None
        and calls[-1].get("assigned_user_id") == 20,
    )
    assert calls[-1]["offset"] == 0
    widget.close()


def test_supervisor_sidebar_places_search_and_filters_first(monkeypatch):
    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(
        deudores_worker,
        "backend_list_deudores_page",
        lambda _session, **_params: ({"items": [], "total": 0}, ""),
    )
    monkeypatch.setattr(deudores_view, "list_users", lambda _session: [])
    session = UserSession(
        user_id=2, email="supervisor@example.test", username="Supervisor", role="supervisor",
        is_active=True, must_change_password=False, access_token="token", auth_source="backend",
    )
    widget = DeudoresWidget(session=session)
    layout = widget.sidebar.layout()
    visible_widgets = [
        layout.itemAt(index).widget()
        for index in range(layout.count())
        if layout.itemAt(index).widget() is not None and layout.itemAt(index).widget().isVisibleTo(widget.sidebar)
    ]

    assert visible_widgets[:6] == [
        widget.sidebar.card_busq,
        widget.sidebar.card_carga,
        widget.sidebar.card_gest,
        widget.sidebar.card_descarga_gest,
        widget.sidebar.lbl_periodo,
        widget.sidebar.cmb_periodo,
    ]
    widget.close()
