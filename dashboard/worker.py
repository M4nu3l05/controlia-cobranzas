"""Carga de datos del dashboard fuera del hilo de la interfaz.

Cada refresco del panel operativo hace varias consultas al backend y cada viaje
cuesta cientos de milisegundos. Ejecutarlas en el hilo de la interfaz congelaba
la aplicación completa, incluso mientras el usuario trabajaba en otro módulo.
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class DashboardLoadWorker(QThread):
    """Ejecuta la carga de deudores, resumen y comisiones en segundo plano."""

    finished_ok = pyqtSignal(object, object, object)  # debtors, summary, extras
    failed = pyqtSignal(str)

    def __init__(self, cargar, cargar_extras, parent=None):
        super().__init__(parent)
        self._cargar = cargar
        self._cargar_extras = cargar_extras

    def run(self) -> None:
        try:
            debtors, summary = self._cargar()
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        # Comisiones y productividad del equipo son informativas: si fallan, el
        # panel igual debe mostrar la cartera.
        try:
            extras = self._cargar_extras()
        except Exception:
            extras = {}

        self.finished_ok.emit(debtors, summary, extras)
