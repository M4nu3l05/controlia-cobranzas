from __future__ import annotations

from datetime import datetime
import time
import unicodedata

import pandas as pd
import requests
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from admin_carteras.service import (
    obtener_empresas_asignadas_para_session,
    session_tiene_restriccion_por_cartera,
)
from auth.auth_service import get_backend_base_url
from auth.session_history_db import obtener_conexiones_hoy, obtener_conexiones_mes
from comisiones.service import obtener_comision_propia, obtener_tasas
from dashboard.worker import DashboardLoadWorker
from deudores.database import cargar_para_envio
from deudores.detalle_dialog import (
    AgregarGestionDialog,
    CorreoDeudorDialog,
    cargar_detalle_deudor_para_dialogos,
)
from deudores.gestiones_db import ESTADO_DEUDOR_DEFAULT
from dashboard.view import DashboardWidget as _LegacyDashboardWidget


# Cada fila de la cola cuesta ~28 widgets: construirlas todas de golpe congela
# la interfaz varios segundos. Se dibujan por tandas, en orden de prioridad.
QUEUE_PAGE_SIZE = 100

BG = "#F4F6FA"
TEXT = "#1E293B"
SECONDARY = "#64748B"
MUTED = "#94A3B8"
BLUE = "#2563EB"


def _money(value) -> str:
    try:
        return "$" + f"{int(round(float(value))):,}".replace(",", ".")
    except Exception:
        return "$0"


def _number(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return "0"


def _pct(value) -> str:
    try:
        return f"{float(value):.1f}%".replace(".", ",")
    except Exception:
        return "0,0%"


def _to_number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace("$", "").replace(" ", "")
    if not text:
        return 0.0
    if "." in text and "," not in text:
        text = text.replace(".", "")
    else:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return 0.0


def _first(row, *names: str) -> str:
    for name in names:
        value = row.get(name, "") if hasattr(row, "get") else ""
        text = str(value or "").strip()
        if text and text.lower() not in {"nan", "none", "nat"}:
            return text
    return ""


def _rut_norm(value: str) -> str:
    return str(value or "").replace(".", "").replace("-", "").strip().lstrip("0")


def _rut_base(value: str) -> str:
    # Los diálogos de detalle, correo y gestiones trabajan con el RUT sin dígito
    # verificador, igual que la tabla de deudores.
    texto = str(value or "").strip().replace(".", "")
    if "-" in texto:
        texto = texto.rsplit("-", 1)[0]
    return texto.strip().lstrip("0")


def _text_norm(value: str) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").strip().lower()


def _priority(days: int) -> str:
    if days >= 14:
        return "critical"
    if days >= 7:
        return "priority"
    return "ok"


PRIORITY_STYLE = {
    "critical": ("#DC2626", "#FEE2E2", "Crítico"),
    "priority": ("#D97706", "#FEF3C7", "Prioritario"),
    "ok": ("#16A34A", "#DCFCE7", "Al día"),
}


def _card(frame: QFrame, radius: int = 12) -> None:
    frame.setStyleSheet(
        f"QFrame#{frame.objectName()} {{background:#FFFFFF; border:1px solid #E8ECF2; border-radius:{radius}px;}}"
    )
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(8)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(0, 0, 0, 13))
    frame.setGraphicsEffect(shadow)


class CommissionCard(QFrame):
    """Acumulado de comisiones de la ejecutiva en la pestaña Mi trabajo."""

    def __init__(self):
        super().__init__()
        self.setObjectName("commissionCard")
        self.setStyleSheet(
            "QFrame#commissionCard{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #065F46,stop:1 #10B981);"
            "border:none;border-radius:14px;} QLabel{border:none;background:transparent;}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 26))
        self.setGraphicsEffect(shadow)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(2)
        kicker = QLabel("MIS COMISIONES ACUMULADAS")
        kicker.setStyleSheet("color:rgba(255,255,255,0.78);font-size:11px;font-weight:600;letter-spacing:1px;")
        self.amount = QLabel("$0")
        self.amount.setStyleSheet("color:#FFFFFF;font-size:26px;font-weight:700;")
        self.detail = QLabel("Sin pagos registrados en el período")
        self.detail.setStyleSheet("color:rgba(255,255,255,0.82);font-size:12px;")
        left.addWidget(kicker)
        left.addWidget(self.amount)
        left.addWidget(self.detail)

        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.setSpacing(4)
        self.rates = QLabel("Sin porcentaje asignado")
        self.rates.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.rates.setWordWrap(True)
        self.rates.setMaximumWidth(360)
        self.rates.setStyleSheet(
            "color:#FFFFFF;background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.30);"
            "border-radius:14px;padding:6px 14px;font-size:12px;"
        )
        self.since = QLabel("")
        self.since.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.since.setStyleSheet("color:rgba(255,255,255,0.72);font-size:11px;")
        right.addWidget(self.rates, 0, Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.since, 0, Qt.AlignmentFlag.AlignRight)

        lay.addLayout(left, 1)
        lay.addLayout(right, 1)

    def set_data(self, amount: str, detail: str, rates: str, since: str) -> None:
        self.amount.setText(amount)
        self.detail.setText(detail)
        self.rates.setText(rates)
        self.since.setText(since)


class MetricCard(QFrame):
    def __init__(self, label: str, color: str = BLUE, progress: bool = False):
        super().__init__()
        self.setObjectName("metricCard")
        _card(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(3)
        self.value = QLabel("0")
        self.value.setStyleSheet(f"color:{color}; font-size:24px; font-weight:700; border:none;")
        self.label = QLabel(label)
        self.label.setStyleSheet(f"color:{SECONDARY}; font-size:12px; font-weight:500; border:none;")
        self.sub = QLabel("")
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet(f"color:{MUTED}; font-size:11px; border:none;")
        lay.addWidget(self.value)
        lay.addWidget(self.label)
        lay.addWidget(self.sub)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:#E2E8F0;border:none;border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:3px;}}"
        )
        self.bar.setVisible(progress)
        lay.addWidget(self.bar)

    def set_data(self, value: str, sub: str, percent: float | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        if percent is not None:
            self.bar.setValue(max(0, min(1000, int(percent * 10))))


class ChannelCard(QToolButton):
    def __init__(self, key: str, icon: str, label: str):
        super().__init__()
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(108)
        self.setText(f"{icon}\n0\n{label}\n$0")
        self.setStyleSheet(self._style())

    def _style(self) -> str:
        return f"""
        QToolButton {{background:#FFFFFF;color:{TEXT};border:1px solid #E8ECF2;border-radius:12px;
            padding:10px 16px;text-align:left;font-size:12px;}}
        QToolButton:hover {{border-color:{BLUE};}}
        QToolButton:checked {{background:#EFF6FF;border:2px solid {BLUE};}}
        """

    def set_data(self, count: int, amount: float, icon: str, label: str) -> None:
        self.setText(f"{icon}\n{_number(count)}\n{label}\n{_money(amount)}")


class FunnelRow(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)
        self.dot = QLabel("●")
        self.dot.setFixedWidth(10)
        self.name = QLabel("—")
        self.name.setStyleSheet(f"color:{TEXT};font-size:12px;")
        self.name.setMinimumWidth(105)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setStyleSheet("QProgressBar{background:#E2E8F0;border:none;border-radius:2px;} QProgressBar::chunk{background:#2563EB;border-radius:2px;}")
        self.count = QLabel("0")
        self.count.setStyleSheet(f"color:{TEXT};font-size:12px;font-weight:700;")
        lay.addWidget(self.dot)
        lay.addWidget(self.name)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.count)

    def set_data(self, name: str, count: int, percent: float, color: str) -> None:
        self.name.setText(name)
        self.count.setText(_number(count))
        self.dot.setStyleSheet(f"color:{color};")
        self.bar.setValue(max(0, min(1000, int(percent * 10))))


class DebtorRow(QWidget):
    def __init__(self, debtor: dict, dashboard: "DashboardWidget"):
        super().__init__()
        self.debtor = debtor
        self.dashboard = dashboard
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.main = QFrame()
        self.main.setObjectName("debtorMain")
        self.main.setCursor(Qt.CursorShape.PointingHandCursor)
        main = QHBoxLayout(self.main)
        main.setContentsMargins(14, 10, 14, 10)
        main.setSpacing(12)
        level = _priority(debtor["dias"])
        color, light, _ = PRIORITY_STYLE[level]
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color};font-size:13px;border:none;")
        identity = QVBoxLayout()
        identity.setSpacing(1)
        name = QLabel(debtor["nombre"] or "Sin nombre")
        name.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;border:none;")
        meta = QLabel(f"{debtor['rut']} · {debtor['estado']}")
        meta.setStyleSheet(f"color:{MUTED};font-size:11px;border:none;")
        reason = QLabel(f"Prioridad {debtor.get('score', 0)} · {debtor.get('score_reason', 'prioridad operativa')}")
        reason.setWordWrap(True)
        reason.setStyleSheet(f"color:{BLUE};font-size:10px;font-weight:500;border:none;")
        identity.addWidget(name)
        identity.addWidget(meta)
        identity.addWidget(reason)
        channels = QHBoxLayout()
        channels.setSpacing(4)
        channel_specs = []
        if debtor["tel"]:
            channel_specs.append(("Tel", "#DCFCE7", "#15803D"))
        if debtor["mail"]:
            channel_specs.append(("Email", "#DBEAFE", "#1D4ED8"))
        if debtor["dir"]:
            channel_specs.append(("Dir", "#FEF9C3", "#854D0E"))
        if not channel_specs:
            channel_specs.append(("Sin contacto", "#FEE2E2", "#DC2626"))
        for text, bg, fg in channel_specs:
            chip = QLabel(text)
            chip.setStyleSheet(f"background:{bg};color:{fg};border:none;border-radius:10px;padding:2px 8px;font-size:11px;font-weight:600;")
            channels.addWidget(chip)
        amount = QLabel(_money(debtor["monto"]))
        amount.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;border:none;")
        badge = QLabel(f"{debtor['dias']}d")
        badge.setStyleSheet(f"background:{light};color:{color};border:none;border-radius:10px;padding:2px 8px;font-size:11px;font-weight:600;")
        main.addWidget(dot)
        main.addLayout(identity, 1)
        main.addLayout(channels)
        main.addWidget(amount)
        main.addWidget(badge)
        self.main.setStyleSheet("QFrame#debtorMain{background:#FFFFFF;border:1px solid #E8ECF2;border-radius:10px;} QFrame#debtorMain:hover{border-color:#CBD5E1;}")
        self.main.mousePressEvent = lambda _event: dashboard.toggle_debtor(self)
        outer.addWidget(self.main)

        # El detalle se construye recién al desplegar la fila: son ~18 widgets
        # que, multiplicados por toda la cola, congelaban el panel al dibujarlo.
        self._outer = outer
        self.detail: QFrame | None = None

    def _build_detail(self) -> None:
        debtor = self.debtor
        dashboard = self.dashboard
        outer = self._outer

        self.detail = QFrame()
        self.detail.setObjectName("debtorDetail")
        self.detail.setStyleSheet("QFrame#debtorDetail{background:#F8FAFC;border:1px solid #DBEAFE;border-top:none;border-bottom-left-radius:10px;border-bottom-right-radius:10px;}")
        detail_lay = QVBoxLayout(self.detail)
        detail_lay.setContentsMargins(14, 12, 14, 12)
        grid = QGridLayout()
        values = [
            ("RUT", debtor["rut"]), ("Último estado", debtor["estado"]),
            ("Teléfono", debtor["telefono"] or "No disponible"), ("Email", debtor["email"] or "No disponible"),
            ("Dirección", debtor["direccion"] or "No disponible"), ("Cartera", debtor["empresa"] or "Sin cartera"),
        ]
        for idx, (label, value) in enumerate(values):
            box = QVBoxLayout()
            box.setSpacing(1)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{MUTED};font-size:11px;border:none;")
            val = QLabel(value)
            val.setWordWrap(True)
            val.setStyleSheet(f"color:{TEXT if value != 'No disponible' else MUTED};font-size:12px;font-weight:500;border:none;")
            box.addWidget(lbl)
            box.addWidget(val)
            grid.addLayout(box, idx // 2, idx % 2)
        detail_lay.addLayout(grid)
        actions = QHBoxLayout()
        for label, available, primary in (
            ("Llamar", debtor["tel"], True), ("Enviar email", debtor["mail"], False), ("Generar carta", debtor["dir"], False)
        ):
            if available:
                btn = QPushButton(label)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(dashboard.action_style(primary))
                if label == "Enviar email":
                    btn.clicked.connect(lambda _checked=False: dashboard.enviar_email(debtor))
                else:
                    btn.clicked.connect(lambda _checked=False, action=label: dashboard.show_action(action, debtor["nombre"]))
                actions.addWidget(btn)
        actions.addStretch(1)
        register = QPushButton("Registrar gestión")
        register.setCursor(Qt.CursorShape.PointingHandCursor)
        register.setStyleSheet(dashboard.action_style(False))
        register.clicked.connect(lambda _checked=False: dashboard.registrar_gestion(debtor))
        actions.addWidget(register)
        detail_lay.addLayout(actions)
        outer.addWidget(self.detail)

    def set_expanded(self, expanded: bool) -> None:
        if expanded and self.detail is None:
            self._build_detail()
        if self.detail is not None:
            self.detail.setVisible(expanded)
        border = BLUE if expanded else "#E8ECF2"
        self.main.setStyleSheet(f"QFrame#debtorMain{{background:#FFFFFF;border:1px solid {border};border-radius:10px;}} QFrame#debtorMain:hover{{border-color:#CBD5E1;}}")


class DashboardWidget(QWidget):
    # Interfaz pública conservada para las conexiones existentes en app.py.
    bd_limpiada = pyqtSignal(list)

    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        self._session = session
        self._empresas_asignadas = obtener_empresas_asignadas_para_session(session)
        self._debtors: list[dict] = []
        self._channel = "todos"
        self._urgency = {"critical": True, "priority": True, "ok": True}
        self._smart_queue = "all"
        self._queue_page = 1
        self._queue_data: list[dict] = []
        self._queue_label = ""
        self._queue_saldo = 0.0
        self._more_button: QPushButton | None = None
        self._open_row: DebtorRow | None = None
        self._worker: DashboardLoadWorker | None = None
        # Segoe UI es el equivalente nativo disponible en Windows cuando Inter
        # no está instalada; evita depender de fuentes o recursos externos.
        self.setStyleSheet('QWidget{font-family:"Segoe UI";}')
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"QScrollArea{{border:none;background:{BG};}}")
        root.addWidget(self.scroll)
        canvas = QWidget()
        canvas.setStyleSheet(f"background:{BG};")
        self.scroll.setWidget(canvas)
        self.content = QVBoxLayout(canvas)
        self.content.setContentsMargins(20, 20, 20, 20)
        self.content.setSpacing(12)
        self._last_refresh = 0.0
        # El timer sólo corre mientras el panel está visible: refrescar en
        # segundo plano bloquea la interfaz aunque el usuario esté en otro módulo.
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.refresh)
        # Debe existir antes de _build_tabs(), que conecta el buscador.
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(self._render_queue)
        self._build_commission()
        self._build_tabs()
        QTimer.singleShot(0, self.refresh)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()
        if self._last_refresh and (time.monotonic() - self._last_refresh) > 60:
            # Se difiere para que el cambio de módulo se pinte antes de bloquear.
            QTimer.singleShot(0, self.refresh)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _build_commission(self) -> None:
        # Sólo la ejecutiva ve su acumulado aquí; el supervisor lo revisa por
        # ejecutiva en la sección "Comisiones por ejecutiva" de Vista general.
        self.commission_card: CommissionCard | None = None
        if not self._is_ejecutivo():
            return
        self.commission_card = CommissionCard()
        self.content.addWidget(self.commission_card)

    def _build_tabs(self) -> None:
        tabs = QHBoxLayout()
        tabs.setSpacing(12)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for idx, text in enumerate(("Cola de trabajo", "Resumen ejecutivo")):
            btn = QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setChecked(idx == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"QToolButton{{background:transparent;color:{SECONDARY};border:none;border-radius:8px;padding:6px 16px;font-size:13px;}} QToolButton:checked{{background:#FFFFFF;color:{TEXT};border:1px solid #E8ECF2;font-weight:600;}}")
            self.tab_group.addButton(btn, idx)
            tabs.addWidget(btn)
        tabs.addStretch(1)
        self.content.addLayout(tabs)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget{background:transparent;border:none;}")
        self.queue_page = QWidget()
        self.summary_page = QWidget()
        self.stack.addWidget(self.queue_page)
        self.stack.addWidget(self.summary_page)
        self.tab_group.idClicked.connect(self.stack.setCurrentIndex)
        self.content.addWidget(self.stack)
        self._build_queue()
        self._build_summary()

    def _build_queue(self) -> None:
        lay = QVBoxLayout(self.queue_page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        activity = QGridLayout()
        activity.setSpacing(10)
        self.work_today = MetricCard("Gestiones hoy", "#7C3AED")
        self.work_critical = MetricCard("Críticos pendientes", "#DC2626")
        self.work_contactable = MetricCard("Contactables", "#16A34A")
        self.work_no_contact = MetricCard("Sin datos de contacto", "#D97706")
        for col, card in enumerate((self.work_today, self.work_critical, self.work_contactable, self.work_no_contact)):
            activity.addWidget(card, 0, col)
        lay.addLayout(activity)

        alerts = QVBoxLayout()
        alerts.setSpacing(8)
        self.alert_critical = QPushButton("Sin alertas críticas")
        self.alert_contact = QPushButton("Sin oportunidades de contacto")
        for button, bg, fg in (
            (self.alert_critical, "#FEE2E2", "#991B1B"),
            (self.alert_contact, "#EFF6FF", "#1D4ED8"),
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:none;border-radius:8px;padding:9px 12px;"
                "font-size:12px;text-align:left;} QPushButton:hover{font-weight:600;}"
            )
            alerts.addWidget(button)
        self.alert_critical.clicked.connect(lambda: self._activate_smart_queue("critical_high"))
        self.alert_contact.clicked.connect(lambda: self._activate_smart_queue("contactable"))
        lay.addLayout(alerts)

        smart_head = QGridLayout()
        smart_head.setHorizontalSpacing(8)
        smart_head.setVerticalSpacing(6)
        smart_label = QLabel("Colas inteligentes")
        smart_label.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;")
        smart_head.addWidget(smart_label, 0, 0, 1, 3)
        self.smart_group = QButtonGroup(self)
        self.smart_group.setExclusive(True)
        self.smart_buttons = {}
        smart_specs = (
            ("all", "Toda la cartera"),
            ("never", "Nunca gestionados"),
            ("critical_high", "Críticos alto saldo"),
            ("contactable", "Contactables hoy"),
            ("no_contact", "Sin contacto"),
            ("partial", "Pagos parciales"),
        )
        for index, (key, label) in enumerate(smart_specs):
            button = QToolButton()
            button.queue_key = key
            button.base_label = label
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"QToolButton{{background:#FFFFFF;color:{SECONDARY};border:1px solid #E2E8F0;border-radius:14px;"
                f"padding:5px 11px;font-size:11px;}} QToolButton:hover{{border-color:{BLUE};}} "
                f"QToolButton:checked{{background:#DBEAFE;color:#1D4ED8;border-color:#93C5FD;font-weight:600;}}"
            )
            self.smart_group.addButton(button)
            self.smart_buttons[key] = button
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            smart_head.addWidget(button, 1 + index // 3, index % 3)
        self.smart_group.buttonClicked.connect(self._smart_queue_changed)
        lay.addLayout(smart_head)

        grid = QGridLayout()
        grid.setSpacing(10)
        specs = [("todos", "◉", "Todos pendientes"), ("tel", "☎", "Con teléfono"), ("mail", "✉", "Con email"), ("dir", "⌖", "Con dirección")]
        self.channel_group = QButtonGroup(self)
        self.channel_group.setExclusive(True)
        self.channel_cards = {}
        for col, (key, icon, label) in enumerate(specs):
            card = ChannelCard(key, icon, label)
            card.setChecked(col == 0)
            self.channel_group.addButton(card)
            self.channel_cards[key] = card
            grid.addWidget(card, 0, col)
        self.channel_group.buttonClicked.connect(self._channel_changed)
        lay.addLayout(grid)

        filters = QFrame()
        filters.setObjectName("workFilters")
        filters.setStyleSheet("QFrame#workFilters{background:#FFFFFF;border:1px solid #E8ECF2;border-radius:10px;}")
        filters_lay = QGridLayout(filters)
        filters_lay.setContentsMargins(12, 10, 12, 10)
        filters_lay.setHorizontalSpacing(8)
        filters_lay.setVerticalSpacing(6)
        filters_title = QLabel("Filtros de trabajo")
        filters_title.setStyleSheet(f"color:{TEXT};font-size:12px;font-weight:600;border:none;")
        filters_lay.addWidget(filters_title, 0, 0)
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("Buscar por nombre, RUT o cartera…")
        self.search_filter.setClearButtonEnabled(True)
        self.search_filter.setStyleSheet("QLineEdit{background:#F8FAFC;color:#1E293B;border:1px solid #CBD5E1;border-radius:7px;padding:6px 9px;font-size:11px;}")
        filters_lay.addWidget(self.search_filter, 0, 1, 1, 3)

        def add_combo(slot: int, title: str) -> QComboBox:
            box = QVBoxLayout()
            box.setSpacing(2)
            label = QLabel(title)
            label.setStyleSheet(f"color:{MUTED};font-size:10px;border:none;")
            combo = QComboBox()
            combo.setMinimumWidth(130)
            combo.setStyleSheet("QComboBox{background:#F8FAFC;color:#334155;border:1px solid #CBD5E1;border-radius:7px;padding:5px 8px;font-size:11px;}")
            box.addWidget(label)
            box.addWidget(combo)
            filters_lay.addLayout(box, 1 + slot // 3, slot % 3)
            return combo

        self.company_filter = add_combo(0, "Cartera")
        self.state_filter = add_combo(1, "Estado")
        self.age_filter = add_combo(2, "Antigüedad")
        self.balance_filter = add_combo(3, "Saldo")
        self.contact_filter = add_combo(4, "Contactabilidad")
        self.age_filter.addItem("Todas", "all")
        self.age_filter.addItem("Nunca gestionados", "never")
        self.age_filter.addItem("0 a 6 días", "0_6")
        self.age_filter.addItem("7 a 13 días", "7_13")
        self.age_filter.addItem("14 a 29 días", "14_29")
        self.age_filter.addItem("30 días o más", "30_plus")
        self.balance_filter.addItem("Todos", "all")
        self.balance_filter.addItem("Menos de $500.000", "low")
        self.balance_filter.addItem("$500.000 a $2.000.000", "medium")
        self.balance_filter.addItem("Más de $2.000.000", "high")
        self.contact_filter.addItem("Todos", "all")
        self.contact_filter.addItem("Algún canal disponible", "any")
        self.contact_filter.addItem("Teléfono y email", "digital")
        self.contact_filter.addItem("Sin datos de contacto", "none")
        self.btn_clear_filters = QPushButton("Limpiar filtros")
        self.btn_clear_filters.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_filters.setStyleSheet(self.action_style(False))
        filters_lay.addWidget(self.btn_clear_filters, 2, 2, Qt.AlignmentFlag.AlignBottom)
        # Sin debounce, cada tecla reconstruye la cola completa. La lambda evita
        # que textChanged pase el texto como intervalo del timer.
        self.search_filter.textChanged.connect(lambda _text: self._search_debounce.start())
        for combo in (self.company_filter, self.state_filter, self.age_filter, self.balance_filter, self.contact_filter):
            combo.currentIndexChanged.connect(self._render_queue)
        self.btn_clear_filters.clicked.connect(self._clear_filters)
        lay.addWidget(filters)

        head = QHBoxLayout()
        title = QLabel("Cola priorizada")
        title.setStyleSheet(f"color:{TEXT};font-size:14px;font-weight:600;")
        self.filter_label = QLabel("— todos los casos")
        self.filter_label.setStyleSheet(f"color:{MUTED};font-size:12px;")
        head.addWidget(title)
        head.addWidget(self.filter_label)
        head.addStretch(1)
        self.urgency_buttons = {}
        for key, label, color in (("critical", "Críticos", "#DC2626"), ("priority", "Prioritarios", "#D97706"), ("ok", "Al día", "#16A34A")):
            btn = QToolButton()
            btn.setText(f"●  {label}")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"QToolButton{{color:{MUTED};background:transparent;border:1px solid #E8ECF2;border-radius:14px;padding:4px 12px;font-size:12px;}} QToolButton:checked{{color:{color};background:#F8FAFC;border-color:#CBD5E1;}}")
            btn.toggled.connect(lambda checked, k=key: self._urgency_changed(k, checked))
            self.urgency_buttons[key] = btn
            head.addWidget(btn)
        lay.addLayout(head)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        lay.addWidget(self.rows_host)
        lay.addStretch(1)

    def _build_summary(self) -> None:
        lay = QVBoxLayout(self.summary_page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        metrics = QGridLayout()
        metrics.setSpacing(10)
        self.kpi_total = MetricCard("Cartera total", BLUE)
        self.kpi_saldo = MetricCard("Saldo actual", "#DC2626")
        self.kpi_coverage = MetricCard("Cobertura de gestión", "#16A34A", True)
        self.kpi_ratio = MetricCard("Ratio pagos/copago", "#D97706", True)
        for col, widget in enumerate((self.kpi_total, self.kpi_saldo, self.kpi_coverage, self.kpi_ratio)):
            metrics.addWidget(widget, 0, col)
        lay.addLayout(metrics)
        lower = QHBoxLayout()
        lower.setSpacing(10)
        self.funnel_card = QFrame()
        self.funnel_card.setObjectName("funnelCard")
        _card(self.funnel_card)
        funnel = QVBoxLayout(self.funnel_card)
        funnel.setContentsMargins(16, 16, 16, 16)
        ft = QLabel("Embudo de cartera")
        ft.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;border:none;")
        fs = QLabel("Distribución actual por estado")
        fs.setStyleSheet(f"color:{MUTED};font-size:11px;border:none;")
        funnel.addWidget(ft)
        funnel.addWidget(fs)
        self.funnel_rows = [FunnelRow() for _ in range(5)]
        for row in self.funnel_rows:
            funnel.addWidget(row)
        lower.addWidget(self.funnel_card, 1)
        focus_card = QFrame()
        focus_card.setObjectName("focusCard")
        _card(focus_card)
        focus_lay = QVBoxLayout(focus_card)
        focus_lay.setContentsMargins(16, 16, 16, 16)
        focus_title = QLabel("Foco del día")
        focus_title.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;border:none;")
        self.warning = QLabel("⚠  Esperando datos para definir el foco operativo.")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("background:#FEF3C7;color:#92400E;border:none;border-radius:8px;padding:10px 14px;font-size:13px;")
        self.info = QLabel("💡  Los canales disponibles aparecerán al actualizar.")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("background:#EFF6FF;color:#1D4ED8;border:none;border-radius:8px;padding:10px 14px;font-size:13px;")
        focus_lay.addWidget(focus_title)
        focus_lay.addWidget(self.warning)
        focus_lay.addWidget(self.info)
        focus_lay.addStretch(1)
        lower.addWidget(focus_card, 1)
        lay.addLayout(lower)
        if self._can_view_team():
            self.team_card = QFrame()
            self.team_card.setObjectName("teamCard")
            _card(self.team_card)
            team = QHBoxLayout(self.team_card)
            team.setContentsMargins(16, 12, 16, 12)
            label = QLabel("Productividad del equipo")
            label.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;border:none;")
            self.team_today = QLabel("Conexiones hoy: 0")
            self.team_month = QLabel("Conexiones del mes: 0")
            self.team_users = QLabel("Ejecutivas activas: 0")
            for item in (self.team_today, self.team_month, self.team_users):
                item.setStyleSheet(f"color:{SECONDARY};font-size:12px;border:none;")
            team.addWidget(label)
            team.addStretch(1)
            team.addWidget(self.team_today)
            team.addWidget(self.team_users)
            team.addWidget(self.team_month)
            lay.addWidget(self.team_card)
        lay.addStretch(1)

    def _can_view_team(self) -> bool:
        return bool(self._session and getattr(self._session, "role", "") in {"admin", "supervisor"})

    def _is_ejecutivo(self) -> bool:
        return bool(self._session and getattr(self._session, "role", "") == "ejecutivo")

    def _uses_backend(self) -> bool:
        return bool(self._session and getattr(self._session, "auth_source", "") == "backend" and getattr(self._session, "access_token", ""))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {getattr(self._session, 'access_token', '')}"}

    def _visible_companies(self) -> list[str]:
        if session_tiene_restriccion_por_cartera(self._session):
            return list(self._empresas_asignadas)
        return []

    def _load_backend(self) -> tuple[list[dict], dict]:
        base = get_backend_base_url()
        companies = self._visible_companies()
        company_param = ",".join(companies)
        summary_resp = requests.get(f"{base}/dashboard/summary", params={"empresas": company_param}, headers=self._headers(), timeout=15)
        summary_resp.raise_for_status()
        summary = summary_resp.json() or {}
        all_items = []
        targets = companies or [""]
        for company in targets:
            resp = requests.get(f"{base}/deudores", params={"empresa": company, "limit": 5000}, headers=self._headers(), timeout=20)
            resp.raise_for_status()
            all_items.extend((resp.json() or {}).get("items", []) or [])
        email_map = {}
        for company in targets:
            resp = requests.get(f"{base}/deudores/destinatarios", params={"empresa": company, "limit": 50000}, headers=self._headers(), timeout=20)
            if resp.ok:
                for item in resp.json() or []:
                    email_map[(_rut_norm(item.get("rut_afiliado", "")), item.get("empresa", ""))] = item.get("mail_afiliado", "")
        debtors = []
        for item in all_items:
            rut = item.get("rut_completo") or item.get("rut_afiliado", "")
            email = email_map.get((_rut_norm(rut), item.get("empresa", "")), "") or item.get("bn", "")
            debtors.append(self._make_debtor(item, email=email, backend=True))
        return debtors, summary

    def _load_local(self) -> tuple[list[dict], dict]:
        companies = self._visible_companies()
        if session_tiene_restriccion_por_cartera(self._session) and not companies:
            return [], {}
        df = cargar_para_envio()
        if companies and not df.empty and "_empresa" in df.columns:
            df = df[df["_empresa"].astype(str).isin(companies)].copy()
        legacy = _LegacyDashboardWidget.__new__(_LegacyDashboardWidget)
        legacy._session = self._session
        legacy._empresas_asignadas = companies
        gestions = legacy._load_gestiones_df()
        latest = {}
        if not gestions.empty:
            gestions["_rut_norm"] = gestions["Rut_Afiliado"].apply(_rut_norm)
            gestions["_date"] = pd.to_datetime(gestions["Fecha_gestion"], dayfirst=True, errors="coerce")
            gestions = gestions.sort_values(["_rut_norm", "_date", "id"], ascending=[True, False, False]).drop_duplicates("_rut_norm")
            latest = {row["_rut_norm"]: row for _, row in gestions.iterrows()}
        debtors = [self._make_debtor(row, latest.get(_rut_norm(_first(row, "Rut_Afiliado")))) for _, row in df.iterrows()]
        total = len(debtors)
        copago = sum(_to_number(row.get("Copago", 0)) for _, row in df.iterrows()) if not df.empty else 0
        pagos = sum(_to_number(row.get("Total_Pagos", 0)) for _, row in df.iterrows()) if not df.empty else 0
        saldo = sum(d["monto"] for d in debtors)
        states = {}
        for d in debtors:
            states[d["estado"]] = states.get(d["estado"], 0) + 1
        pending = sum(count for state, count in states.items() if _text_norm(state) == "sin gestion")
        managed = max(total - pending, 0)
        coverage = managed / total * 100 if total else 0
        visible_ruts = {_rut_norm(d["rut"]) for d in debtors}
        gestiones_hoy = 0
        if not gestions.empty:
            today = pd.Timestamp.now().normalize()
            today_rows = gestions[
                gestions["_rut_norm"].isin(visible_ruts)
                & (gestions["_date"].dt.normalize() == today)
            ]
            gestiones_hoy = int(today_rows["_rut_norm"].nunique())
        summary = {"total_deudores": total, "copago_total": copago, "total_pagos_total": pagos, "saldo_total": saldo, "sin_gestion_total": pending, "gestionados_total": managed, "cobertura_pct": coverage, "pagos_vs_copago_pct": pagos / copago * 100 if copago else 0, "estado_counts": states, "gestiones_hoy": gestiones_hoy}
        health, focus = legacy._build_global_status(total, pending, 0, coverage)
        summary["health_label"], summary["focus_text"] = health, focus
        return debtors, summary

    def _make_debtor(self, row, latest=None, email: str = "", backend: bool = False) -> dict:
        getter = lambda *names: _first(row, *names)
        rut = getter("rut_completo", "Rut_Afiliado", "rut_afiliado")
        state = getter("estado_deudor", "Estado_deudor") or ESTADO_DEUDOR_DEFAULT
        latest_date = None
        if latest is not None and hasattr(latest, "get"):
            latest_date = latest.get("_date")
            state = _first(latest, "Estado") or state
        never_managed = latest_date is None and _text_norm(state) == "sin gestion"
        days = 30 if never_managed else 0
        if latest_date is not None and not pd.isna(latest_date):
            days = max(0, (pd.Timestamp.now().normalize() - pd.Timestamp(latest_date).normalize()).days)
        phone = getter("telefono_movil_afiliado", "telefono_fijo_afiliado", "Telefono Empleador", "telefono_empleador")
        mail = email or getter("mail_afiliado", "BN", "bn")
        address = getter("direccion", "Direccion", "Dirección", "Domicilio", "domicilio")
        debtor = {"rut": rut, "nombre": getter("nombre_afiliado", "Nombre_Afiliado"), "estado": state, "dias": days,
            "monto": _to_number(row.get("saldo_actual", row.get("Saldo_Actual", 0))), "copago": _to_number(row.get("copago", row.get("Copago", 0))),
            "pagos": _to_number(row.get("total_pagos", row.get("Total_Pagos", 0))), "tel": bool(phone), "mail": "@" in mail,
            "dir": bool(address), "telefono": phone, "email": mail, "direccion": address, "empresa": getter("empresa", "_empresa"),
            "never": never_managed, "last_type": _first(latest, "tipo_gestion") if latest is not None else ""}
        debtor["rut_base"] = _rut_base(rut)
        # Fila original: la reutilizan los diálogos de correo y gestión de la cola.
        try:
            debtor["raw"] = dict(row)
        except Exception:
            debtor["raw"] = {}
        debtor["backend"] = backend
        debtor["partial"] = debtor["pagos"] > 0 and debtor["monto"] > 0
        debtor["score"], debtor["score_reason"] = self._score_debtor(debtor)
        return debtor

    @staticmethod
    def _score_debtor(debtor: dict) -> tuple[int, str]:
        factors: list[tuple[int, str]] = []
        days = int(debtor.get("dias", 0) or 0)
        if days >= 30:
            factors.append((30, "30+ días sin gestión"))
        elif days >= 14:
            factors.append((24, "14+ días sin gestión"))
        elif days >= 7:
            factors.append((15, "7+ días sin gestión"))
        elif days > 0:
            factors.append((5, "gestión reciente"))

        amount = float(debtor.get("monto", 0) or 0)
        if amount >= 5_000_000:
            factors.append((25, "saldo muy alto"))
        elif amount > 2_000_000:
            factors.append((20, "saldo alto"))
        elif amount >= 500_000:
            factors.append((12, "saldo relevante"))
        elif amount > 0:
            factors.append((5, "saldo pendiente"))

        if debtor.get("never"):
            factors.append((15, "nunca gestionado"))
        if _text_norm(debtor.get("estado", "")) == "sin gestion":
            factors.append((15, "estado sin gestión"))
        if debtor.get("tel") or debtor.get("mail") or debtor.get("dir"):
            factors.append((10, "canal disponible"))
        if debtor.get("partial"):
            factors.append((5, "pago parcial pendiente"))

        score = min(100, sum(points for points, _ in factors))
        reasons = [label for _, label in sorted(factors, reverse=True)[:3]]
        return score, " · ".join(reasons) if reasons else "sin factores adicionales"

    def refresh(self) -> None:
        # La carga ocurre en un hilo aparte; el hilo de la interfaz sólo pinta
        # el resultado cuando llega.
        if self._worker is not None and self._worker.isRunning():
            return
        self._last_refresh = time.monotonic()
        self._worker = DashboardLoadWorker(self._load_data, self._load_extras, parent=self)
        self._worker.finished_ok.connect(self._on_data_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.start()

    def _load_data(self) -> tuple[list[dict], dict]:
        """Corre en el hilo del worker: sólo red y cálculo, nada de widgets."""
        if session_tiene_restriccion_por_cartera(self._session):
            self._empresas_asignadas = obtener_empresas_asignadas_para_session(self._session)
        return self._load_backend() if self._uses_backend() else self._load_local()

    def _load_extras(self) -> dict:
        """Corre en el hilo del worker: datos secundarios del panel."""
        return {"comision": self._load_commission(), "equipo": self._load_team()}

    def _load_commission(self) -> dict | None:
        if getattr(self, "commission_card", None) is None:
            return None
        fila, err = obtener_comision_propia(self._session)
        if err:
            return {"error": err}
        tasas, _tasas_err = obtener_tasas(self._session, usar_cache=True)
        return {"fila": fila, "tasas": tasas}

    def _on_data_loaded(self, debtors, summary, extras) -> None:
        try:
            self._debtors = debtors
            self._populate_filter_options()
            self._apply_summary(summary)
            self._render_channels()
            self._render_queue()
        except Exception as exc:
            self.warning.setText(f"⚠  No fue posible actualizar el dashboard: {exc}")
        extras = extras or {}
        self._apply_team(extras.get("equipo"))
        self._apply_commission(extras.get("comision"))

    def _on_load_failed(self, mensaje: str) -> None:
        self.warning.setText(f"⚠  No fue posible actualizar el dashboard: {mensaje}")

    def _on_worker_done(self) -> None:
        self._worker = None

    def refrescar(self) -> None:
        self.refresh()

    def _apply_summary(self, data: dict) -> None:
        total = int(data.get("total_deudores", len(self._debtors)) or 0)
        managed = int(data.get("gestionados_total", 0) or 0)
        pending = int(data.get("sin_gestion_total", max(total - managed, 0)) or 0)
        copago = float(data.get("copago_total", 0) or 0)
        payments = float(data.get("total_pagos_total", 0) or 0)
        balance = float(data.get("saldo_total", 0) or 0)
        coverage = float(data.get("cobertura_pct", (managed / total * 100 if total else 0)) or 0)
        ratio = float(data.get("pagos_vs_copago_pct", (payments / copago * 100 if copago else 0)) or 0)
        focus = str(data.get("focus_text", "Carga una cartera para activar el panel operativo."))
        self.kpi_total.set_data(_number(total), f"{_number(managed)} gestionados · {_number(pending)} pendientes")
        self.kpi_saldo.set_data(_money(balance), f"Copago {_money(copago)} · Pagos {_money(payments)}")
        self.kpi_coverage.set_data(_pct(coverage), f"{_number(managed)} de {_number(total)} deudores", coverage)
        self.kpi_ratio.set_data(_pct(ratio), f"{_money(payments)} de {_money(copago)}", ratio)
        pending_debtors = [d for d in self._debtors if d["monto"] > 0]
        critical = [d for d in pending_debtors if d["dias"] >= 14]
        contactable = [d for d in pending_debtors if d["tel"] or d["mail"] or d["dir"]]
        no_contact = [d for d in pending_debtors if not (d["tel"] or d["mail"] or d["dir"])]
        high_critical = [d for d in critical if d["monto"] > 2_000_000]
        phone_count = sum(1 for d in pending_debtors if d["tel"])
        mail_count = sum(1 for d in pending_debtors if d["mail"])
        self.work_today.set_data(_number(data.get("gestiones_hoy", 0)), "Casos gestionados en las carteras visibles")
        self.work_critical.set_data(_number(len(critical)), f"Saldo asociado {_money(sum(d['monto'] for d in critical))}")
        self.work_contactable.set_data(_number(len(contactable)), f"{_number(phone_count)} con teléfono · {_number(mail_count)} con email")
        self.work_no_contact.set_data(_number(len(no_contact)), f"Saldo por enriquecer {_money(sum(d['monto'] for d in no_contact))}")
        self.alert_critical.setText(
            f"⚠  {_number(len(high_critical))} críticos de alto saldo · {_money(sum(d['monto'] for d in high_critical))} — ver cola"
        )
        self.alert_contact.setText(
            f"✉  {_number(mail_count)} con email · ☎ {_number(phone_count)} con teléfono — priorizar contactos"
        )
        smart_counts = {
            "all": len(pending_debtors),
            "never": sum(1 for d in pending_debtors if d.get("never")),
            "critical_high": len(high_critical),
            "contactable": len(contactable),
            "no_contact": len(no_contact),
            "partial": sum(1 for d in pending_debtors if d.get("partial")),
        }
        for key, button in self.smart_buttons.items():
            button.setText(f"{button.base_label}  ·  {_number(smart_counts[key])}")
        self.warning.setText(f"⚠  {focus}")
        self.info.setText(f"💡  {_number(phone_count)} deudores tienen teléfono disponible — prioriza llamadas hoy.")
        states = data.get("estado_counts", {}) or {}
        top = sorted(states.items(), key=lambda item: item[1], reverse=True)[:5]
        colors = [BLUE, "#16A34A", "#DC2626", "#D97706", MUTED]
        for idx, row in enumerate(self.funnel_rows):
            if idx < len(top):
                name, count = top[idx]
                row.show()
                row.set_data(str(name), int(count), float(count) / total * 100 if total else 0, colors[idx])
            else:
                row.hide()

    def _populate_filter_options(self) -> None:
        def populate(combo: QComboBox, first_label: str, values: list[str]) -> None:
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first_label, "all")
            for value in values:
                combo.addItem(value, value)
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        pending = [d for d in self._debtors if d["monto"] > 0]
        companies = sorted({d["empresa"] for d in pending if d["empresa"]}, key=_text_norm)
        states = sorted({d["estado"] for d in pending if d["estado"]}, key=_text_norm)
        populate(self.company_filter, "Todas las carteras", companies)
        populate(self.state_filter, "Todos los estados", states)

    def _render_channels(self) -> None:
        specs = {"todos": ("◉", "Todos pendientes"), "tel": ("☎", "Con teléfono"), "mail": ("✉", "Con email"), "dir": ("⌖", "Con dirección")}
        for key, card in self.channel_cards.items():
            pending = [d for d in self._debtors if d["monto"] > 0]
            subset = pending if key == "todos" else [d for d in pending if d[key]]
            icon, label = specs[key]
            card.set_data(len(subset), sum(d["monto"] for d in subset), icon, label)

    def _channel_changed(self, button: ChannelCard) -> None:
        self._channel = button.key
        self._render_queue()

    def _smart_queue_changed(self, button: QToolButton) -> None:
        self._smart_queue = getattr(button, "queue_key", "all")
        self._render_queue()

    def _activate_smart_queue(self, key: str) -> None:
        self._clear_filters(render=False)
        self._smart_queue = key
        button = self.smart_buttons.get(key)
        if button:
            button.setChecked(True)
        self.stack.setCurrentIndex(0)
        self.tab_group.button(0).setChecked(True)
        self._render_queue()

    def _clear_filters(self, _checked: bool = False, *, render: bool = True) -> None:
        self.search_filter.blockSignals(True)
        self.search_filter.clear()
        self.search_filter.blockSignals(False)
        for combo in (self.company_filter, self.state_filter, self.age_filter, self.balance_filter, self.contact_filter):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._channel = "todos"
        self.channel_cards["todos"].setChecked(True)
        self._smart_queue = "all"
        self.smart_buttons["all"].setChecked(True)
        for key, button in self.urgency_buttons.items():
            button.blockSignals(True)
            button.setChecked(True)
            button.blockSignals(False)
            self._urgency[key] = True
        if render:
            self._render_queue()

    def _urgency_changed(self, key: str, checked: bool) -> None:
        self._urgency[key] = checked
        self._render_queue()

    def _render_queue(self, *_args) -> None:
        self._queue_page = 1
        self._open_row = None
        self._more_button = None
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        data = [d for d in self._debtors if d["monto"] > 0]

        if self._smart_queue == "never":
            data = [d for d in data if d.get("never")]
        elif self._smart_queue == "critical_high":
            data = [d for d in data if d["dias"] >= 14 and d["monto"] > 2_000_000]
        elif self._smart_queue == "contactable":
            data = [d for d in data if d["tel"] or d["mail"] or d["dir"]]
        elif self._smart_queue == "no_contact":
            data = [d for d in data if not (d["tel"] or d["mail"] or d["dir"])]
        elif self._smart_queue == "partial":
            data = [d for d in data if d.get("partial")]

        if self._channel != "todos":
            data = [d for d in data if d[self._channel]]
        data = [d for d in data if self._urgency[_priority(d["dias"])]]

        search = _text_norm(self.search_filter.text())
        if search:
            data = [
                d for d in data
                if search in _text_norm(" ".join((d["nombre"], d["rut"], d["empresa"], d["estado"])))
            ]
        company = self.company_filter.currentData()
        if company and company != "all":
            data = [d for d in data if d["empresa"] == company]
        state = self.state_filter.currentData()
        if state and state != "all":
            data = [d for d in data if d["estado"] == state]
        age = self.age_filter.currentData()
        if age == "never":
            data = [d for d in data if d.get("never")]
        elif age == "0_6":
            data = [d for d in data if 0 <= d["dias"] < 7]
        elif age == "7_13":
            data = [d for d in data if 7 <= d["dias"] < 14]
        elif age == "14_29":
            data = [d for d in data if 14 <= d["dias"] < 30]
        elif age == "30_plus":
            data = [d for d in data if d["dias"] >= 30]
        balance = self.balance_filter.currentData()
        if balance == "low":
            data = [d for d in data if d["monto"] < 500_000]
        elif balance == "medium":
            data = [d for d in data if 500_000 <= d["monto"] <= 2_000_000]
        elif balance == "high":
            data = [d for d in data if d["monto"] > 2_000_000]
        contact = self.contact_filter.currentData()
        if contact == "any":
            data = [d for d in data if d["tel"] or d["mail"] or d["dir"]]
        elif contact == "digital":
            data = [d for d in data if d["tel"] and d["mail"]]
        elif contact == "none":
            data = [d for d in data if not (d["tel"] or d["mail"] or d["dir"])]

        data = sorted(data, key=lambda d: (-d.get("score", 0), -d["monto"], -d["dias"]))
        labels = {"todos": "todos los casos", "tel": "con teléfono", "mail": "con email", "dir": "con dirección"}
        queue_labels = {
            "all": labels[self._channel], "never": "nunca gestionados", "critical_high": "críticos de alto saldo",
            "contactable": "contactables hoy", "no_contact": "sin datos de contacto", "partial": "con pagos parciales",
        }
        self._queue_data = data
        self._queue_label = queue_labels[self._smart_queue]
        self._queue_saldo = sum(d["monto"] for d in data)

        if not data:
            self.filter_label.setText(f"— {self._queue_label} · 0 resultados")
            empty = QLabel("No hay casos con los filtros seleccionados.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color:{MUTED};font-size:13px;padding:32px;")
            self.rows_layout.addWidget(empty)
            return

        self._append_queue_rows(0, self._queue_page * QUEUE_PAGE_SIZE)

    def _append_queue_rows(self, desde: int, hasta: int) -> None:
        """Agrega la tanda [desde, hasta) sin rehacer las filas ya dibujadas."""
        data = self._queue_data
        if self._more_button is not None:
            self.rows_layout.removeWidget(self._more_button)
            self._more_button.deleteLater()
            self._more_button = None

        for debtor in data[desde:hasta]:
            self.rows_layout.addWidget(DebtorRow(debtor, self))

        mostrados = min(hasta, len(data))
        restantes = len(data) - mostrados
        etiqueta = f"{_number(mostrados)} de {_number(len(data))}" if restantes else _number(len(data))
        self.filter_label.setText(
            f"— {self._queue_label} · {etiqueta} resultados · {_money(self._queue_saldo)} de saldo"
        )

        if restantes > 0:
            self._more_button = QPushButton(
                f"Mostrar {_number(min(QUEUE_PAGE_SIZE, restantes))} casos más"
                f"  ·  quedan {_number(restantes)} por revisar"
            )
            self._more_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._more_button.setStyleSheet(
                f"QPushButton{{background:#FFFFFF;color:{BLUE};border:1px dashed #93C5FD;border-radius:10px;"
                "padding:11px 16px;font-size:12px;font-weight:600;} QPushButton:hover{background:#EFF6FF;}"
            )
            self._more_button.clicked.connect(self._show_more_queue)
            self.rows_layout.addWidget(self._more_button)

    def _show_more_queue(self) -> None:
        desde = self._queue_page * QUEUE_PAGE_SIZE
        self._queue_page += 1
        self._append_queue_rows(desde, self._queue_page * QUEUE_PAGE_SIZE)

    def toggle_debtor(self, row: DebtorRow) -> None:
        if self._open_row is row:
            row.set_expanded(False)
            self._open_row = None
            return
        if self._open_row:
            self._open_row.set_expanded(False)
        self._open_row = row
        row.set_expanded(True)

    @staticmethod
    def action_style(primary: bool) -> str:
        if primary:
            return "QPushButton{background:#2563EB;color:#FFFFFF;border:none;border-radius:6px;padding:5px 14px;font-size:12px;} QPushButton:hover{background:#1D4ED8;}"
        return f"QPushButton{{background:#FFFFFF;color:{TEXT};border:1px solid #CBD5E1;border-radius:6px;padding:5px 14px;font-size:12px;}} QPushButton:hover{{background:#F8FAFC;}}"

    def show_action(self, action: str, name: str) -> None:
        QMessageBox.information(self, action, f"{action}: {name or 'deudor sin nombre'}")

    def _datos_para_dialogo(self, debtor: dict) -> tuple[pd.DataFrame, dict] | None:
        rut = debtor.get("rut_base") or _rut_base(debtor.get("rut", ""))
        empresa = str(debtor.get("empresa", "") or "").strip()
        try:
            df_detalle, resumen = cargar_detalle_deudor_para_dialogos(self._session, rut=rut, empresa=empresa)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Sin detalle",
                f"No fue posible obtener el detalle del deudor para preparar el correo.\n\n{exc}",
            )
            return None

        fila = {} if debtor.get("backend") else dict(debtor.get("raw") or {})
        fila.update(resumen)
        if not str(fila.get("_empresa", "")).strip() and empresa:
            fila["_empresa"] = empresa
        if "@" in str(debtor.get("email", "")) and "@" not in str(fila.get("mail_afiliado", "")):
            fila["mail_afiliado"] = debtor["email"]
        if not str(fila.get("Nombre_Afiliado", "")).strip() and debtor.get("nombre"):
            fila["Nombre_Afiliado"] = debtor["nombre"]
        return df_detalle, fila

    def enviar_email(self, debtor: dict) -> None:
        datos = self._datos_para_dialogo(debtor)
        if datos is None:
            return
        df_detalle, fila = datos
        dlg = CorreoDeudorDialog(
            df_detalle,
            debtor.get("rut_base") or _rut_base(debtor.get("rut", "")),
            fila_resumen=fila,
            parent=self,
            session=self._session,
        )
        dlg.exec()
        self.refresh()

    def registrar_gestion(self, debtor: dict) -> None:
        dlg = AgregarGestionDialog(
            rut=debtor.get("rut_base") or _rut_base(debtor.get("rut", "")),
            nombre=debtor.get("nombre", "") or debtor.get("rut", ""),
            session=self._session,
            empresa=str(debtor.get("empresa", "") or "").strip(),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _apply_commission(self, comision: dict | None) -> None:
        if getattr(self, "commission_card", None) is None or not comision:
            return
        err = comision.get("error", "")
        if err:
            self.commission_card.set_data(
                "$0", f"No fue posible obtener las comisiones: {err}", "Sin porcentaje asignado", ""
            )
            return

        fila = comision.get("fila") or {}
        tasas = comision.get("tasas") or {}
        pagos = int(fila.get("pagos", 0) or 0)
        recaudado = int(fila.get("monto_pagado_clp", 0) or 0)
        detalle = (
            f"{_number(pagos)} pago{'s' if pagos != 1 else ''} registrado{'s' if pagos != 1 else ''}"
            f" · {_money(recaudado)} recaudado"
            if pagos
            else "Aún no registras pagos en este período"
        )

        tasas_norm = {_text_norm(empresa): porcentaje for empresa, porcentaje in tasas.items()}
        empresas = self._empresas_asignadas or sorted(tasas, key=_text_norm)
        partes = [f"{empresa}: {_pct(tasas_norm.get(_text_norm(empresa), 0))}" for empresa in empresas]
        rates = " · ".join(partes) if partes else "Sin porcentaje asignado"

        desde = str(fila.get("desde", "") or "")[:10]
        if len(desde) == 10:
            desde = f"{desde[8:10]}/{desde[5:7]}/{desde[0:4]}"
        since = f"Acumulado desde el último corte del {desde}" if desde else "Acumulado histórico"
        self.commission_card.set_data(_money(fila.get("comision_clp", 0)), detalle, rates, since)

    def _load_team(self):
        """Corre en el hilo del worker: devuelve (hoy, mes) o None."""
        if not self._can_view_team():
            return None
        try:
            if self._uses_backend():
                legacy = _LegacyDashboardWidget.__new__(_LegacyDashboardWidget)
                legacy._session = self._session
                return legacy._backend_session_history()
            now = datetime.now()
            return obtener_conexiones_hoy(role="ejecutivo"), obtener_conexiones_mes(now.year, now.month, role="ejecutivo")
        except Exception:
            return None

    def _apply_team(self, equipo) -> None:
        if not self._can_view_team() or not equipo:
            return
        try:
            today, month = equipo
            active = today["username"].nunique() if not today.empty and "username" in today.columns else 0
            self.team_today.setText(f"Conexiones hoy: {_number(len(today))}")
            self.team_users.setText(f"Ejecutivas activas: {_number(active)}")
            self.team_month.setText(f"Conexiones del mes: {_number(len(month))}")
        except Exception:
            pass
