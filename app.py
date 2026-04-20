import os
import sys

from core.logging_config import configure_logging
from core.paths import ensure_runtime_dirs

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QTabWidget,
    QTabBar,
    QDialog,
    QTableWidget,
    QHeaderView,
    QTableWidgetItem,
    QLineEdit,
)

from conciliador import ConciliacionTab, load_qss
from deudores import DeudoresWidget
from dashboard import DashboardWidget
from envios import EnviosWidget
from admin_carteras import AdminCarterasWidget

from auth.auth_service import (
    backend_close_session,
    backend_list_pending_recovery_requests,
    backend_reset_pending_recovery_request,
)
from auth.session_history_db import close_session
from legal import LegalDocumentDialog, enforce_legal_acceptance, get_privacy_text, get_terms_text


def _app_icon_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "assets", "app_icon.ico"),
        os.path.join(base_dir, "app_icon.ico"),
        os.path.join(os.path.dirname(sys.executable), "app_icon.ico"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


class _ColorTabBar(QTabBar):
    ACCENTS = [
        (37, 99, 235),
        (124, 58, 237),
        (8, 145, 178),
        (5, 150, 105),
        (234, 88, 12),
        (217, 70, 239),
    ]
    INDICATOR_H = 3
    TAB_H = 56
    TAB_MIN_W = 104

    def tabSizeHint(self, index: int):
        sz = super().tabSizeHint(index)
        sz.setHeight(self.TAB_H)
        sz.setWidth(max(sz.width(), self.TAB_MIN_W))
        return sz

    def minimumTabSizeHint(self, index: int):
        sz = super().minimumTabSizeHint(index)
        sz.setHeight(self.TAB_H)
        sz.setWidth(max(sz.width(), 96))
        return sz

    def paintEvent(self, event):
        from PyQt6.QtCore import QRect, Qt
        from PyQt6.QtGui import QColor, QFont, QPainter

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        for i in range(self.count()):
            rect = self.tabRect(i)
            is_sel = self.currentIndex() == i
            r, g, b = self.ACCENTS[i] if i < len(self.ACCENTS) else self.ACCENTS[0]
            accent = QColor(r, g, b)

            if is_sel:
                tint = QColor(r, g, b, 18)
                p.fillRect(rect, tint)
            else:
                p.fillRect(rect, QColor("#ffffff"))

            if i < self.count() - 1:
                sep_x = rect.right()
                p.setPen(QColor("#e2e8f0"))
                p.drawLine(sep_x, rect.top() + 10, sep_x, rect.bottom() - 10)

            text = self.tabText(i)
            parts = text.strip().split(None, 1)
            icon = parts[0] if parts else ""
            name = parts[1].strip() if len(parts) > 1 else text.strip()

            text_rect = rect.adjusted(4, 2, -4, -self.INDICATOR_H - 2)

            p.save()
            if is_sel:
                p.setPen(accent)
                icon_font = QFont("Segoe UI Emoji", 16)
                p.setFont(icon_font)
                icon_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), text_rect.height() // 2)
                p.drawText(icon_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, icon)

                p.setPen(accent)
                name_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
                p.setFont(name_font)
                name_rect = QRect(
                    text_rect.left(),
                    text_rect.top() + text_rect.height() // 2,
                    text_rect.width(),
                    text_rect.height() // 2,
                )
                p.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)
            else:
                p.setPen(QColor("#94a3b8"))
                icon_font = QFont("Segoe UI Emoji", 14)
                p.setFont(icon_font)
                icon_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), text_rect.height() // 2)
                p.drawText(icon_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, icon)

                p.setPen(QColor("#64748b"))
                name_font = QFont("Segoe UI", 9)
                p.setFont(name_font)
                name_rect = QRect(
                    text_rect.left(),
                    text_rect.top() + text_rect.height() // 2,
                    text_rect.width(),
                    text_rect.height() // 2,
                )
                p.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)
            p.restore()

            if is_sel:
                ind = QRect(rect.left(), rect.bottom() - self.INDICATOR_H + 1, rect.width(), self.INDICATOR_H)
                p.fillRect(ind, accent)

        p.end()


class TemporaryPasswordDialog(QDialog):
    def __init__(self, *, username: str, temp_password: str, parent=None):
        super().__init__(parent)
        self._temp_password = str(temp_password or "")
        self.setWindowTitle("Contrasena temporal generada")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        msg = QLabel(
            "Comparte esta contrasena por canal seguro. "
            "El usuario debera cambiarla al iniciar sesion."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("color:#334155; font-size:9pt;")
        layout.addWidget(msg)

        user_lbl = QLabel(f"Usuario: {username}")
        user_lbl.setStyleSheet("font-weight:700; color:#0f172a;")
        layout.addWidget(user_lbl)

        row = QHBoxLayout()
        self.password_edit = QLineEdit(self._temp_password)
        self.password_edit.setReadOnly(True)
        self.password_edit.setMinimumHeight(38)
        self.password_edit.setStyleSheet(
            """
            QLineEdit {
                background:#f8fafc;
                border:1px solid #cbd5e1;
                border-radius:8px;
                padding:0 10px;
                font-family:Consolas;
                font-size:10pt;
                color:#0f172a;
            }
            """
        )
        row.addWidget(self.password_edit, 1)

        self.btn_copy = QPushButton("Copiar contrasena")
        self.btn_copy.setMinimumHeight(38)
        self.btn_copy.setStyleSheet(
            """
            QPushButton {
                background:#2563eb; color:#ffffff; border:none; border-radius:8px; padding:0 12px; font-weight:600;
            }
            QPushButton:hover { background:#1d4ed8; }
            """
        )
        self.btn_copy.clicked.connect(self._copy_password)
        row.addWidget(self.btn_copy)
        layout.addLayout(row)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#16a34a; font-size:8.5pt;")
        layout.addWidget(self.lbl_status)

        btn_close = QPushButton("Cerrar")
        btn_close.setMinimumHeight(34)
        btn_close.setStyleSheet(
            """
            QPushButton {
                background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; border-radius:8px; padding:0 14px;
            }
            QPushButton:hover { background:#e2e8f0; }
            """
        )
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignRight)

        self.password_edit.selectAll()
        self.password_edit.setFocus()

    def _copy_password(self):
        QApplication.clipboard().setText(self._temp_password)
        self.lbl_status.setText("Contrasena copiada al portapapeles.")


class RecoveryNotificationsDialog(QDialog):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session
        self.setWindowTitle("Solicitudes de recuperacion")
        self.setMinimumSize(760, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Solicitudes pendientes")
        title.setStyleSheet("font-size:14pt; font-weight:700; color:#0f172a;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Aqui veras solicitudes de recuperacion segun tu rol. "
            "Usa el boton \"Reestablecer\" para generar contrasena temporal."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#64748b; font-size:9pt;")
        layout.addWidget(subtitle)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Correo solicitado", "Usuario", "Rol", "Fecha", "Accion"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(
            """
            QTableWidget {
                border:1px solid #e2e8f0;
                border-radius:10px;
                gridline-color:#eef2f7;
                background:#ffffff;
            }
            QHeaderView::section {
                background:#f8fafc;
                color:#334155;
                border:none;
                border-bottom:1px solid #e2e8f0;
                padding:8px;
                font-weight:700;
            }
            """
        )
        layout.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.setMinimumHeight(34)
        self.btn_refresh.setStyleSheet(
            """
            QPushButton {
                background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; border-radius:8px; padding:0 12px;
            }
            QPushButton:hover { background:#e2e8f0; }
            """
        )
        self.btn_refresh.clicked.connect(self.reload)
        foot.addWidget(self.btn_refresh)
        foot.addStretch(1)

        btn_close = QPushButton("Cerrar")
        btn_close.setMinimumHeight(34)
        btn_close.setStyleSheet(
            """
            QPushButton {
                background:#2563eb; color:white; border:none; border-radius:8px; padding:0 14px; font-weight:600;
            }
            QPushButton:hover { background:#1d4ed8; }
            """
        )
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_close)
        layout.addLayout(foot)

        self.reload()

    def reload(self):
        rows, err = backend_list_pending_recovery_requests(self._session)
        if err:
            QMessageBox.warning(self, "Recuperaciones", err)
            return

        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)

            req_id = int(row.get("id", 0) or 0)
            requested_email = str(row.get("requested_email", "") or "")
            target_username = str(row.get("target_username", "") or "")
            target_role_label = str(row.get("target_role_label", row.get("target_role", "")) or "")
            requested_at = str(row.get("requested_at", "") or "")

            self.table.setItem(r, 0, QTableWidgetItem(requested_email))
            self.table.setItem(r, 1, QTableWidgetItem(target_username))
            self.table.setItem(r, 2, QTableWidgetItem(target_role_label))
            self.table.setItem(r, 3, QTableWidgetItem(requested_at))

            btn_reset = QPushButton("Reestablecer")
            btn_reset.setMinimumHeight(30)
            btn_reset.setStyleSheet(
                """
                QPushButton {
                    background:#2563eb; color:white; border:none; border-radius:7px; padding:0 10px; font-weight:600;
                }
                QPushButton:hover { background:#1d4ed8; }
                """
            )
            btn_reset.clicked.connect(lambda _, rid=req_id: self._do_reset(rid))
            self.table.setCellWidget(r, 4, btn_reset)

        if self.table.rowCount() == 0:
            self.table.setRowCount(1)
            self.table.setSpan(0, 0, 1, 5)
            self.table.setItem(0, 0, QTableWidgetItem("No hay solicitudes pendientes para tu rol."))

    def _do_reset(self, request_id: int):
        resp = QMessageBox.question(
            self,
            "Reestablecer contrasena",
            "Deseas generar una contrasena temporal para esta solicitud?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        data, err = backend_reset_pending_recovery_request(self._session, request_id=request_id)
        if err:
            QMessageBox.warning(self, "No se pudo reestablecer", err)
            self.reload()
            return

        payload = data or {}
        user = payload.get("user") or {}
        username = str(user.get("username", "") or "")
        temp_password = str(payload.get("temporary_password", "") or "")
        if not temp_password:
            QMessageBox.warning(self, "Sin contrasena temporal", "El backend no devolvio una contrasena temporal.")
            self.reload()
            return

        dlg = TemporaryPasswordDialog(username=username, temp_password=temp_password, parent=self)
        dlg.exec()
        self.reload()


class MainWindow(QMainWindow):
    def __init__(self, session=None):
        super().__init__()
        self._session = session
        self._session_closed = False
        self._last_pending_recovery_ids: set[int] = set()
        icon_path = _app_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        username = session.username if session else "Usuario"
        self.setWindowTitle(f"Controlia Cobranzas  |  {username}")
        self.setMinimumSize(760, 520)

        screen = QApplication.primaryScreen()
        available = screen.availableGeometry()
        w = min(int(available.width() * 0.92), 1600)
        h = min(int(available.height() * 0.92), 1000)
        self.resize(w, h)
        x = available.x() + (available.width() - w) // 2
        y = available.y() + (available.height() - h) // 2
        self.move(x, y)
        if available.width() <= 1366 or available.height() <= 768:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if session:
            from auth.auth_service import ROLES

            role_label = ROLES.get(session.role, session.role.capitalize())
            role_colors = {
                "admin": ("#fef9c3", "#92400e"),
                "supervisor": ("#dcfce7", "#15803d"),
                "ejecutivo": ("#dbeafe", "#1d4ed8"),
            }
            rb, rf = role_colors.get(session.role, ("#e2e8f0", "#374151"))

            user_strip = QWidget()
            user_strip.setMinimumHeight(34)
            user_strip.setStyleSheet("background: #1e3a8a;")
            strip_row = QHBoxLayout(user_strip)
            strip_row.setContentsMargins(16, 4, 16, 4)
            strip_row.setSpacing(10)
            strip_row.addStretch(1)

            lbl_user = QLabel(f"👤  {session.username}  ·  {session.email}")
            lbl_user.setStyleSheet("color:#bfdbfe; font-size:8pt; background:transparent;")
            strip_row.addWidget(lbl_user)

            lbl_role = QLabel(role_label)
            lbl_role.setMinimumHeight(22)
            lbl_role.setStyleSheet(
                f"background:{rb}; color:{rf}; border-radius:4px;"
                f" padding:0 8px; font-size:7.5pt; font-weight:700;"
            )
            strip_row.addWidget(lbl_role)

            self._btn_recovery = None
            self._recovery_poll_timer = None
            if session.role in {"admin", "supervisor"}:
                self._btn_recovery = QPushButton("🔔 Recuperaciones")
                self._btn_recovery.setMinimumHeight(26)
                self._btn_recovery.setStyleSheet(
                    """
                    QPushButton {
                        background: #1d4ed8; color: #e0ecff;
                        border: 1px solid #3b82f6; border-radius: 4px;
                        padding: 0 8px; font-size: 8pt; font-weight:600;
                    }
                    QPushButton:hover { background: #2563eb; color: white; }
                    """
                )
                self._btn_recovery.clicked.connect(self._open_recovery_dialog)
                strip_row.addWidget(self._btn_recovery)

            btn_logout = QPushButton("Cerrar sesión")
            btn_logout.setMinimumHeight(26)
            btn_logout.setStyleSheet(
                """
                QPushButton {
                    background: transparent; color: #93c5fd;
                    border: 1px solid #3b82f6; border-radius: 4px;
                    padding: 0 8px; font-size: 8pt;
                }
                QPushButton:hover { background: #1d4ed8; color: white; }
                """
            )
            btn_logout.clicked.connect(self._logout)
            strip_row.addWidget(btn_logout)
            layout.addWidget(user_strip)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.setTabBar(_ColorTabBar())
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setStyleSheet(
            """
            QTabWidget#MainTabs::pane {
                border: none;
                border-top: 1px solid #e2e8f0;
                background: #f0f4f8;
            }
            QTabWidget#MainTabs > QTabBar {
                background: #ffffff;
                border-bottom: 1px solid #e2e8f0;
            }
            """
        )

        self.tab_dashboard = DashboardWidget(session=session)
        self.tabs.addTab(self.tab_dashboard, "📊  Dashboard")

        if session is None or session.is_supervisor_or_above():
            self.tab_conciliacion = ConciliacionTab()
            self.tabs.addTab(self.tab_conciliacion, "📋  Conciliación de Nóminas")

        self.tab_deudores = DeudoresWidget(session=session)
        self.tabs.addTab(self.tab_deudores, "🔍  Búsqueda de Deudores")
        self.tab_deudores.datos_actualizados.connect(self.tab_dashboard.refrescar)
        self.tab_dashboard.bd_limpiada.connect(self.tab_deudores.limpiar_empresa_en_vista)

        if session is None or session.is_supervisor_or_above():
            self.tab_envios = EnviosWidget(session=session)
            self.tabs.addTab(self.tab_envios, "📧  Envíos Programados")

        if session and session.is_supervisor_or_above():
            self.tab_admin_carteras = AdminCarterasWidget(session=session)
            self.tabs.addTab(self.tab_admin_carteras, "🛠️  Administración de carteras")
            self.tab_admin_carteras.datos_actualizados.connect(self.tab_dashboard.refrescar)
            self.tab_admin_carteras.datos_actualizados.connect(self.tab_deudores.refrescar_datos)
            self.tab_admin_carteras.bd_limpiada.connect(self.tab_deudores.limpiar_empresa_en_vista)

        if session and session.is_admin():
            from auth.views.users_panel import UsersPanel

            self.tab_users = UsersPanel(session=session)
            self.tabs.addTab(self.tab_users, "👥  Usuarios")

        layout.addWidget(self.tabs)
        self._init_legal_menu()
        self._init_recovery_notifications()

    def _init_legal_menu(self):
        menu_ayuda = self.menuBar().addMenu("Ayuda")

        act_terms = QAction("Términos y Condiciones", self)
        act_terms.triggered.connect(self._abrir_terminos)
        menu_ayuda.addAction(act_terms)

        act_privacy = QAction("Política de Privacidad", self)
        act_privacy.triggered.connect(self._abrir_privacidad)
        menu_ayuda.addAction(act_privacy)

    def _abrir_terminos(self):
        texto, err = get_terms_text()
        if err:
            QMessageBox.warning(self, "Términos y Condiciones", err)
            return
        LegalDocumentDialog(
            title="Términos y Condiciones - Controlia Cobranzas",
            body_text=texto,
            parent=self,
        ).exec()

    def _abrir_privacidad(self):
        texto, err = get_privacy_text()
        if err:
            QMessageBox.warning(self, "Política de Privacidad", err)
            return
        LegalDocumentDialog(
            title="Política de Privacidad - Controlia Cobranzas",
            body_text=texto,
            parent=self,
        ).exec()

    def _cerrar_sesion_activa(self):
        if self._session_closed or not self._session:
            return

        if getattr(self._session, "auth_source", "") == "backend":
            backend_close_session(self._session)
        else:
            close_session(
                session_id=getattr(self._session, "session_history_id", None),
                user_id=getattr(self._session, "user_id", None),
            )
        self._session_closed = True

    def _init_recovery_notifications(self):
        if not self._session or getattr(self._session, "auth_source", "") != "backend":
            return
        if str(getattr(self._session, "role", "")).strip().lower() not in {"admin", "supervisor"}:
            return

        QTimer.singleShot(1200, lambda: self._check_recovery_notifications(show_popup=True))
        self._recovery_poll_timer = QTimer(self)
        self._recovery_poll_timer.setInterval(45000)
        self._recovery_poll_timer.timeout.connect(lambda: self._check_recovery_notifications(show_popup=False))
        self._recovery_poll_timer.start()

    def _check_recovery_notifications(self, *, show_popup: bool):
        rows, err = backend_list_pending_recovery_requests(self._session)
        if err:
            return

        pending_ids = {int(r.get("id", 0) or 0) for r in rows if int(r.get("id", 0) or 0) > 0}
        new_ids = pending_ids - self._last_pending_recovery_ids
        self._last_pending_recovery_ids = pending_ids

        if getattr(self, "_btn_recovery", None) is not None:
            if pending_ids:
                self._btn_recovery.setText(f"🔔 Recuperaciones ({len(pending_ids)})")
            else:
                self._btn_recovery.setText("🔔 Recuperaciones")

        if show_popup and pending_ids:
            QMessageBox.information(
                self,
                "Notificacion de recuperacion",
                f"Tienes {len(pending_ids)} solicitud(es) pendientes.\n"
                "Presiona \"Reestablecer\" para generar la contrasena temporal.",
            )
            self._open_recovery_dialog()
        elif (not show_popup) and new_ids:
            QMessageBox.information(
                self,
                "Nueva solicitud",
                "Recibiste una nueva solicitud de recuperacion de contrasena.",
            )

    def _open_recovery_dialog(self):
        if not self._session:
            return
        dlg = RecoveryNotificationsDialog(self._session, self)
        dlg.exec()
        self._check_recovery_notifications(show_popup=False)

    def _logout(self):
        resp = QMessageBox.question(
            self,
            "Cerrar sesión",
            "¿Deseas cerrar la sesión y volver al login?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._cerrar_sesion_activa()
            self.close()

            from auth import AuthWindow

            auth = AuthWindow()
            result = auth.exec()
            if result == AuthWindow.DialogCode.Accepted and auth.session:
                if not enforce_legal_acceptance(auth.session):
                    return
                new_win = MainWindow(session=auth.session)
                new_win.show()
                QApplication.instance()._main_window = new_win

    def closeEvent(self, event):
        self._cerrar_sesion_activa()
        super().closeEvent(event)


def main():
    ensure_runtime_dirs()
    configure_logging()

    app = QApplication(sys.argv)
    icon_path = _app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    base_dir = os.path.dirname(os.path.abspath(__file__))
    qss_path = os.path.join(base_dir, "styles.qss")
    load_qss(app, qss_path)

    from auth import AuthWindow

    auth = AuthWindow()
    result = auth.exec()
    if result != AuthWindow.DialogCode.Accepted or auth.session is None:
        sys.exit(0)

    if not enforce_legal_acceptance(auth.session):
        sys.exit(0)

    w = MainWindow(session=auth.session)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

