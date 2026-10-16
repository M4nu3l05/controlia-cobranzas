import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from deudores.detalle_dialog import DetalleDeudorDialog, _GestionWidget


def _backend_row(**overrides):
    row = {
        "id": 41,
        "tipo_gestion": "Manual",
        "estado": "Gestion realizada",
        "fecha_gestion": "16/10/2026",
        "observacion": "Prueba de refresco",
        "origen": "manual",
    }
    row.update(overrides)
    return row


def test_backend_management_rows_render_without_name_error(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "deudores.detalle_dialog.backend_list_gestiones",
        lambda *_args, **_kwargs: ([_backend_row()], ""),
    )

    widget = _GestionWidget(
        rut="12345678",
        nombre="Persona Prueba",
        empresa="Consalud",
        session=SimpleNamespace(auth_source="backend"),
    )
    widget._cargar()
    app.processEvents()

    assert widget.tbl.rowCount() == 1
    assert widget.tbl.item(0, 1).text() == "Gestión realizada"
    assert widget.lbl_total.text() == "1 gestión"
    widget.close()


def test_management_refresh_is_applied_even_when_detail_refresh_fails():
    app = QApplication.instance() or QApplication([])
    management_widget = _GestionWidget(
        rut="12345678",
        nombre="Persona Prueba",
        empresa="Consalud",
        session=None,
    )
    app.processEvents()
    emitted = []
    target = SimpleNamespace(
        _gestion_widget=management_widget,
        gestiones_actualizadas=SimpleNamespace(emit=lambda: emitted.append(True)),
        _aplicar_detalle_backend=lambda _payload: pytest.fail(
            "No debe aplicar un detalle cuya consulta falló"
        ),
    )

    DetalleDeudorDialog._on_gestion_refresh_completed(
        target,
        {},
        [_backend_row(tipo_gestion="Pago", estado="Pagado")],
        "Error temporal al recargar el detalle",
        "",
    )
    app.processEvents()

    assert management_widget.tbl.rowCount() == 1
    assert management_widget.tbl.item(0, 0).text() == "Pago"
    assert management_widget.tbl.item(0, 1).text() == "Pagado"
    assert emitted == [True]
    management_widget.close()
