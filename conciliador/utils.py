"""
Utilidades varias
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication


def load_qss(app: "QApplication", qss_path: str) -> None:
    """
    Carga un archivo .qss y lo aplica como stylesheet global.
    Si no existe, no falla (queda estilo por defecto).
    """
    if not os.path.exists(qss_path):
        return
    with open(qss_path, "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())

