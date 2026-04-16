from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative_path: str) -> str:
    """Devuelve la ruta absoluta de un recurso, compatible con PyInstaller."""
    base_path = getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
    return str(Path(base_path) / relative_path)
