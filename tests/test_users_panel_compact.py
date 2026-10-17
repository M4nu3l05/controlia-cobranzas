from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox

from auth.views.users_panel import UsersPanel


def test_users_table_has_five_responsive_columns(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(UsersPanel, "reload", lambda self: None)
    session = SimpleNamespace(user_id=1, role="admin", username="Administrador")
    panel = UsersPanel(session)
    panel.resize(1366, 768)
    panel.show()
    panel._render_users([
        {
            "id": 1,
            "username": "Administrador",
            "email": "admin@example.com",
            "role": "admin",
            "is_active": True,
        },
        {
            "id": 2,
            "username": "Supervisora de prueba",
            "email": "supervisora.con.correo.largo@example.com",
            "role": "supervisor",
            "is_active": True,
        },
    ])
    app.processEvents()

    assert panel.table.columnCount() == 5
    assert [panel.table.horizontalHeaderItem(i).text() for i in range(5)] == [
        "Nombre", "Correo", "Rol", "Estado", "Acciones"
    ]
    assert isinstance(panel.table.cellWidget(1, 2).findChild(QComboBox), QComboBox)
    assert panel.table.cellWidget(1, 3) is not None
    assert panel.table.cellWidget(1, 4) is not None
    assert panel.table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

    panel.resize(620, 500)
    app.processEvents()
    assert panel.table.columnWidth(1) >= panel.table.horizontalHeader().minimumSectionSize()
    panel.close()
