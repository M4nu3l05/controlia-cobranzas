from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QComboBox


class ComboBoxWheelGuard(QObject):
    """Evita cambios accidentales en combos cerrados por la rueda del mouse."""

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, QComboBox)
            and not watched.view().isVisible()
        ):
            event.ignore()
            return True
        return super().eventFilter(watched, event)
