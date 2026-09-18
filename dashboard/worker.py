"""Carga de datos del dashboard fuera del hilo de la interfaz.

Cada refresco del panel operativo hace varias consultas al backend y cada viaje
cuesta cientos de milisegundos. Ejecutarlas en el hilo de la interfaz congelaba
la aplicación completa, incluso mientras el usuario trabajaba en otro módulo.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

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


class GeneralDashboardLoadWorker(QThread):
    """Carga secciones independientes sin tocar widgets desde el worker."""

    completed = pyqtSignal(int, object)

    def __init__(self, generation: int, loaders: dict[str, object], parent=None):
        super().__init__(parent)
        self._generation = int(generation)
        self._loaders = dict(loaders)

    def run(self) -> None:
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(self._loaders))) as pool:
            pending = {pool.submit(loader): name for name, loader in self._loaders.items()}
            for future in as_completed(pending):
                name = pending[future]
                try:
                    results[name] = {"value": future.result(), "error": ""}
                except Exception as exc:
                    results[name] = {"value": None, "error": str(exc)}
        self.completed.emit(self._generation, results)
