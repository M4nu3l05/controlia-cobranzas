# ================================================================
#  deudores/gestiones_worker.py
#  QThread para cargar el Excel de gestiones en segundo plano.
# ================================================================

from dataclasses import dataclass
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from .gestiones_db import cargar_desde_excel
from .gestiones_db import insertar_gestion_manual
from .outbox import encolar_gestion
from auth.auth_service import backend_create_gestion_con_estado
from auth.auth_service import backend_get_deudor_detalle, backend_list_gestiones


logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class GuardarGestionParams:
    session: object
    rut: str
    empresa: str
    nombre: str
    tipo_gestion: str
    estado: str
    fecha: str
    observacion: str
    client_operation_id: str


class GuardarGestionWorker(QThread):
    saved = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, params: GuardarGestionParams, parent=None):
        super().__init__(parent)
        self.params = params

    def run(self) -> None:
        p = self.params
        try:
            if p.session and getattr(p.session, "auth_source", "") == "backend":
                data, err, offline = backend_create_gestion_con_estado(
                    p.session,
                    rut=p.rut,
                    empresa=p.empresa,
                    nombre_afiliado=p.nombre,
                    tipo_gestion=p.tipo_gestion,
                    estado=p.estado,
                    fecha_gestion=p.fecha,
                    observacion=p.observacion,
                    origen="manual",
                    client_operation_id=p.client_operation_id,
                )
                if err and offline:
                    encolar_gestion(
                        user_id=int(getattr(p.session, "user_id", 0) or 0),
                        rut=p.rut,
                        empresa=p.empresa,
                        nombre_afiliado=p.nombre,
                        tipo_gestion=p.tipo_gestion,
                        estado=p.estado,
                        fecha_gestion=p.fecha,
                        observacion=p.observacion,
                        origen="manual",
                        client_operation_id=p.client_operation_id,
                    )
                    self.saved.emit({"queued": True, "data": None})
                    return
                if err:
                    self.failed.emit(err)
                    return
                self.saved.emit({"queued": False, "data": data})
                return

            gestion_id = insertar_gestion_manual(
                rut=p.rut,
                nombre=p.nombre,
                tipo_gestion=p.tipo_gestion,
                estado=p.estado,
                fecha=p.fecha,
                observacion=p.observacion,
            )
            self.saved.emit({"queued": False, "data": {"id": gestion_id}})
        except Exception as exc:
            logger.exception(
                "Fallo inesperado al guardar gestión manual (operation_id=%s)",
                p.client_operation_id,
            )
            self.failed.emit(str(exc) or type(exc).__name__)


class RefrescarGestionWorker(QThread):
    completed = pyqtSignal(object, object, str)

    def __init__(self, session, *, rut: str, empresa: str, parent=None):
        super().__init__(parent)
        self._session = session
        self._rut = rut
        self._empresa = empresa

    def run(self) -> None:
        try:
            payload, detail_error = backend_get_deudor_detalle(
                self._session,
                rut=self._rut,
                empresa=self._empresa,
            )
            rows, management_error = backend_list_gestiones(
                self._session,
                rut=self._rut,
                empresa=self._empresa,
            )
            error = detail_error or management_error
            self.completed.emit(payload or {}, rows or [], error)
        except Exception as exc:
            logger.exception("Fallo al refrescar una gestión guardada")
            self.completed.emit({}, [], str(exc) or type(exc).__name__)
