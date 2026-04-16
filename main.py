import sys

from PyQt6.QtWidgets import QApplication

from app import MainWindow
from auth import AuthWindow, UserSession
from conciliador.utils import load_qss
from core.logging_config import configure_logging
from core.paths import ensure_runtime_dirs
from core.runtime import resource_path
from legal import enforce_legal_acceptance, ensure_legal_documents_available


def main() -> int:
    ensure_runtime_dirs()
    configure_logging()
    ensure_legal_documents_available()

    app = QApplication(sys.argv)
    load_qss(app, resource_path("styles.qss"))

    auth = AuthWindow()
    result = auth.exec()

    if result != AuthWindow.DialogCode.Accepted or auth.session is None:
        return 0

    session: UserSession = auth.session
    if not enforce_legal_acceptance(session):
        return 0

    w = MainWindow(session=session)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
