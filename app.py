import os
import sys

from core.logging_config import configure_logging
from core.paths import ensure_runtime_dirs

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont
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
)

from conciliador import ConciliacionTab, load_qss
from deudores import DeudoresWidget
from dashboard import DashboardWidget
from envios import EnviosWidget
from admin_carteras import AdminCarterasWidget

from auth.session_history_db import close_session
from legal import LegalDocumentDialog, enforce_legal_acceptance, get_privacy_text, get_terms_text


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


class MainWindow(QMainWindow):
    def __init__(self, session=None):
        super().__init__()
        self._session = session
        self._session_closed = False

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

        close_session(
            session_id=getattr(self._session, "session_history_id", None),
            user_id=getattr(self._session, "user_id", None),
        )
        self._session_closed = True

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
