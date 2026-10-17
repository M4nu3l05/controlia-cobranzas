from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from deudores.gestiones_import_dialog import GestionCompanyResolutionDialog


def test_dialog_requires_and_returns_one_company_per_ambiguous_rut():
    app = QApplication.instance() or QApplication([])
    dialog = GestionCompanyResolutionDialog([
        {"rut": "11111111", "nombre": "Persona Uno", "companies": ["Colmena", "Consalud", "Cruz Blanca"]},
        {"rut": "22222222", "nombre": "Persona Dos", "companies": ["Cart-56", "Cruz Blanca"]},
    ])

    dialog._validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.lbl_error.isHidden()

    assert [dialog._combos[0][1].itemText(i) for i in range(dialog._combos[0][1].count())] == [
        "Selecciona una cartera…", "Colmena", "Cruz Blanca"
    ]
    dialog._combos[0][1].setCurrentIndex(1)
    dialog._combos[1][1].setCurrentIndex(1)
    dialog._validate_and_accept()
    app.processEvents()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.company_overrides() == {
        "11111111": "Colmena",
        "22222222": "Cruz Blanca",
    }
