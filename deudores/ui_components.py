from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import Qt, QSortFilterProxyModel
from PyQt6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from .schema import COLUMNA_EMPRESA

EMPRESA_COLORES = {
    "Colmena": QColor("#dbeafe"),
    "Consalud": QColor("#d1fae5"),
    "Cruz Blanca": QColor("#fce7f3"),
}


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(8)
        lbl_title = QLabel(title)
        lbl_title.setObjectName("CardTitle")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        outer.addWidget(lbl_title)
        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setObjectName("CardSubtitle")
            lbl_sub.setWordWrap(True)
            outer.addWidget(lbl_sub)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        outer.addWidget(sep)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)


class DeudoresTableModel(QStandardItemModel):
    def __init__(self, df: pd.DataFrame, columnas: list[str], etiquetas: list[str], parent=None):
        super().__init__(parent)
        pares = [
            (c, e) for c, e in zip(columnas, etiquetas)
            if not c.startswith("_") or c == COLUMNA_EMPRESA
        ]
        self._cols_vis = [p[0] for p in pares]
        self.setColumnCount(len(self._cols_vis))
        self.setHorizontalHeaderLabels([p[1] for p in pares])

        try:
            self._emp_idx = self._cols_vis.index(COLUMNA_EMPRESA)
        except ValueError:
            self._emp_idx = -1

        for row_data in df[self._cols_vis].itertuples(index=False):
            items = [QStandardItem(str(v)) for v in row_data]
            empresa_val = str(row_data[self._emp_idx]) if self._emp_idx >= 0 else ""
            color = EMPRESA_COLORES.get(empresa_val)
            for item in items:
                item.setEditable(False)
            if color and self._emp_idx >= 0:
                items[self._emp_idx].setBackground(color)
                items[self._emp_idx].setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            self.appendRow(items)


class EmpresaFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.empresa_filtro: str = ""
        self.empresa_col_idx: int = 0

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not super().filterAcceptsRow(source_row, source_parent):
            return False
        if self.empresa_filtro:
            model = self.sourceModel()
            item = model.item(source_row, self.empresa_col_idx)
            if item is None or item.text() != self.empresa_filtro:
                return False
        return True
