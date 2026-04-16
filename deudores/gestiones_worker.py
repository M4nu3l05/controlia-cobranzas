# ================================================================
#  deudores/gestiones_worker.py
#  QThread para cargar el Excel de gestiones en segundo plano.
# ================================================================

from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal

from .gestiones_db import cargar_desde_excel


def _friendly_gestiones_error(exc: Exception, excel_path: str) -> str:
    msg = str(exc or "").strip()
    lower = msg.lower()

    if isinstance(exc, FileNotFoundError):
        return f"No se encontró el archivo Excel de gestiones.\n\nArchivo:\n{excel_path}"
    if isinstance(exc, PermissionError):
        return "No se pudo abrir el archivo de gestiones porque está bloqueado o está abierto en otro programa."
    if "worksheet" in lower or "sheet" in lower or "hoja" in lower:
        return (
            "El archivo de gestiones no contiene las hojas esperadas.\n\n"
            "Debe incluir una o más hojas llamadas `SMS`, `Email` o `Carta`.\n\n"
            f"Detalle:\n{msg}"
        )
    if "excel file format cannot be determined" in lower or "file is not a zip file" in lower:
        return "El archivo seleccionado no parece ser un Excel válido de gestiones."

    return (
        "No se pudo cargar la base de gestiones.\n\n"
        f"Archivo:\n{excel_path}\n\n"
        f"Detalle:\n{msg or type(exc).__name__}"
    )


@dataclass
class CargaGestionesParams:
    excel_path: str


class CargaGestionesWorker(QThread):
    progress   = pyqtSignal(int, str)
    finished_ok = pyqtSignal(int, int, list)   # insertados, omitidos, errores
    failed     = pyqtSignal(str)

    def __init__(self, params: CargaGestionesParams, parent=None):
        super().__init__(parent)
        self.params = params

    def run(self):
        try:
            self.progress.emit(20, "Leyendo hojas SMS, Email, Carta…")
            insertados, omitidos, errores = cargar_desde_excel(self.params.excel_path)
            self.progress.emit(90, f"Insertadas {insertados:,}  |  Omitidas {omitidos:,} (duplicadas).")
            if errores:
                self.progress.emit(100, f"Completado con advertencias: {'; '.join(errores)}")
            else:
                self.progress.emit(100, f"¡Listo! {insertados:,} nuevas, {omitidos:,} ya existían.")
            self.finished_ok.emit(insertados, omitidos, errores)
        except Exception as e:
            self.failed.emit(_friendly_gestiones_error(e, self.params.excel_path))
