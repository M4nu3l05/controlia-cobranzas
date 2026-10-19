from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QComboBox

from core.ui_events import ComboBoxWheelGuard
from deudores.database import EMPRESAS, EMPRESAS_OPERATIVAS
from admin_carteras.view import AdminCarterasWidget
from dashboard.view import DashboardWidget


def _wheel_event() -> QWheelEvent:
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


def test_operational_portfolios_preserve_historical_catalog():
    assert EMPRESAS == ["Colmena", "Consalud", "Cruz Blanca", "Cart-56"]
    assert EMPRESAS_OPERATIVAS == ["Colmena", "Cruz Blanca"]


def test_combo_wheel_is_blocked_when_closed_and_allowed_when_open():
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItems(["Uno", "Dos", "Tres"])
    combo.setCurrentIndex(1)
    guard = ComboBoxWheelGuard(app)

    assert guard.eventFilter(combo, _wheel_event()) is True
    assert combo.currentIndex() == 1

    combo.show()
    combo.showPopup()
    app.processEvents()
    assert combo.view().isVisible()
    assert guard.eventFilter(combo, _wheel_event()) is False
    combo.hidePopup()
    combo.close()


def test_dashboard_and_assignments_build_exactly_two_operational_entries():
    app = QApplication.instance() or QApplication([])
    dashboard = DashboardWidget(session=None, auto_refresh=False)
    admin = AdminCarterasWidget(session=None, auto_load=False)

    assert list(dashboard._company_cards) == ["Colmena", "Cruz Blanca"]
    assert admin.tbl_comisiones.rowCount() == 2
    assert [admin.tbl_comisiones.item(row, 0).text() for row in range(2)] == [
        "Colmena", "Cruz Blanca"
    ]
    assert list(admin._combos_asignacion) == ["Colmena", "Cruz Blanca"]
    # La limpieza controlada mantiene acceso a carteras retiradas (ej. Cart-56).
    assert [admin.cmb_empresa.itemText(i) for i in range(admin.cmb_empresa.count())] == EMPRESAS

    admin.close()
    dashboard.close()
