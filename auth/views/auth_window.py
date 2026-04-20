# ================================================================
#  auth/views/auth_window.py
# ================================================================

from __future__ import annotations
import math

from PyQt6.QtCore import QRect, QRectF, Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient,
    QPainter, QPainterPath, QPen, QRadialGradient
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame,
    QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget,
    QSizePolicy, QVBoxLayout, QWidget,
)

from auth.auth_service import (
    UserSession,
    confirm_password_reset,
    force_change_password,
    login,
    password_strength,
    request_password_reset,
)
from auth.session_history_db import register_login


class _LeftPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(140)
        self.setMaximumWidth(330)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._angle = 0.0
        t = QTimer(self)
        t.setInterval(40)
        t.timeout.connect(self._tick)
        t.start()

    def _tick(self):
        self._angle = (self._angle + 0.5) % 360
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        g = QLinearGradient(0, 0, w * 0.3, h)
        g.setColorAt(0.0, QColor("#1e40af"))
        g.setColorAt(0.55, QColor("#2563eb"))
        g.setColorAt(1.0, QColor("#1d4ed8"))
        p.fillRect(self.rect(), QBrush(g))

        c = QColor(255, 255, 255, 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(w - 60, -90, 240, 240)

        p.setBrush(QColor(255, 255, 255, 8))
        p.drawEllipse(-50, h // 2 - 70, 160, 160)

        p.setPen(QPen(QColor(255, 255, 255, 60), 2))
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(w // 2 - 14, h // 5, 28, 90, 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#60a5fa"))
        p.drawEllipse(w // 2 - 8, h // 5 + 8, 16, 16)

        p.setBrush(QColor("#93c5fd"))
        p.drawEllipse(w - 55, 65, 10, 10)

        p.setBrush(QColor(255, 255, 255, 40))
        for r in range(5):
            for c_ in range(5):
                p.drawEllipse(18 + c_ * 14, 18 + r * 14, 3, 3)

        for r in range(4):
            for c_ in range(4):
                p.drawEllipse(w - 70 + c_ * 14, h - 70 + r * 14, 3, 3)

        pen_x = QPen(QColor(255, 255, 255, 80), 2)
        pen_x.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_x)
        p.drawLine(30, h - 78, 46, h - 62)
        p.drawLine(46, h - 78, 30, h - 62)

        p.setPen(QPen(QColor(255, 255, 255, 60), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc_r = QRectF(w - 65, h - 120, 130, 130)
        p.drawArc(arc_r, int(self._angle * 16), 200 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#38bdf8"))
        rad = math.radians(self._angle)
        bx = arc_r.center().x() + 65 * math.cos(rad) - 5
        by = arc_r.center().y() + 65 * math.sin(rad) - 5
        p.drawEllipse(int(bx), int(by), 10, 10)

        sg = QRadialGradient(w // 2, h - 30, 55)
        sg.setColorAt(0.0, QColor("#38bdf8"))
        sg.setColorAt(0.6, QColor("#2563eb"))
        sg.setColorAt(1.0, QColor("#1e3a8a"))
        p.setBrush(QBrush(sg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawChord(QRectF(w // 2 - 55, h - 80, 110, 110), 0, 180 * 16)

        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Segoe UI", 21, QFont.Weight.Bold))
        ty = int(h * 0.40)
        p.drawText(QRect(22, ty, w - 44, 80), Qt.AlignmentFlag.AlignLeft, "Controlia\nCobranzas")
        p.setPen(QColor(255, 255, 255, 175))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(
            QRect(22, ty + 78, w - 44, 50),
            Qt.AlignmentFlag.AlignLeft,
            "Gestión de cobranzas\ninteligente para Isapres",
        )
        p.end()


class _Logo(QWidget):
    SIZE = 60

    def __init__(self, p=None):
        super().__init__(p)
        self.setMinimumSize(self.SIZE, self.SIZE)
        self.setMaximumSize(self.SIZE, self.SIZE)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.SIZE, self.SIZE)
        g.setColorAt(0, QColor("#3b82f6"))
        g.setColorAt(1, QColor("#2563eb"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.SIZE, self.SIZE), 15, 15)
        p.fillPath(path, QBrush(g))
        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        p.drawText(QRect(0, 0, self.SIZE, self.SIZE), Qt.AlignmentFlag.AlignCenter, "ER")
        p.end()


_FIELD_NORMAL = """
    QLineEdit {
        background:#f8fafc; border:1.5px solid #e2e8f0;
        border-radius:10px; padding:0 14px; font-size:9pt; color:#0f172a;
    }
    QLineEdit:focus { border:1.5px solid #2563eb; background:#fff; }
"""
_FIELD_ERROR = """
    QLineEdit {
        background:#fff5f5; border:1.5px solid #dc2626;
        border-radius:10px; padding:0 14px; font-size:9pt; color:#0f172a;
    }
    QLineEdit:focus { border:1.5px solid #dc2626; background:#fff5f5; }
"""
_BTN_PRIMARY = """
    QPushButton { background:#2563eb; color:#fff; border:none;
        border-radius:10px; font-size:10pt; font-weight:600; }
    QPushButton:hover   { background:#1d4ed8; }
    QPushButton:pressed { background:#1e40af; }
    QPushButton:disabled{ background:#93c5fd; }
"""
_BTN_SEC = """
    QPushButton { background:#f1f5f9; color:#374151;
        border:1.5px solid #e2e8f0; border-radius:10px;
        font-size:9pt; font-weight:600; }
    QPushButton:hover { background:#e2e8f0; }
"""
_BTN_LINK = """
    QPushButton { background:transparent; color:#2563eb;
        border:none; font-size:9pt; text-decoration:underline; padding:0; }
    QPushButton:hover { color:#1d4ed8; }
"""


class _Field(QWidget):
    def __init__(self, label: str, placeholder: str, password: bool = False, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#374151;")
        lay.addWidget(lbl)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumHeight(40)
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setStyleSheet(_FIELD_NORMAL)
        lay.addWidget(self.edit)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#dc2626; font-size:8pt;")
        self.lbl_err.setVisible(False)
        lay.addWidget(self.lbl_err)

    def set_error(self, msg: str):
        self.lbl_err.setText(msg)
        self.lbl_err.setVisible(bool(msg))
        self.edit.setStyleSheet(_FIELD_ERROR if msg else _FIELD_NORMAL)

    def clear_error(self):
        self.set_error("")

    @property
    def value(self) -> str:
        return self.edit.text()


def _primary_btn(text: str, h: int = 44) -> QPushButton:
    b = QPushButton(text)
    b.setMinimumHeight(h)
    b.setStyleSheet(_BTN_PRIMARY)
    return b


def _sec_btn(text: str, h: int = 38) -> QPushButton:
    b = QPushButton(text)
    b.setMinimumHeight(h)
    b.setStyleSheet(_BTN_SEC)
    return b


def _link_btn(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(_BTN_LINK)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFlat(True)
    return b


def _hr() -> QWidget:
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 4, 0, 4)
    row.setSpacing(8)
    for _ in range(2):
        l = QFrame()
        l.setFrameShape(QFrame.Shape.HLine)
        l.setStyleSheet("color:#e2e8f0;")
        row.addWidget(l, 1)
    return w


class _LoginPage(QWidget):
    sig_ok = pyqtSignal(object)
    sig_forgot = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("Controlia", "ControliaCobranzas")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(44, 28, 44, 28)
        lay.setSpacing(0)
        self._root_layout = lay

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(_Logo())
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(14)

        t = QLabel("¡Bienvenido de vuelta!")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        t.setStyleSheet("color:#0f172a;")
        lay.addWidget(t)
        lay.addSpacing(4)

        s = QLabel("Inicia sesión en tu cuenta")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet("color:#64748b; font-size:9pt;")
        lay.addWidget(s)
        lay.addSpacing(22)

        self.f_email = _Field("Correo electrónico", "tucorreo@ejemplo.cl")
        self.f_pass = _Field("Contraseña", "**********", password=True)
        self.f_email.edit.returnPressed.connect(self._do)
        self.f_pass.edit.returnPressed.connect(self._do)
        lay.addWidget(self.f_email)
        lay.addSpacing(12)
        lay.addWidget(self.f_pass)
        lay.addSpacing(8)

        opt = QHBoxLayout()
        self.chk = QCheckBox("Recordarme")
        self.chk.setStyleSheet("color:#374151; font-size:9pt;")
        opt.addWidget(self.chk)
        opt.addStretch(1)
        bf = _link_btn("¿Olvidaste tu contraseña?")
        bf.clicked.connect(self.sig_forgot.emit)
        opt.addWidget(bf)
        lay.addLayout(opt)
        lay.addSpacing(18)

        self.btn = _primary_btn("Iniciar sesión", 46)
        self.btn.clicked.connect(self._do)
        lay.addWidget(self.btn)
        lay.addSpacing(16)
        lay.addWidget(_hr())
        lay.addSpacing(8)

        info = QLabel("Las cuentas son creadas por el Administrador del sistema.")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("color:#94a3b8; font-size:8pt;")
        lay.addWidget(info)
        lay.addStretch(1)
        self._load_remembered_email()

    def _load_remembered_email(self) -> None:
        remembered = str(self._settings.value("auth/remembered_email", "") or "").strip()
        if remembered:
            self.f_email.edit.setText(remembered)
            self.chk.setChecked(True)
            self.f_pass.edit.setFocus()
        else:
            self.chk.setChecked(False)

    def _persist_remembered_email(self, email: str) -> None:
        if self.chk.isChecked():
            self._settings.setValue("auth/remembered_email", str(email or "").strip())
        else:
            self._settings.remove("auth/remembered_email")
        self._settings.sync()

    def apply_responsive(self, width: int) -> None:
        if width <= 760:
            self._root_layout.setContentsMargins(18, 16, 18, 16)
            self.btn.setMinimumHeight(40)
        elif width <= 980:
            self._root_layout.setContentsMargins(28, 20, 28, 20)
            self.btn.setMinimumHeight(42)
        else:
            self._root_layout.setContentsMargins(44, 28, 44, 28)
            self.btn.setMinimumHeight(46)

    def _do(self):
        self.f_email.clear_error()
        self.f_pass.clear_error()

        email = self.f_email.value.strip()

        if not email:
            self.f_email.set_error("Ingresa tu correo.")
            return
        if not self.f_pass.value:
            self.f_pass.set_error("Ingresa tu contraseña.")
            return

        self.btn.setEnabled(False)
        self.btn.setText("Verificando...")
        session, err = login(email, self.f_pass.value)
        self.btn.setEnabled(True)
        self.btn.setText("Iniciar sesión")

        if session:
            self._persist_remembered_email(email)
            self.sig_ok.emit(session)
        else:
            self.f_pass.set_error(err)
            self.f_email.set_error(" ")


class _ForceChangePage(QWidget):
    sig_done = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: UserSession | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(44, 30, 44, 30)
        lay.setSpacing(0)
        self._root_layout = lay

        banner = QWidget()
        banner.setStyleSheet("background:#fef9c3; border-radius:8px; padding:4px;")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(12, 8, 12, 8)
        lbl_b = QLabel("Debes establecer tu contraseña antes de continuar.")
        lbl_b.setStyleSheet("color:#92400e; font-size:9pt; font-weight:600;")
        lbl_b.setWordWrap(True)
        bl.addWidget(lbl_b)
        lay.addWidget(banner)
        lay.addSpacing(18)

        t = QLabel("Crear tu contraseña")
        t.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        t.setStyleSheet("color:#0f172a;")
        lay.addWidget(t)
        lay.addSpacing(4)

        self.lbl_user = QLabel("")
        self.lbl_user.setStyleSheet("color:#64748b; font-size:9pt;")
        lay.addWidget(self.lbl_user)
        lay.addSpacing(20)

        self.f_new = _Field("Nueva contraseña", "Mínimo 8 caracteres", password=True)
        self.f_conf = _Field("Confirmar contraseña", "Repite la contraseña", password=True)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setStyleSheet("""
            QProgressBar { background:#e2e8f0; border:none; border-radius:2px; }
            QProgressBar::chunk { background:#2563eb; border-radius:2px; }
        """)
        self.lbl_str = QLabel("")
        self.lbl_str.setStyleSheet("font-size:8pt; color:#64748b;")
        self.f_new.edit.textChanged.connect(self._upd_strength)

        lay.addWidget(self.f_new)
        lay.addSpacing(4)
        lay.addWidget(self.bar)
        lay.addWidget(self.lbl_str)
        lay.addSpacing(12)
        lay.addWidget(self.f_conf)
        lay.addSpacing(16)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#dc2626; font-size:8.5pt;")
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setVisible(False)
        lay.addWidget(self.lbl_err)
        lay.addSpacing(4)

        self.btn = _primary_btn("Guardar y continuar", 44)
        self.btn.clicked.connect(self._do)
        lay.addWidget(self.btn)
        lay.addStretch(1)

    def apply_responsive(self, width: int) -> None:
        if width <= 760:
            self._root_layout.setContentsMargins(18, 16, 18, 16)
            self.btn.setMinimumHeight(40)
        elif width <= 980:
            self._root_layout.setContentsMargins(28, 20, 28, 20)
            self.btn.setMinimumHeight(42)
        else:
            self._root_layout.setContentsMargins(44, 30, 44, 30)
            self.btn.setMinimumHeight(44)

    def load_session(self, session: UserSession):
        self._session = session
        self.lbl_user.setText(f"Cuenta: {session.email}")

    def _upd_strength(self, text):
        if not text:
            self.bar.setValue(0)
            self.lbl_str.setText("")
            return
        sc, lb = password_strength(text)
        self.bar.setValue(sc)
        color = {
            "Débil": "#dc2626",
            "Media": "#f59e0b",
            "Fuerte": "#16a34a",
            "Muy fuerte": "#0891b2",
        }.get(lb, "#64748b")
        self.bar.setStyleSheet(f"""
            QProgressBar {{ background:#e2e8f0; border:none; border-radius:2px; }}
            QProgressBar::chunk {{ background:{color}; border-radius:2px; }}
        """)
        self.lbl_str.setText(f"Contraseña: {lb}")
        self.lbl_str.setStyleSheet(f"font-size:8pt; color:{color};")

    def _do(self):
        self.lbl_err.setVisible(False)
        errors = force_change_password(
            self._session,
            self.f_new.value,
            self.f_conf.value,
        )
        if errors:
            self.lbl_err.setText("\n".join(f"- {e}" for e in errors))
            self.lbl_err.setVisible(True)
            return

        if getattr(self._session, "auth_source", "") == "backend":
            self._session.must_change_password = False
            QMessageBox.information(
                self,
                "Contraseña actualizada",
                "Tu contraseña fue actualizada correctamente.\n"
                "Ya puedes continuar usando el sistema.",
            )
            self.sig_done.emit(self._session)
            return

        from auth.auth_db import UserSession as LocalUserSession, get_user_by_id

        updated = get_user_by_id(self._session.user_id)
        updated_session = LocalUserSession.from_db(updated)
        setattr(
            updated_session,
            "session_history_id",
            getattr(self._session, "session_history_id", None),
        )
        self.sig_done.emit(updated_session)


class _ForgotPage(QWidget):
    sig_done = pyqtSignal()
    sig_go_login = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        lay.addWidget(self._stack)
        self._pg_step1 = self._step1()
        self._pg_step2 = self._step2()
        self._stack.addWidget(self._pg_step1)
        self._stack.addWidget(self._pg_step2)

    def _step1(self) -> QWidget:
        pg = QWidget()
        lay = QVBoxLayout(pg)
        lay.setContentsMargins(44, 28, 44, 28)
        lay.setSpacing(0)
        pg._root_layout = lay

        bb = _sec_btn("<- Volver al login", 36)
        bb.clicked.connect(self.sig_go_login.emit)
        lay.addWidget(bb)
        lay.addSpacing(20)

        t = QLabel("¿Olvidaste tu contraseña?")
        t.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        t.setStyleSheet("color:#0f172a;")
        lay.addWidget(t)
        lay.addSpacing(6)

        d = QLabel("Ingresa tu correo para registrar una solicitud de recuperación asistida.")
        d.setStyleSheet("color:#64748b; font-size:9pt;")
        lay.addWidget(d)
        lay.addSpacing(22)

        self.f1_email = _Field("Correo electrónico", "tucorreo@ejemplo.cl")
        lay.addWidget(self.f1_email)
        lay.addSpacing(16)

        self.lbl_s1_err = QLabel("")
        self.lbl_s1_err.setStyleSheet("color:#dc2626; font-size:8.5pt;")
        self.lbl_s1_err.setVisible(False)
        lay.addWidget(self.lbl_s1_err)
        lay.addSpacing(4)

        self.btn_s1 = _primary_btn("Solicitar recuperación", 44)
        self.btn_s1.clicked.connect(self._req)
        lay.addWidget(self.btn_s1)
        lay.addStretch(1)
        return pg

    def _step2(self) -> QWidget:
        pg = QWidget()
        lay = QVBoxLayout(pg)
        lay.setContentsMargins(44, 24, 44, 24)
        lay.setSpacing(0)
        pg._root_layout = lay

        t = QLabel("Ingresa el código")
        t.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        t.setStyleSheet("color:#0f172a;")
        lay.addWidget(t)
        lay.addSpacing(4)

        self.lbl_s2h = QLabel("")
        self.lbl_s2h.setStyleSheet("color:#64748b; font-size:9pt;")
        self.lbl_s2h.setWordWrap(True)
        lay.addWidget(self.lbl_s2h)
        lay.addSpacing(16)

        self.edit_code = QLineEdit()
        self.edit_code.setPlaceholderText("Código de 6 dígitos")
        self.edit_code.setMaxLength(6)
        self.edit_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_code.setFixedHeight(52)
        self.edit_code.setStyleSheet("""
            QLineEdit { background:#f0f9ff; border:2px solid #bae6fd;
                border-radius:12px; font-size:20pt; font-weight:700;
                color:#0369a1; letter-spacing:10px; }
            QLineEdit:focus { border:2px solid #2563eb; }
        """)
        lay.addWidget(self.edit_code)
        lay.addSpacing(14)

        self.f2_new = _Field("Nueva contraseña", "Mínimo 8 caracteres", password=True)
        self.f2_conf = _Field("Confirmar contraseña", "Repite la contraseña", password=True)
        lay.addWidget(self.f2_new)
        lay.addSpacing(10)
        lay.addWidget(self.f2_conf)
        lay.addSpacing(14)

        self.lbl_s2_err = QLabel("")
        self.lbl_s2_err.setStyleSheet("color:#dc2626; font-size:8.5pt;")
        self.lbl_s2_err.setWordWrap(True)
        self.lbl_s2_err.setVisible(False)
        lay.addWidget(self.lbl_s2_err)
        lay.addSpacing(4)

        self.btn_s2 = _primary_btn("Restablecer contraseña", 44)
        self.btn_s2.clicked.connect(self._reset)
        lay.addWidget(self.btn_s2)
        lay.addSpacing(10)

        bn = _link_btn("Solicitar un nuevo código")
        bn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        lay.addWidget(bn, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(1)
        return pg

    def apply_responsive(self, width: int) -> None:
        if width <= 760:
            m = (18, 16, 18, 16)
        elif width <= 980:
            m = (28, 20, 28, 20)
        else:
            m = (44, 28, 44, 28)

        if hasattr(self._pg_step1, "_root_layout"):
            self._pg_step1._root_layout.setContentsMargins(*m)
        if hasattr(self._pg_step2, "_root_layout"):
            self._pg_step2._root_layout.setContentsMargins(*m)

    def _req(self):
        self.f1_email.clear_error()
        self.lbl_s1_err.setVisible(False)
        self.btn_s1.setEnabled(False)
        self.btn_s1.setText("Procesando…")

        _, err = request_password_reset(self.f1_email.value.strip())

        self.btn_s1.setEnabled(True)
        self.btn_s1.setText("Solicitar recuperación")

        if err:
            # En este flujo el backend responde con mensaje funcional o error explícito.
            if "Solicitud registrada" in err or "recuperación" in err.lower():
                QMessageBox.information(self, "Recuperación asistida", err)
                self.sig_done.emit()
                return
            self.lbl_s1_err.setText(err)
            self.lbl_s1_err.setVisible(True)
            return

        QMessageBox.information(
            self,
            "Recuperación asistida",
            "Solicitud registrada correctamente.\n"
            "Tu recuperación será gestionada por el rol autorizado.",
        )
        self.sig_done.emit()

    def _reset(self):
        self.lbl_s2_err.setVisible(False)
        errors = confirm_password_reset(
            getattr(self, "_email_reset", ""),
            self.edit_code.text().strip(),
            self.f2_new.value,
            self.f2_conf.value,
        )
        if errors:
            self.lbl_s2_err.setText("\n".join(f"- {e}" for e in errors))
            self.lbl_s2_err.setVisible(True)
            return

        QMessageBox.information(
            self,
            "Contraseña restablecida",
            "Tu contraseña fue actualizada.\n"
            "Ya puedes iniciar sesión con la nueva contraseña.",
        )
        self.sig_done.emit()


class AuthWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Controlia Cobranzas - Acceso")
        self.setMinimumSize(620, 420)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            w = min(840, max(680, int(available.width() * 0.9)))
            h = min(570, max(480, int(available.height() * 0.9)))
            self.resize(w, h)
        else:
            self.resize(840, 570)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.session: UserSession | None = None

        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(28)
        sh.setOffset(0, 5)
        sh.setColor(QColor(0, 0, 0, 55))
        self.setGraphicsEffect(sh)
        self.setStyleSheet("QDialog { background:#f0f4f8; }")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._left_panel = _LeftPanel()
        root.addWidget(self._left_panel)

        right = QWidget()
        right.setStyleSheet("QWidget { background:#ffffff; }")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        rl.addWidget(self._stack)
        root.addWidget(right, 1)

        self._pg_login = _LoginPage()
        self._pg_force = _ForceChangePage()
        self._pg_forgot = _ForgotPage()

        self._stack.addWidget(self._pg_login)
        self._stack.addWidget(self._pg_force)
        self._stack.addWidget(self._pg_forgot)

        self._pg_login.sig_ok.connect(self._after_login)
        self._pg_login.sig_forgot.connect(lambda: self._stack.setCurrentIndex(2))
        self._pg_force.sig_done.connect(self._on_auth_ok)
        self._pg_forgot.sig_done.connect(lambda: self._stack.setCurrentIndex(0))
        self._pg_forgot.sig_go_login.connect(lambda: self._stack.setCurrentIndex(0))

        self._stack.setCurrentIndex(0)
        self._apply_responsive()

    def _after_login(self, session: UserSession):
        if getattr(session, "auth_source", "") != "backend" and not getattr(session, "session_history_id", None):
            try:
                setattr(session, "session_history_id", register_login(session))
            except Exception:
                setattr(session, "session_history_id", None)

        if session.must_change_password:
            self._pg_force.load_session(session)
            self._stack.setCurrentIndex(1)
        else:
            self._on_auth_ok(session)

    def _on_auth_ok(self, session: UserSession):
        self.session = session
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_responsive()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive()

    def _apply_responsive(self):
        w = max(self.width(), 1)
        left_w = int(w * 0.28)
        left_w = max(150, min(320, left_w))
        self._left_panel.setMinimumWidth(left_w)
        self._left_panel.setMaximumWidth(left_w)

        right_w = max(w - left_w, 300)
        self._pg_login.apply_responsive(right_w)
        self._pg_force.apply_responsive(right_w)
        self._pg_forgot.apply_responsive(right_w)

    def closeEvent(self, event):
        QApplication.quit()
        event.accept()




