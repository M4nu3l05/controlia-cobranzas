from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .documents import get_privacy_text, get_terms_text


class LegalDocumentDialog(QDialog):
    def __init__(self, *, title: str, body_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 620)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(body_text)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setStyleSheet(
            "QPlainTextEdit { background:#f8fafc; border:1px solid #dbe3ee; border-radius:8px; padding:10px; }"
        )
        root.addWidget(editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)


class LegalAcceptanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aceptación de Términos y Privacidad")
        self.resize(980, 760)
        self.setModal(True)

        self._accepted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Aceptación de Términos y Política de Privacidad")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#0f172a;")
        root.addWidget(title)

        subtitle = QLabel(
            "Para continuar usando Controlia Cobranzas debes leer y aceptar ambos documentos legales vigentes."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#475569;")
        root.addWidget(subtitle)

        self._tabs = QTabWidget()
        self._terms_text = QPlainTextEdit()
        self._privacy_text = QPlainTextEdit()
        for w in (self._terms_text, self._privacy_text):
            w.setReadOnly(True)
            w.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            w.setStyleSheet(
                "QPlainTextEdit { background:#f8fafc; border:1px solid #dbe3ee; border-radius:8px; padding:10px; }"
            )

        self._tabs.addTab(self._terms_text, "Términos y Condiciones")
        self._tabs.addTab(self._privacy_text, "Política de Privacidad")
        root.addWidget(self._tabs, 1)

        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setStyleSheet("color:#b91c1c; font-weight:600;")
        self.lbl_error.setVisible(False)
        root.addWidget(self.lbl_error)

        self.chk_terms = QCheckBox("He leído y acepto los Términos y Condiciones.")
        self.chk_privacy = QCheckBox("He leído y acepto la Política de Privacidad.")
        for chk in (self.chk_terms, self.chk_privacy):
            chk.setStyleSheet("QCheckBox { color:#0f172a; font-size:10pt; }")
            chk.stateChanged.connect(self._sync_actions)
            root.addWidget(chk)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_exit = QPushButton("Salir")
        self.btn_exit.setStyleSheet(
            "QPushButton { background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; border-radius:8px; padding:8px 14px; }"
            "QPushButton:hover { background:#e2e8f0; }"
        )
        self.btn_exit.clicked.connect(self.reject)

        self.btn_accept = QPushButton("Aceptar y continuar")
        self.btn_accept.setEnabled(False)
        self.btn_accept.setStyleSheet(
            "QPushButton { background:#1d4ed8; color:#ffffff; border:none; border-radius:8px; padding:8px 16px; font-weight:700; }"
            "QPushButton:hover { background:#1e40af; }"
            "QPushButton:disabled { background:#93c5fd; }"
        )
        self.btn_accept.clicked.connect(self._on_accept)

        actions.addWidget(self.btn_exit)
        actions.addWidget(self.btn_accept)
        root.addLayout(actions)

        self._load_documents()

    @property
    def accepted(self) -> bool:
        return bool(self._accepted)

    def _load_documents(self) -> None:
        terms_text, terms_err = get_terms_text()
        privacy_text, privacy_err = get_privacy_text()

        self._terms_text.setPlainText(terms_text or "No disponible.")
        self._privacy_text.setPlainText(privacy_text or "No disponible.")

        errors = [e for e in (terms_err, privacy_err) if e]
        if errors:
            self.lbl_error.setText(
                "No se pudieron cargar los documentos legales requeridos. "
                "Por seguridad, no es posible continuar.\n\n" + "\n".join(f"- {e}" for e in errors)
            )
            self.lbl_error.setVisible(True)
            self.chk_terms.setEnabled(False)
            self.chk_privacy.setEnabled(False)
            self.btn_accept.setEnabled(False)
        else:
            self.lbl_error.setVisible(False)

        self._sync_actions()

    def _sync_actions(self) -> None:
        enabled = (
            self.chk_terms.isEnabled()
            and self.chk_privacy.isEnabled()
            and self.chk_terms.isChecked()
            and self.chk_privacy.isChecked()
        )
        self.btn_accept.setEnabled(enabled)

    def _on_accept(self) -> None:
        if not (self.chk_terms.isChecked() and self.chk_privacy.isChecked()):
            QMessageBox.warning(self, "Confirmación requerida", "Debes aceptar ambos documentos para continuar.")
            return

        self._accepted = True
        self.accept()
