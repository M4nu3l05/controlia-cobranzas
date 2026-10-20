"""Hilos Qt para buscar y descargar actualizaciones sin bloquear la ventana."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core import updater

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    # Emite ReleaseInfo si hay una versión más nueva, o None si ya está al día.
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        try:
            self.finished_ok.emit(updater.find_update())
        except Exception as exc:
            logger.warning("No se pudo buscar actualizaciones: %s", exc)
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, release: updater.ReleaseInfo, parent=None):
        super().__init__(parent)
        self._release = release
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            path = updater.download_update(
                self._release,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                is_cancelled=lambda: self._cancel,
            )
            self.finished_ok.emit(str(path))
        except updater.UpdateCancelled:
            self.cancelled.emit()
        except updater.UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.exception("Fallo inesperado al descargar la actualización")
            self.failed.emit(f"No se pudo descargar la actualización: {exc}")
