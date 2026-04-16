"""
Worker thread para ejecutar la conciliación en segundo plano
"""

import traceback
from PyQt6.QtCore import QThread, pyqtSignal

from .models import ConciliacionParams
from .conciliacion import compare_excels


class ConciliacionWorker(QThread):
    """
    Hilo de fondo que ejecuta la comparación de archivos Excel.
    """
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(self, params: ConciliacionParams):
        super().__init__()
        self.params = params

    def run(self):
        try:
            def cb(pct, msg):
                self.progress.emit(pct, msg)

            out_path, metrics = compare_excels(
                self.params.mes_anterior_path,
                self.params.mes_actual_path,
                self.params.salida_path,
                sheet=self.params.sheet_name,
                progress_cb=cb,
                export_both=self.params.export_both
            )
            self.finished_ok.emit(out_path, metrics)
        except Exception:
            self.failed.emit(traceback.format_exc())