from __future__ import annotations

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QSortFilterProxyModel
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from core.text_utils import fix_mojibake_text
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


class DeudoresTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, columnas: list[str], etiquetas: list[str], parent=None):
        super().__init__(parent)
        pares = [
            (c, e) for c, e in zip(columnas, etiquetas)
            if not c.startswith("_") or c == COLUMNA_EMPRESA
        ]
        self._cols_vis = [p[0] for p in pares]
        self._labels = [p[1] for p in pares]
        self._df = df.reindex(columns=self._cols_vis).reset_index(drop=True).copy()

        try:
            self._emp_idx = self._cols_vis.index(COLUMNA_EMPRESA)
        except ValueError:
            self._emp_idx = -1

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._cols_vis)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._df):
            return None
        value = self._df.iat[index.row(), index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return fix_mojibake_text(value)
        if index.column() == self._emp_idx:
            empresa = str(value or "")
            if role == Qt.ItemDataRole.BackgroundRole:
                return EMPRESA_COLORES.get(empresa)
            if role == Qt.ItemDataRole.FontRole and empresa in EMPRESA_COLORES:
                return QFont("Segoe UI", 9, QFont.Weight.Bold)
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._labels[section] if 0 <= section < len(self._labels) else ""
        return super().headerData(section, orientation, role)

    def flags(self, index: QModelIndex):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def append_dataframe(self, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        incoming = df.reindex(columns=self._cols_vis).reset_index(drop=True)
        start = len(self._df)
        end = start + len(incoming) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._df = pd.concat([self._df, incoming], ignore_index=True)
        self.endInsertRows()


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
            index = model.index(source_row, self.empresa_col_idx)
            if not index.isValid() or str(model.data(index, Qt.ItemDataRole.DisplayRole)) != self.empresa_filtro:
                return False
        return True
