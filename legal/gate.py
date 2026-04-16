from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from .acceptance_service import register_acceptance, requires_acceptance
from .dialogs import LegalAcceptanceDialog
from .documents import ensure_legal_documents_available


def enforce_legal_acceptance(session, parent: QWidget | None = None) -> bool:
    ensure_legal_documents_available()

    needs_acceptance, status_err = requires_acceptance(session)
    if not needs_acceptance and not status_err:
        return True

    if status_err:
        QMessageBox.warning(
            parent,
            "Validación legal",
            "No se pudo verificar la aceptación legal en el servidor/base local.\n\n"
            f"Detalle: {status_err}\n\n"
            "Debes completar la aceptación para continuar.",
        )

    dlg = LegalAcceptanceDialog(parent=parent)
    result = dlg.exec()
    if result != dlg.DialogCode.Accepted or not dlg.accepted:
        return False

    _, save_err = register_acceptance(session)
    if save_err:
        QMessageBox.critical(
            parent,
            "Error de aceptación legal",
            "Se aceptaron los documentos, pero no fue posible registrar la aceptación.\n\n"
            f"Detalle: {save_err}\n\n"
            "Por seguridad no es posible continuar.",
        )
        return False

    return True
