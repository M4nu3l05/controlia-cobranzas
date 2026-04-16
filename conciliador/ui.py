"""
Componentes de UI reutilizables
"""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class Card(QFrame):
    """
    Tarjeta visual con título, subtítulo y área de contenido expandible.
    """
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()

        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        # Título
        lbl_title = QLabel(title)
        lbl_title.setObjectName("CardTitle")
        lay.addWidget(lbl_title)

        # Subtítulo
        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setWordWrap(True)
            lbl_sub.setObjectName("CardSubtitle")
            lay.addWidget(lbl_sub)

        # Contenedor del contenido
        self.body = QVBoxLayout()
        self.body.setSpacing(10)

        # El body se agrega con stretch=1 para que crezca
        lay.addLayout(self.body, 1)

