from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from .plantillas import VARIABLES_DISPONIBLES, cargar_plantillas, guardar_plantillas
from .ui_components import Card


class TabPlantillas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._plantillas = cargar_plantillas()
        self._idx_actual = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        left = QWidget()
        left.setMinimumWidth(110)
        left.setMaximumWidth(320)
        left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        card_list = Card("Plantillas guardadas", "")
        self.lst = QTableWidget(0, 1)
        self.lst.horizontalHeader().setVisible(False)
        self.lst.verticalHeader().setVisible(False)
        self.lst.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lst.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lst.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lst.itemSelectionChanged.connect(self._on_select)
        card_list.body.addWidget(self.lst)
        btn_add = QPushButton("➕  Nueva plantilla")
        btn_add.clicked.connect(self._nueva)
        btn_del = QPushButton("🗑  Eliminar")
        btn_del.clicked.connect(self._eliminar)
        card_list.body.addWidget(btn_add)
        card_list.body.addWidget(btn_del)
        ll.addWidget(card_list)
        layout.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        card_edit = Card("Editor de plantilla", "Usa variables como {nombre}, {saldo}, {empresa}.")
        form = QFormLayout()
        self.txt_nombre_p = QLineEdit()
        self.txt_asunto = QLineEdit()
        form.addRow("Nombre plantilla:", self.txt_nombre_p)
        form.addRow("Asunto:", self.txt_asunto)
        card_edit.body.addLayout(form)
        self.txt_cuerpo = QTextEdit()
        self.txt_cuerpo.setMinimumHeight(180)
        card_edit.body.addWidget(self.txt_cuerpo, 1)
        lbl_vars = QLabel("Variables disponibles: " + "  ".join(list(VARIABLES_DISPONIBLES.keys())))
        lbl_vars.setObjectName("MutedLabel")
        lbl_vars.setWordWrap(True)
        card_edit.body.addWidget(lbl_vars)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_save = QPushButton("💾  Guardar plantilla")
        btn_save.setObjectName("PrimaryButton")
        btn_save.clicked.connect(self._guardar_plantilla)
        btn_row.addWidget(btn_save)
        card_edit.body.addLayout(btn_row)
        rl.addWidget(card_edit, 1)
        layout.addWidget(right, 1)
        self._refrescar_lista()

    def _refrescar_lista(self):
        self.lst.setRowCount(0)
        for p in self._plantillas:
            r = self.lst.rowCount()
            self.lst.insertRow(r)
            self.lst.setItem(r, 0, QTableWidgetItem(p.get("nombre", f"Plantilla {r+1}")))
        if self._plantillas:
            self.lst.selectRow(self._idx_actual)
            self._cargar_en_editor(self._idx_actual)

    def _on_select(self):
        rows = self.lst.selectedItems()
        if rows:
            self._idx_actual = self.lst.row(rows[0])
            self._cargar_en_editor(self._idx_actual)

    def _cargar_en_editor(self, idx: int):
        if 0 <= idx < len(self._plantillas):
            p = self._plantillas[idx]
            self.txt_nombre_p.setText(p.get("nombre", ""))
            self.txt_asunto.setText(p.get("asunto", ""))
            self.txt_cuerpo.setPlainText(p.get("cuerpo", ""))

    def _guardar_plantilla(self):
        if 0 <= self._idx_actual < len(self._plantillas):
            self._plantillas[self._idx_actual] = {
                "nombre": self.txt_nombre_p.text().strip() or f"Plantilla {self._idx_actual+1}",
                "asunto": self.txt_asunto.text().strip(),
                "cuerpo": self.txt_cuerpo.toPlainText(),
            }
            guardar_plantillas(self._plantillas)
            self._refrescar_lista()
            self.lst.selectRow(self._idx_actual)

    def _nueva(self):
        self._plantillas.append({"nombre": "Nueva plantilla", "asunto": "", "cuerpo": ""})
        self._idx_actual = len(self._plantillas) - 1
        guardar_plantillas(self._plantillas)
        self._refrescar_lista()

    def _eliminar(self):
        if len(self._plantillas) <= 1:
            QMessageBox.warning(self, "Mínimo", "Debe haber al menos una plantilla.")
            return
        if 0 <= self._idx_actual < len(self._plantillas):
            self._plantillas.pop(self._idx_actual)
            self._idx_actual = max(0, self._idx_actual - 1)
            guardar_plantillas(self._plantillas)
            self._refrescar_lista()

    def get_plantilla_actual(self) -> dict:
        if 0 <= self._idx_actual < len(self._plantillas):
            return self._plantillas[self._idx_actual]
        return {}
