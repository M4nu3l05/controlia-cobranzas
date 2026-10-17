from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from deudores.database import EMPRESAS_OPERATIVAS


class GestionCompanyResolutionDialog(QDialog):
    """Solicita una cartera para cada RUT ambiguo de una importación."""

    def __init__(self, ambiguous_debtors: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar cartera para gestiones")
        self.resize(760, min(650, 210 + max(1, len(ambiguous_debtors)) * 42))
        self.setModal(True)
        self._combos: list[tuple[str, QComboBox]] = []

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Los siguientes RUT están presentes en más de una cartera. "
            "Selecciona dónde se registrarán las gestiones de cada uno."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        table = QTableWidget(len(ambiguous_debtors), 3)
        table.setHorizontalHeaderLabels(["RUT", "Deudor", "Cartera seleccionada"])
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)

        for row_index, debtor in enumerate(ambiguous_debtors):
            rut = str(debtor.get("rut", "")).strip()
            name = str(debtor.get("nombre", "")).strip() or "—"
            table.setItem(row_index, 0, QTableWidgetItem(rut))
            table.setItem(row_index, 1, QTableWidgetItem(name))
            combo = QComboBox()
            combo.addItem("Selecciona una cartera…", "")
            for company in debtor.get("companies", []) or []:
                company_text = str(company).strip()
                if company_text in EMPRESAS_OPERATIVAS:
                    combo.addItem(company_text, company_text)
            table.setCellWidget(row_index, 2, combo)
            self._combos.append((rut, combo))

        table.resizeColumnsToContents()
        layout.addWidget(table, 1)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #b91c1c; font-weight: 600;")
        self.lbl_error.setVisible(False)
        layout.addWidget(self.lbl_error)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        apply_button = QPushButton("Continuar con la carga")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(self._validate_and_accept)
        actions.addWidget(apply_button)
        layout.addLayout(actions)

    def _validate_and_accept(self) -> None:
        missing = [rut for rut, combo in self._combos if not str(combo.currentData() or "").strip()]
        if missing:
            self.lbl_error.setText("Debes seleccionar una cartera para todos los RUT de la lista.")
            self.lbl_error.setVisible(True)
            return
        self.accept()

    def company_overrides(self) -> dict[str, str]:
        return {
            rut: str(combo.currentData() or "").strip()
            for rut, combo in self._combos
            if str(combo.currentData() or "").strip()
        }
