from __future__ import annotations

from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

_LOG_EMAIL = 0
_LOG_NOMBRE = 1
_LOG_ESTADO = 2
_LOG_DETALLE = 3

_ESTADO_PENDIENTE = "⏳ Pendiente"
_ESTADO_ENVIADO = "✅ Enviado"
_ESTADO_NO_ENVIADO = "❌ No enviado"
_ESTADO_OMITIDO = "⚠️ Sin email"

_COLOR_PENDIENTE = QColor("#f1f5f9")
_COLOR_ENVIADO = QColor("#d1fae5")
_COLOR_FALLIDO = QColor("#fee2e2")
_COLOR_OMITIDO = QColor("#fef9c3")


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(8)
        lbl = QLabel(title)
        lbl.setObjectName("CardTitle")
        lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        outer.addWidget(lbl)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("CardSubtitle")
            s.setWordWrap(True)
            outer.addWidget(s)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        outer.addWidget(sep)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)
