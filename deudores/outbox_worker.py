# ================================================================
#  deudores/outbox_worker.py
#  Sube en segundo plano las gestiones que quedaron en cola local.
# ================================================================

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from auth.auth_service import backend_create_gestion_con_estado

from .outbox import listar_pendientes, marcar_sincronizada, registrar_error

logger = logging.getLogger(__name__)


class OutboxSyncWorker(QThread):
    """Intenta enviar las gestiones pendientes sin bloquear la interfaz."""

    # (sincronizadas, rechazadas, sigue_sin_conexion)
    terminado = pyqtSignal(int, int, bool)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session

    def run(self):
        user_id = int(getattr(self._session, "user_id", 0) or 0)
        if not user_id:
            self.terminado.emit(0, 0, False)
            return

        sincronizadas = 0
        rechazadas = 0
        sin_conexion = False

        for pendiente in listar_pendientes(user_id):
            try:
                _, err, offline = backend_create_gestion_con_estado(
                    self._session,
                    rut=pendiente.rut,
                    empresa=pendiente.empresa,
                    nombre_afiliado=pendiente.nombre_afiliado,
                    tipo_gestion=pendiente.tipo_gestion,
                    estado=pendiente.estado,
                    fecha_gestion=pendiente.fecha_gestion,
                    observacion=pendiente.observacion,
                    origen=pendiente.origen,
                    assigned_to_user_id=pendiente.assigned_to_user_id,
                )
            except Exception:
                logger.exception("Fallo inesperado al sincronizar gestion %s", pendiente.id)
                registrar_error(pendiente.id, "Error inesperado al sincronizar.")
                rechazadas += 1
                continue

            if not err:
                marcar_sincronizada(pendiente.id)
                sincronizadas += 1
                continue

            if offline:
                # Sigue sin red: no tiene sentido recorrer el resto de la cola.
                sin_conexion = True
                break

            # El backend respondio y rechazo la gestion: reintentar no ayuda,
            # se deja registrado el motivo para revisarlo.
            registrar_error(pendiente.id, err)
            rechazadas += 1

        self.terminado.emit(sincronizadas, rechazadas, sin_conexion)
