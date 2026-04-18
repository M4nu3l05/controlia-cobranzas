from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import pandas as pd
import requests
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGridLayout,
    QComboBox,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from auth.session_history_db import (
    obtener_conexiones_hoy,
    obtener_conexiones_mes,
    preparar_reporte_excel,
)
from auth.auth_service import get_backend_base_url
from core.excel_export import write_excel_report
from core.paths import get_data_dir
from deudores.database import EMPRESAS, cargar_empresas, cargar_todas, stats_por_empresa, stats_por_empresas
from admin_carteras.service import obtener_empresas_asignadas_para_session, session_tiene_restriccion_por_cartera
from deudores.gestiones_db import (
    ESTADO_DEUDOR_DEFAULT,
    TABLA as TABLA_GESTIONES,
    obtener_estados_deudor_por_rut,
)


EMPRESA_CONFIG = {
    "Colmena": {"bg": "#eff6ff", "border": "#bfdbfe", "txt": "#1d4ed8", "icono": "🔵"},
    "Consalud": {"bg": "#ecfdf5", "border": "#a7f3d0", "txt": "#047857", "icono": "🟢"},
    "Cruz Blanca": {"bg": "#fdf2f8", "border": "#fbcfe8", "txt": "#be185d", "icono": "🔴"},
    "Cart-56": {"bg": "#fff7ed", "border": "#fdba74", "txt": "#c2410c", "icono": "🟠"},
}

STATUS_COLORS = {
    "good": ("#ecfdf5", "#10b981", "#065f46"),
    "warn": ("#fffbeb", "#f59e0b", "#92400e"),
    "danger": ("#fef2f2", "#ef4444", "#991b1b"),
    "info": ("#eff6ff", "#3b82f6", "#1d4ed8"),
}


def _fmt_int(val: int | float) -> str:
    try:
        return f"{int(round(float(val))):,}".replace(",", ".")
    except Exception:
        return "0"


def _fmt_pct(val: float) -> str:
    try:
        return f"{float(val):.1f}%".replace(".", ",")
    except Exception:
        return "0,0%"


def _fmt_clp(val: float) -> str:
    try:
        return "$ " + f"{int(round(float(val))):,}".replace(",", ".")
    except Exception:
        return "$ 0"


def _safe_ratio(part: float, total: float) -> float:
    try:
        total_f = float(total)
        if total_f <= 0:
            return 0.0
        return (float(part) / total_f) * 100.0
    except Exception:
        return 0.0


def _norm_rut(v: str) -> str:
    return str(v or "").strip().replace(".", "").replace("-", "")


def _backend_base_url() -> str:
    return get_backend_base_url()


def _parse_datetime_multi(value: str) -> pd.Timestamp:
    text = str(value or "").strip()
    if not text:
        return pd.NaT

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y",
        "%Y%m",
        "%m/%Y",
    ):
        try:
            return pd.to_datetime(text, format=fmt, errors="raise")
        except Exception:
            pass
    return pd.to_datetime(text, errors="coerce")


def _format_duration_hhmmss(total_seconds: float) -> str:
    try:
        total = max(int(total_seconds), 0)
    except Exception:
        total = 0
    horas = total // 3600
    minutos = (total % 3600) // 60
    segundos = total % 60
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


def _add_shadow(widget: QWidget, blur: int = 26, y_offset: int = 8) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y_offset)
    shadow.setColor(QColor(15, 23, 42, 28))
    widget.setGraphicsEffect(shadow)


class _ChipLabel(QLabel):
    def __init__(self, text: str = "", level: str = "info", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(26)
        self.set_level(level)

    def set_level(self, level: str):
        bg, border, txt = STATUS_COLORS.get(level, STATUS_COLORS["info"])
        self.setStyleSheet(
            f"""
            QLabel {{
                background:{bg};
                color:{txt};
                border:1px solid {border};
                border-radius:13px;
                padding: 3px 10px;
                font-size:8.5pt;
                font-weight:700;
            }}
            """
        )


class _DashboardCard(QFrame):
    def __init__(self, parent=None, padding: int = 18):
        super().__init__(parent)
        self.setObjectName("DashboardCard")
        self.setStyleSheet(
            """
            QFrame#DashboardCard {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 20px;
            }
            """
        )
        _add_shadow(self, blur=24, y_offset=7)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(12)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class _HeroCard(_DashboardCard):
    def __init__(self, parent=None):
        super().__init__(parent, padding=22)
        self.setStyleSheet(
            """
            QFrame#DashboardCard {
                border-radius: 24px;
                border: 1px solid rgba(255,255,255,0.08);
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f172a,
                    stop:0.55 #1d4ed8,
                    stop:1 #38bdf8
                );
            }
            QLabel { background: transparent; border: none; }
            """
        )

        wrap = QHBoxLayout()
        wrap.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(4)

        self.lbl_kicker = QLabel("CRM DE COBRANZAS · PRODUCTIVIDAD")
        self.lbl_kicker.setStyleSheet(
            "color: rgba(255,255,255,0.72); font-size:8pt; font-weight:800; letter-spacing:1px;"
        )

        self.lbl_title = QLabel("Dashboard ejecutivo")
        self.lbl_title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.lbl_title.setStyleSheet("color:#ffffff;")

        self.lbl_subtitle = QLabel(
            "Vista integral del rendimiento operativo, avance de cartera, foco diario y actividad del equipo."
        )
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setStyleSheet("color: rgba(255,255,255,0.88); font-size:9.5pt;")

        left.addWidget(self.lbl_kicker)
        left.addWidget(self.lbl_title)
        left.addWidget(self.lbl_subtitle)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addStretch(1)

        self.lbl_health = QLabel("Salud operativa: Sin datos")
        self.lbl_health.setStyleSheet(
            """
            QLabel {
                background: rgba(255,255,255,0.18);
                color:#ffffff;
                border-radius: 14px;
                padding: 9px 12px;
                font-weight: 800;
            }
            """
        )

        self.lbl_focus = QLabel("Foco del día: Esperando actualización")
        self.lbl_focus.setWordWrap(True)
        self.lbl_focus.setStyleSheet(
            """
            QLabel {
                background: rgba(255,255,255,0.12);
                color: rgba(255,255,255,0.94);
                border-radius: 14px;
                padding: 10px 12px;
            }
            """
        )

        right.addWidget(self.lbl_health)
        right.addWidget(self.lbl_focus)

        wrap.addLayout(left, 3)
        wrap.addLayout(right, 2)
        self.body.addLayout(wrap)

    def set_health(self, label: str, focus: str):
        self.lbl_health.setText(f"Salud operativa: {label}")
        self.lbl_focus.setText(f"Foco del día: {focus}")


class _SectionCard(_DashboardCard):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent, padding=18)

        header = QVBoxLayout()
        header.setSpacing(3)

        self.lbl_title = QLabel(title)
        self.lbl_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.lbl_title.setStyleSheet("color:#0f172a;")

        self.lbl_subtitle = QLabel(subtitle)
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setStyleSheet("color:#64748b; font-size:9pt;")

        header.addWidget(self.lbl_title)
        if subtitle:
            header.addWidget(self.lbl_subtitle)

        self.body.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#eef2f7; max-height:1px; border:none;")
        self.body.addWidget(line)


class _MetricCard(_DashboardCard):
    def __init__(self, title: str, accent: str = "#2563eb", icon_text: str = "●", parent=None):
        super().__init__(parent, padding=16)
        self.accent = accent

        top = QHBoxLayout()
        top.setSpacing(8)

        self.icon = QLabel(icon_text)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setFixedSize(36, 36)
        self.icon.setStyleSheet(
            f"""
            QLabel {{
                background: {accent}22;
                color: {accent};
                border: 1px solid {accent}33;
                border-radius: 18px;
                font-weight: 800;
                font-size: 11pt;
            }}
            """
        )

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color:#64748b; font-size:9pt; font-weight:700;")
        top.addWidget(self.icon)
        top.addWidget(self.lbl_title)
        top.addStretch(1)

        self.lbl_value = QLabel("0")
        self.lbl_value.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.lbl_value.setStyleSheet(f"color:{accent};")

        self.lbl_delta = QLabel("—")
        self.lbl_delta.setStyleSheet("color:#334155; font-size:9pt; font-weight:700;")

        self.lbl_helper = QLabel("")
        self.lbl_helper.setWordWrap(True)
        self.lbl_helper.setStyleSheet("color:#94a3b8; font-size:8.5pt;")

        self.body.addLayout(top)
        self.body.addWidget(self.lbl_value)
        self.body.addWidget(self.lbl_delta)
        self.body.addWidget(self.lbl_helper)
        self.body.addStretch(1)

    def set_data(self, value: str, delta: str = "", helper: str = ""):
        self.lbl_value.setText(value)
        self.lbl_delta.setText(delta or "—")
        self.lbl_helper.setText(helper or "")


class _MiniStatCard(_DashboardCard):
    def __init__(self, title: str, accent: str = "#2563eb", parent=None):
        super().__init__(parent, padding=14)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color:#64748b; font-size:8.7pt; font-weight:700;")

        self.lbl_value = QLabel("0")
        self.lbl_value.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self.lbl_value.setStyleSheet(f"color:{accent};")

        self.lbl_detail = QLabel("—")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet("color:#475569; font-size:8.5pt;")

        self.body.addWidget(self.lbl_title)
        self.body.addWidget(self.lbl_value)
        self.body.addWidget(self.lbl_detail)
        self.body.addStretch(1)

    def set_data(self, value: str, detail: str = ""):
        self.lbl_value.setText(value)
        self.lbl_detail.setText(detail or "—")


class _ProgressCard(_DashboardCard):
    def __init__(self, title: str, accent: str = "#2563eb", icon_text: str = "●", parent=None):
        super().__init__(parent, padding=16)
        self.accent = accent

        top = QHBoxLayout()
        self.lbl_title = QLabel(f"{icon_text}  {title}")
        self.lbl_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.lbl_title.setStyleSheet("color:#0f172a;")
        top.addWidget(self.lbl_title)
        top.addStretch(1)

        self.chip = _ChipLabel("Sin datos", "info")
        top.addWidget(self.chip)

        self.lbl_main = QLabel("0")
        self.lbl_main.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self.lbl_main.setStyleSheet("color:#111827;")

        self.lbl_sub = QLabel("Sin información")
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setStyleSheet("color:#475569; font-size:9pt;")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            f"""
            QProgressBar {{
                min-height:10px;
                max-height:10px;
                border-radius:5px;
                border:1px solid #dbeafe;
                background:#eff6ff;
            }}
            QProgressBar::chunk {{
                border-radius:4px;
                background:{accent};
            }}
            """
        )

        self.lbl_progress = QLabel("0,0%")
        self.lbl_progress.setStyleSheet("color:#334155; font-size:8.7pt; font-weight:700;")

        self.lbl_detail = QLabel("")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet("color:#64748b; font-size:8.4pt;")

        self.body.addLayout(top)
        self.body.addWidget(self.lbl_main)
        self.body.addWidget(self.lbl_sub)
        self.body.addWidget(self.progress)
        self.body.addWidget(self.lbl_progress)
        self.body.addWidget(self.lbl_detail)
        self.body.addStretch(1)

    def set_data(
        self,
        main: str,
        subtitle: str,
        percent: float,
        detail: str,
        chip_text: str,
        chip_level: str,
    ):
        self.lbl_main.setText(main)
        self.lbl_sub.setText(subtitle)
        self.progress.setValue(max(0, min(100, int(round(percent)))))
        self.lbl_progress.setText(f"Cobertura operativa: {_fmt_pct(percent)}")
        self.lbl_detail.setText(detail)
        self.chip.setText(chip_text)
        self.chip.set_level(chip_level)


class _ListItemCard(QFrame):
    def __init__(self, accent: str = "#2563eb", parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            """
            QFrame {
                background:#f8fafc;
                border:1px solid #e2e8f0;
                border-radius: 14px;
            }
            QLabel {
                background: transparent;
                border:none;
            }
            """
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{accent}; font-size:10pt;")
        self.lbl_left = QLabel("—")
        self.lbl_left.setStyleSheet("color:#0f172a; font-weight:700;")
        self.lbl_mid = QLabel("")
        self.lbl_mid.setStyleSheet("color:#475569; font-size:8.8pt;")
        self.lbl_right = QLabel("0")
        self.lbl_right.setStyleSheet(f"color:{accent}; font-weight:800; font-size:10pt;")

        lay.addWidget(self.dot)
        lay.addWidget(self.lbl_left, 2)
        lay.addWidget(self.lbl_mid, 3)
        lay.addStretch(1)
        lay.addWidget(self.lbl_right)

    def set_data(self, left: str, mid: str, right: str):
        self.lbl_left.setText(left)
        self.lbl_mid.setText(mid)
        self.lbl_right.setText(right)


class DashboardWidget(QWidget):
    bd_limpiada = pyqtSignal(list)

    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        self._session = session
        self._empresas_asignadas = obtener_empresas_asignadas_para_session(session)
        self._periodos_disponibles: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        header = QHBoxLayout()

        title_block = QVBoxLayout()
        title_block.setSpacing(2)

        title = QLabel("Dashboard de Productividad")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color:#0f172a;")

        subtitle = QLabel("Panel visual tipo SaaS con lectura de cartera, gestión, foco y rendimiento operativo.")
        subtitle.setStyleSheet("color:#64748b; font-size:9pt;")

        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        header.addLayout(title_block)
        header.addStretch(1)

        self.cmb_periodo = QComboBox()
        self.cmb_periodo.addItem("Acumulado")
        self.cmb_periodo.setMinimumWidth(140)
        self.cmb_periodo.currentIndexChanged.connect(self.refrescar)
        header.addWidget(self.cmb_periodo)

        self.lbl_updated = QLabel("Actualizando…")
        self.lbl_updated.setStyleSheet("color:#64748b; font-size:9pt;")
        header.addWidget(self.lbl_updated)

        self.btn_refresh = QPushButton("🔄 Actualizar")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setStyleSheet(
            """
            QPushButton {
                background:#0f172a;
                color:#ffffff;
                border:none;
                border-radius: 12px;
                padding: 10px 14px;
                font-weight:700;
            }
            QPushButton:hover {
                background:#1e293b;
            }
            """
        )
        self.btn_refresh.clicked.connect(self.refrescar)
        header.addWidget(self.btn_refresh)

        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        root.addWidget(self.scroll, 1)

        self.canvas = QWidget()
        self.canvas.setStyleSheet("background:transparent;")
        self.scroll.setWidget(self.canvas)

        self.content = QVBoxLayout(self.canvas)
        self.content.setContentsMargins(0, 2, 0, 6)
        self.content.setSpacing(14)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.refrescar)
        self._timer.start()

        QTimer.singleShot(0, self.refrescar)

    def _usa_restriccion_carteras(self) -> bool:
        return session_tiene_restriccion_por_cartera(self._session)

    def _empresas_visibles(self) -> list[str]:
        return self._empresas_asignadas if self._usa_restriccion_carteras() else list(EMPRESAS)

    def _periodo_actual(self) -> str:
        return self.cmb_periodo.currentText().strip() if hasattr(self, "cmb_periodo") else "Acumulado"

    def _set_periodos_disponibles(self, periodos: list[str]) -> None:
        actuales = ["Acumulado"] + [p for p in periodos if p]
        actual = self._periodo_actual()
        self.cmb_periodo.blockSignals(True)
        self.cmb_periodo.clear()
        self.cmb_periodo.addItems(actuales)
        idx = self.cmb_periodo.findText(actual)
        self.cmb_periodo.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_periodo.blockSignals(False)
        self._periodos_disponibles = list(periodos)

    def _sin_carteras_asignadas(self) -> bool:
        return self._usa_restriccion_carteras() and not self._empresas_asignadas

    def _is_supervisor(self) -> bool:
        return bool(self._session and getattr(self._session, "role", "") == "supervisor")

    def _can_view_reporte_ejecutiva(self) -> bool:
        return bool(self._session and getattr(self._session, "role", "") in ("admin", "supervisor"))

    def _build_ui(self):
        self.hero = _HeroCard()
        self.content.addWidget(self.hero)

        top_metrics = QGridLayout()
        top_metrics.setHorizontalSpacing(12)
        top_metrics.setVerticalSpacing(12)

        self.card_total_deudores = _MetricCard("Cartera total", "#2563eb", "👥")
        self.card_saldo = _MetricCard("Saldo actual", "#dc2626", "💰")
        self.card_gestionados = _MetricCard("Cobertura de gestión", "#059669", "📈")
        self.card_hoy = _MetricCard("Gestiones hoy", "#7c3aed", "⚡")

        top_metrics.addWidget(self.card_total_deudores, 0, 0)
        top_metrics.addWidget(self.card_saldo, 0, 1)
        top_metrics.addWidget(self.card_gestionados, 0, 2)
        top_metrics.addWidget(self.card_hoy, 0, 3)

        self.content.addLayout(top_metrics)

        mini_metrics = QGridLayout()
        mini_metrics.setHorizontalSpacing(12)
        mini_metrics.setVerticalSpacing(12)

        self.op_sin_gestion = _MiniStatCard("Sin gestión", "#f59e0b")
        self.op_7d = _MiniStatCard("Gestiones últimos 7 días", "#0ea5e9")
        self.op_contactados = _MiniStatCard("Contactados + promesas", "#10b981")
        self.op_recuperacion = _MiniStatCard("Ratio pagos/copago", "#8b5cf6")

        mini_metrics.addWidget(self.op_sin_gestion, 0, 0)
        mini_metrics.addWidget(self.op_7d, 0, 1)
        mini_metrics.addWidget(self.op_contactados, 0, 2)
        mini_metrics.addWidget(self.op_recuperacion, 0, 3)

        self.content.addLayout(mini_metrics)

        middle = QHBoxLayout()
        middle.setSpacing(12)

        self.card_funnel = _SectionCard(
            "Embudo de cartera",
            "Distribución actual por estado deudor consolidado.",
        )
        self.card_actions = _SectionCard(
            "Acciones y canales",
            "Tipos de gestión del día para lectura táctica de ejecución.",
        )

        self.funnel_rows: list[_ListItemCard] = []
        self.action_rows: list[_ListItemCard] = []

        for _ in range(5):
            row = _ListItemCard("#2563eb")
            self.funnel_rows.append(row)
            self.card_funnel.body.addWidget(row)

        for _ in range(5):
            row = _ListItemCard("#7c3aed")
            self.action_rows.append(row)
            self.card_actions.body.addWidget(row)

        middle.addWidget(self.card_funnel, 1)
        middle.addWidget(self.card_actions, 1)
        self.content.addLayout(middle)

        self.sec_empresas = _SectionCard(
            "Performance por compañía",
            "Cada compañía se presenta como una tarjeta independiente con foco en cobertura, saldo y pendiente.",
        )
        self.content.addWidget(self.sec_empresas)

        company_grid = QGridLayout()
        company_grid.setHorizontalSpacing(12)
        company_grid.setVerticalSpacing(12)

        self._company_cards: dict[str, _ProgressCard] = {}
        for i, empresa in enumerate(EMPRESAS):
            cfg = EMPRESA_CONFIG.get(empresa, {})
            card = _ProgressCard(
                title=empresa,
                accent=cfg.get("txt", "#2563eb"),
                icon_text=cfg.get("icono", "●"),
            )
            self._company_cards[empresa] = card
            company_grid.addWidget(card, i // 2, i % 2)

        self.sec_empresas.body.addLayout(company_grid)

        if self._can_view_reporte_ejecutiva():
            self.sec_team = _SectionCard(
                "Productividad del equipo",
                "Panel de sesiones y actividad de ejecutivas con enfoque visual de dashboard.",
            )
            self.content.addWidget(self.sec_team)

            team_metrics = QGridLayout()
            team_metrics.setHorizontalSpacing(12)
            team_metrics.setVerticalSpacing(12)

            self.pill_conexiones_hoy = _MetricCard("Conexiones hoy", "#2563eb", "🔐")
            self.pill_ejecutivas_hoy = _MetricCard("Ejecutivas activas", "#059669", "👩")
            self.pill_conexiones_mes = _MetricCard("Conexiones del mes", "#7c3aed", "🗓")
            self.pill_duracion_prom = _MetricCard("Duración promedio", "#ea580c", "⏱")

            team_metrics.addWidget(self.pill_conexiones_hoy, 0, 0)
            team_metrics.addWidget(self.pill_ejecutivas_hoy, 0, 1)
            team_metrics.addWidget(self.pill_conexiones_mes, 0, 2)
            team_metrics.addWidget(self.pill_duracion_prom, 0, 3)

            self.sec_team.body.addLayout(team_metrics)

            team_lower = QHBoxLayout()
            team_lower.setSpacing(12)

            self.team_rank_card = _SectionCard(
                "Ranking mensual",
                "Top de ejecutivas por cantidad de conexiones del mes.",
            )
            self.team_rank_rows: list[_ListItemCard] = []
            for _ in range(5):
                row = _ListItemCard("#059669")
                self.team_rank_rows.append(row)
                self.team_rank_card.body.addWidget(row)

            self.team_table_card = _SectionCard(
                "Sesiones del día",
                "Detalle diario de ingreso, salida y horas trabajadas.",
            )

            actions = QHBoxLayout()
            actions.addStretch(1)

            self.lbl_mes_reporte = QLabel("")
            self.lbl_mes_reporte.setStyleSheet("color:#64748b; font-size:9pt;")
            actions.addWidget(self.lbl_mes_reporte)

            if self._is_supervisor():
                self.btn_export = QPushButton("📥 Descargar Excel mensual")
                self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_export.setStyleSheet(
                    """
                    QPushButton {
                        background:#ffffff;
                        color:#0f172a;
                        border:1px solid #cbd5e1;
                        border-radius: 12px;
                        padding: 9px 12px;
                        font-weight:700;
                    }
                    QPushButton:hover {
                        background:#f8fafc;
                    }
                    """
                )
                self.btn_export.clicked.connect(self._exportar_excel_mensual)
                actions.addWidget(self.btn_export)

            self.team_table_card.body.addLayout(actions)

            self.tbl_ej = QTableWidget(0, 5)
            self.tbl_ej.setHorizontalHeaderLabels(
                ["Ejecutiva", "Fecha", "Hora de inicio", "Hora de término", "Horas trabajadas"]
            )
            self.tbl_ej.verticalHeader().setVisible(False)
            self.tbl_ej.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.tbl_ej.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.tbl_ej.setAlternatingRowColors(True)
            self.tbl_ej.setStyleSheet(
                """
                QTableWidget {
                    border:1px solid #e2e8f0;
                    border-radius: 14px;
                    background:#ffffff;
                    alternate-background-color:#f8fafc;
                    gridline-color:#eef2f7;
                }
                QHeaderView::section {
                    background:#f8fafc;
                    color:#334155;
                    border:none;
                    border-bottom:1px solid #e2e8f0;
                    padding:10px;
                    font-weight:700;
                }
                """
            )
            hh = self.tbl_ej.horizontalHeader()
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

            self.team_table_card.body.addWidget(self.tbl_ej)

            team_lower.addWidget(self.team_rank_card, 1)
            team_lower.addWidget(self.team_table_card, 2)

            self.sec_team.body.addLayout(team_lower)

        self.content.addStretch(1)

    def _usa_backend_dashboard(self) -> bool:
        return bool(
            self._session
            and getattr(self._session, "auth_source", "") == "backend"
            and getattr(self._session, "access_token", None)
        )

    def _backend_headers(self) -> dict[str, str]:
        token = getattr(self._session, "access_token", "") if self._session else ""
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _backend_empresas_param(self) -> str:
        return ",".join(self._empresas_visibles())

    def _refrescar_dashboard_backend(self) -> bool:
        try:
            resp = requests.get(
                f"{_backend_base_url()}/dashboard/summary",
                params={"empresas": self._backend_empresas_param(), "periodo_carga": "" if self._periodo_actual() == "Acumulado" else self._periodo_actual()},
                headers=self._backend_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            self.hero.set_health("Sin conexión backend", f"No se pudo cargar el dashboard desde backend: {e}")
            self.lbl_updated.setText(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            return False

        self._set_periodos_disponibles(list(payload.get("periodos_disponibles", []) or []))

        total_deudores = int(payload.get("total_deudores", 0) or 0)
        total_copago = float(payload.get("copago_total", 0) or 0)
        total_pagos = float(payload.get("total_pagos_total", 0) or 0)
        total_saldo = float(payload.get("saldo_total", 0) or 0)
        sin_gestion_total = int(payload.get("sin_gestion_total", 0) or 0)
        managed_count = int(payload.get("gestionados_total", 0) or 0)
        managed_pct = float(payload.get("cobertura_pct", 0) or 0)

        self.hero.set_health(
            str(payload.get("health_label", "Sin datos")),
            str(payload.get("focus_text", "Carga una base de deudores para activar el panel operativo.")),
        )

        self.card_total_deudores.set_data(
            _fmt_int(total_deudores),
            f"{_fmt_int(managed_count)} gestionados · {_fmt_int(sin_gestion_total)} pendientes",
            "Base consolidada del período seleccionado." if self._periodo_actual() != "Acumulado" else "Base consolidada total actualmente cargada en el CRM.",
        )
        self.card_saldo.set_data(
            _fmt_clp(total_saldo),
            f"Copago: {_fmt_clp(total_copago)} · Pagos: {_fmt_clp(total_pagos)}",
            "Saldo económico vigente del período seleccionado." if self._periodo_actual() != "Acumulado" else "Saldo económico vigente después de pagos registrados.",
        )
        self.card_gestionados.set_data(
            _fmt_pct(managed_pct),
            f"Cobertura real sobre {_fmt_int(total_deudores)} deudores",
            "Porcentaje de cartera del período con último estado distinto de 'Sin Gestión'." if self._periodo_actual() != "Acumulado" else "Porcentaje de cartera con último estado distinto de 'Sin Gestión'.",
        )
        self.card_hoy.set_data(
            _fmt_int(payload.get("gestiones_hoy", 0)),
            f"{_fmt_int(payload.get('gestiones_7d', 0))} con actividad en 7 días",
            "Últimas gestiones únicas del día por RUT.",
        )

        self.op_sin_gestion.set_data(
            _fmt_int(sin_gestion_total),
            f"{_fmt_pct(_safe_ratio(sin_gestion_total, total_deudores))} de la cartera total",
        )
        self.op_7d.set_data(
            _fmt_int(payload.get("gestiones_7d", 0)),
            f"Gestiones únicas hoy: {_fmt_int(payload.get('gestiones_hoy', 0))}",
        )
        self.op_contactados.set_data(
            _fmt_int(payload.get("contactados_total", 0)),
            f"{_fmt_pct(_safe_ratio(payload.get('contactados_total', 0), total_deudores))} de cobertura efectiva",
        )
        self.op_recuperacion.set_data(
            _fmt_pct(payload.get("pagos_vs_copago_pct", 0)),
            f"Pagos {_fmt_clp(total_pagos)} vs copago {_fmt_clp(total_copago)}",
        )

        estado_counts = payload.get("estado_counts", {}) or {}
        top_funnel = sorted(estado_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        funnel_rows = [
            (
                str(estado),
                f"{_fmt_pct(_safe_ratio(cantidad, total_deudores))} de la cartera",
                _fmt_int(cantidad),
            )
            for estado, cantidad in top_funnel
        ]
        if not funnel_rows:
            funnel_rows = [("Sin datos", "Carga una base para ver el embudo", "0")]
        self._set_rows(self.funnel_rows, funnel_rows)

        tipos_hoy = payload.get("tipos_hoy", {}) or {}
        tipos_rows = [
            (
                str(tipo),
                "Gestiones registradas hoy",
                _fmt_int(cantidad),
            )
            for tipo, cantidad in tipos_hoy.items()
        ]
        if not tipos_rows:
            tipos_rows = [("Sin actividad", "Hoy todavía no hay gestiones registradas", "0")]
        self._set_rows(self.action_rows, tipos_rows)

        company_map = {str(c.get("empresa", "")): c for c in (payload.get("companies", []) or [])}

        for empresa in EMPRESAS:
            self._company_cards[empresa].setVisible(empresa in self._empresas_visibles())
            if empresa not in self._empresas_visibles():
                continue

            datos = company_map.get(empresa, {})
            self._company_cards[empresa].set_data(
                main=f"{_fmt_int(datos.get('deudores', 0))} deudores",
                subtitle=(
                    f"{datos.get('freshness', 'Backend')} · {_fmt_int(datos.get('sin_gestion', 0))} sin gestión · "
                    f"{_fmt_clp(float(datos.get('saldo_actual', 0.0) or 0.0))} de saldo"
                ),
                percent=float(datos.get("cobertura_pct", 0) or 0),
                detail=(
                    f"Gestionados: {_fmt_int(datos.get('gestionados', 0))} ({_fmt_pct(datos.get('cobertura_pct', 0))})\n"
                    f"Pagos: {_fmt_clp(float(datos.get('total_pagos', 0.0) or 0.0))}\n"
                    f"Copago: {_fmt_clp(float(datos.get('copago', 0.0) or 0.0))}"
                ),
                chip_text=str(datos.get("status_label", "Sin base")),
                chip_level=str(datos.get("status_level", "info")),
            )

        self.lbl_updated.setText(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        return True

    def _gestiones_db_path(self) -> str:
        return os.path.join(str(get_data_dir()), "db_gestiones.sqlite")

    def _load_gestiones_df(self) -> pd.DataFrame:
        path = self._gestiones_db_path()
        if not os.path.exists(path):
            return pd.DataFrame()
        try:
            with sqlite3.connect(path) as con:
                return pd.read_sql(
                    f"""
                    SELECT id, Rut_Afiliado, Nombre_Afiliado, tipo_gestion, Estado, Fecha_gestion, _fecha_carga
                    FROM {TABLA_GESTIONES}
                    """,
                    con,
                    dtype=str,
                ).fillna("")
        except Exception:
            return pd.DataFrame()

    def _company_map(self) -> tuple[pd.DataFrame, dict[str, str]]:
        df_deu = cargar_empresas(self._empresas_visibles()) if self._usa_restriccion_carteras() else cargar_todas()
        if df_deu.empty or "Rut_Afiliado" not in df_deu.columns:
            return pd.DataFrame(), {}
        work = df_deu.copy()
        work["_rut_norm"] = work["Rut_Afiliado"].apply(_norm_rut)
        if "_empresa" not in work.columns:
            work["_empresa"] = ""
        if self._usa_restriccion_carteras():
            work = work[work["_empresa"].astype(str).isin(self._empresas_visibles())].copy()
        work = work.drop_duplicates(subset=["_rut_norm"], keep="first")
        return work, dict(zip(work["_rut_norm"], work["_empresa"]))

    def _load_estado_actual_df(self) -> pd.DataFrame:
        df_deu, _ = self._company_map()
        if df_deu.empty:
            return pd.DataFrame()

        mapa = obtener_estados_deudor_por_rut()
        df = df_deu.copy()
        df["Estado_deudor"] = df["_rut_norm"].map(mapa).fillna(ESTADO_DEUDOR_DEFAULT)
        return df

    def _build_gestiones_period_stats(self, df_g: pd.DataFrame, company_by_rut: dict[str, str]) -> dict:
        if df_g.empty:
            return {
                "hoy_unicas": 0,
                "ultimos_7d": 0,
                "tipos_hoy": {},
            }

        df = df_g.copy()
        df["_rut_norm"] = df["Rut_Afiliado"].apply(_norm_rut)
        df["_empresa"] = df["_rut_norm"].map(company_by_rut).fillna("")
        df["_fecha_dt"] = pd.to_datetime(df["Fecha_gestion"], format="%d/%m/%Y", errors="coerce")
        df["_id_sort"] = pd.to_numeric(df["id"], errors="coerce").fillna(0)

        hoy_dt = pd.Timestamp(datetime.now().date())
        ini_7d = hoy_dt - pd.Timedelta(days=6)

        df_hoy = df[df["_fecha_dt"] == hoy_dt].copy()
        df_hoy = df_hoy.sort_values(by=["_rut_norm", "_id_sort"], ascending=[True, False])
        df_hoy_latest = df_hoy.drop_duplicates(subset=["_rut_norm"], keep="first")

        df_7d = df[df["_fecha_dt"].between(ini_7d, hoy_dt, inclusive="both")].copy()
        df_7d = df_7d.sort_values(by=["_rut_norm", "_fecha_dt", "_id_sort"], ascending=[True, False, False])
        df_7d_latest = df_7d.drop_duplicates(subset=["_rut_norm"], keep="first")

        tipos_hoy = (
            df_hoy_latest["tipo_gestion"].astype(str).replace("", "Sin tipo").value_counts().head(5).to_dict()
            if not df_hoy_latest.empty
            else {}
        )

        return {
            "hoy_unicas": int(len(df_hoy_latest)),
            "ultimos_7d": int(len(df_7d_latest)),
            "tipos_hoy": {str(k): int(v) for k, v in tipos_hoy.items()},
        }

    def _build_team_stats(self, df_hoy: pd.DataFrame, df_mes: pd.DataFrame) -> dict:
        def _prepare(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or df.empty:
                return pd.DataFrame(columns=["username", "login_at", "logout_at"])
            out = df.copy()
            out["login_dt"] = pd.to_datetime(out["login_at"], errors="coerce")
            out["logout_dt"] = pd.to_datetime(out["logout_at"], errors="coerce")
            out["duration_sec"] = (out["logout_dt"] - out["login_dt"]).dt.total_seconds().fillna(0)
            out.loc[out["duration_sec"] < 0, "duration_sec"] = 0
            return out

        hoy_p = _prepare(df_hoy)
        mes_p = _prepare(df_mes)

        avg_today = hoy_p["duration_sec"].mean() if not hoy_p.empty else 0
        ranking = []

        if not mes_p.empty:
            grouped = (
                mes_p.groupby("username", dropna=False)
                .agg(
                    conexiones=("username", "size"),
                    total_segundos=("duration_sec", "sum"),
                    promedio_segundos=("duration_sec", "mean"),
                )
                .sort_values(by=["conexiones", "total_segundos"], ascending=[False, False])
                .head(5)
                .reset_index()
            )
            for _, row in grouped.iterrows():
                ranking.append(
                    {
                        "username": str(row.get("username", "") or "Sin usuario"),
                        "conexiones": int(row.get("conexiones", 0)),
                        "total": _format_duration_hhmmss(row.get("total_segundos", 0)),
                        "promedio": _format_duration_hhmmss(row.get("promedio_segundos", 0)),
                    }
                )

        return {
            "avg_today": _format_duration_hhmmss(avg_today),
            "ranking": ranking,
        }

    def _fill_ejecutivas_table(self, df_hoy: pd.DataFrame):
        if not self._can_view_reporte_ejecutiva():
            return

        rep = preparar_reporte_excel(df_hoy)
        self.tbl_ej.setRowCount(0)

        for _, row in rep.iterrows():
            r = self.tbl_ej.rowCount()
            self.tbl_ej.insertRow(r)
            for c, key in enumerate(rep.columns):
                item = QTableWidgetItem(str(row.get(key, "")))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl_ej.setItem(r, c, item)

    def _set_rows(self, rows: list[_ListItemCard], data: list[tuple[str, str, str]]):
        for idx, row in enumerate(rows):
            if idx < len(data):
                left, mid, right = data[idx]
                row.show()
                row.set_data(left, mid, right)
            else:
                row.hide()

    def _exportar_excel_mensual(self):
        hoy = datetime.now()
        df_mes = obtener_conexiones_mes(hoy.year, hoy.month, role="ejecutivo")
        rep = preparar_reporte_excel(df_mes)

        if rep.empty:
            QMessageBox.information(self, "Sin datos", "No hay conexiones mensuales para exportar todavía.")
            return

        sugerido = f"reporte_conexiones_ejecutivas_{hoy.strftime('%Y_%m')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar reporte mensual", sugerido, "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            write_excel_report(path, {"Conexiones": rep})
            QMessageBox.information(self, "Reporte generado", f"El reporte fue exportado correctamente en:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el Excel.\n\nDetalle:\n{e}")

    def _build_global_status(
        self,
        total_deudores: int,
        sin_gestion: int,
        gestiones_hoy: int,
        managed_pct: float,
    ) -> tuple[str, str]:
        if total_deudores <= 0:
            return "Sin datos", "Carga una base de deudores para activar el panel operativo."

        sin_ratio = _safe_ratio(sin_gestion, total_deudores)

        if managed_pct >= 70 and gestiones_hoy >= max(5, int(total_deudores * 0.02)):
            return "Alta", "Mantén el ritmo actual y focaliza la cartera en 'Sin Gestión' más antigua."
        if managed_pct >= 45 and sin_ratio <= 55:
            return "Media", "La cobertura es aceptable, pero conviene acelerar gestiones en cartera pendiente."
        return "Crítica", "Prioriza asignación sobre casos sin gestión y aumenta el volumen diario de contacto."

    def refrescar(self):
        if self._usa_restriccion_carteras():
            self._empresas_asignadas = obtener_empresas_asignadas_para_session(self._session)

            if not self._empresas_asignadas:
                self.hero.set_health("Sin carteras asignadas", "Contacta a un supervisor o administrador para obtener visibilidad.")
                self.card_total_deudores.set_data("0", "Sin carteras asignadas", "No tienes empresas asignadas en esta sesión.")
                self.card_saldo.set_data("$ 0", "Sin carteras asignadas", "No hay métricas disponibles.")
                self.card_gestionados.set_data("0,0%", "Sin carteras asignadas", "No hay cobertura disponible.")
                self.card_hoy.set_data("0", "Sin carteras asignadas", "No hay actividad visible.")
                self.op_sin_gestion.set_data("0", "Sin carteras asignadas")
                self.op_7d.set_data("0", "Sin carteras asignadas")
                self.op_contactados.set_data("0", "Sin carteras asignadas")
                self.op_recuperacion.set_data("0,0%", "Sin carteras asignadas")
                self._set_rows(self.funnel_rows, [("Sin carteras asignadas", "No tienes empresas visibles", "0")])
                self._set_rows(self.action_rows, [("Sin carteras asignadas", "No tienes empresas visibles", "0")])
                for empresa in EMPRESAS:
                    self._company_cards[empresa].setVisible(False)
                self.lbl_updated.setText(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                return

        if self._usa_backend_dashboard():
            ok = self._refrescar_dashboard_backend()

            if ok and self._can_view_reporte_ejecutiva():
                hoy = datetime.now()
                df_hoy = obtener_conexiones_hoy(role="ejecutivo")
                df_mes = obtener_conexiones_mes(hoy.year, hoy.month, role="ejecutivo")
                team_stats = self._build_team_stats(df_hoy, df_mes)
                self._fill_ejecutivas_table(df_hoy)

                unique_today = int(df_hoy["username"].nunique()) if not df_hoy.empty and "username" in df_hoy.columns else 0

                self.pill_conexiones_hoy.set_data(
                    _fmt_int(len(df_hoy)),
                    f"{_fmt_int(unique_today)} ejecutivas activas",
                    "Número total de sesiones iniciadas hoy.",
                )
                self.pill_ejecutivas_hoy.set_data(
                    _fmt_int(unique_today),
                    f"{_fmt_int(len(df_hoy))} sesiones hoy",
                    "Usuarios únicos conectados hoy con rol ejecutivo.",
                )
                self.pill_conexiones_mes.set_data(
                    _fmt_int(len(df_mes)),
                    f"Mes actual: {hoy.strftime('%m/%Y')}",
                    "Acumulado de sesiones del mes actual.",
                )
                self.pill_duracion_prom.set_data(
                    team_stats.get("avg_today", "00:00:00"),
                    "Duración promedio por sesión del día",
                    "Sirve para leer continuidad operativa del equipo.",
                )

                self.lbl_mes_reporte.setText(f"Mes actual: {hoy.strftime('%m/%Y')}")

                ranking_rows = []
                for item in team_stats.get("ranking", []):
                    ranking_rows.append(
                        (
                            item.get("username", "Sin usuario"),
                            f"Total: {item.get('total', '00:00:00')} · Promedio: {item.get('promedio', '00:00:00')}",
                            _fmt_int(item.get("conexiones", 0)),
                        )
                    )
                if not ranking_rows:
                    ranking_rows = [("Sin actividad", "Aún no hay conexiones mensuales registradas", "0")]

                self._set_rows(self.team_rank_rows, ranking_rows)
            return

        if self._sin_carteras_asignadas():
            self.hero.set_health("Sin carteras asignadas", "Contacta a un supervisor o administrador para obtener visibilidad.")
            self.card_total_deudores.set_data("0", "Sin carteras asignadas", "No tienes empresas asignadas en esta sesión.")
            self.card_saldo.set_data("$ 0", "Sin carteras asignadas", "No hay métricas disponibles.")
            self.card_gestionados.set_data("0,0%", "Sin carteras asignadas", "No hay cobertura disponible.")
            self.card_hoy.set_data("0", "Sin carteras asignadas", "No hay actividad visible.")
            self.op_sin_gestion.set_data("0", "Sin carteras asignadas")
            self.op_7d.set_data("0", "Sin carteras asignadas")
            self.op_contactados.set_data("0", "Sin carteras asignadas")
            self.op_recuperacion.set_data("0,0%", "Sin carteras asignadas")
            self._set_rows(self.funnel_rows, [("Sin carteras asignadas", "No tienes empresas visibles", "0")])
            self._set_rows(self.action_rows, [("Sin carteras asignadas", "No tienes empresas visibles", "0")])
            for empresa in EMPRESAS:
                self._company_cards[empresa].setVisible(False)
            self.lbl_updated.setText(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            return

        empresas_visibles = self._empresas_visibles()
        montos = stats_por_empresas(empresas_visibles) if self._usa_restriccion_carteras() else stats_por_empresa()
        df_estado = self._load_estado_actual_df()
        _, company_by_rut = self._company_map()
        df_g = self._load_gestiones_df()
        gest_period = self._build_gestiones_period_stats(df_g, company_by_rut)

        total = montos.get("_total", {})
        total_deudores = int(total.get("deudores", 0) or 0)
        total_copago = float(total.get("copago", 0.0) or 0.0)
        total_pagos = float(total.get("pagos", 0.0) or 0.0)
        total_saldo = float(total.get("saldo", 0.0) or 0.0)

        if df_estado.empty:
            sin_gestion_total = 0
            managed_count = 0
            estado_counts = {}
        else:
            estado_counts = df_estado["Estado_deudor"].astype(str).value_counts().to_dict()
            sin_gestion_total = int(estado_counts.get(ESTADO_DEUDOR_DEFAULT, 0))
            managed_count = max(len(df_estado) - sin_gestion_total, 0)

        managed_pct = _safe_ratio(managed_count, total_deudores)
        pagos_vs_copago_pct = _safe_ratio(total_pagos, total_copago)
        contactados = int(
            sum(
                int(estado_counts.get(k, 0))
                for k in [
                    "Contactado",
                    "CIP Con intención de pago",
                    "Promesa de pago",
                    "Acuerdo de pago",
                ]
            )
        )

        health_label, focus_text = self._build_global_status(
            total_deudores=total_deudores,
            sin_gestion=sin_gestion_total,
            gestiones_hoy=int(gest_period.get("hoy_unicas", 0)),
            managed_pct=managed_pct,
        )
        self.hero.set_health(health_label, focus_text)

        self.card_total_deudores.set_data(
            _fmt_int(total_deudores),
            f"{_fmt_int(managed_count)} gestionados · {_fmt_int(sin_gestion_total)} pendientes",
            "Base consolidada total actualmente cargada en el CRM.",
        )
        self.card_saldo.set_data(
            _fmt_clp(total_saldo),
            f"Copago: {_fmt_clp(total_copago)} · Pagos: {_fmt_clp(total_pagos)}",
            "Saldo económico vigente después de pagos registrados.",
        )
        self.card_gestionados.set_data(
            _fmt_pct(managed_pct),
            f"Cobertura real sobre {_fmt_int(total_deudores)} deudores",
            "Porcentaje de cartera con último estado distinto de 'Sin Gestión'.",
        )
        self.card_hoy.set_data(
            _fmt_int(gest_period.get("hoy_unicas", 0)),
            f"{_fmt_int(gest_period.get('ultimos_7d', 0))} con actividad en 7 días",
            "Últimas gestiones únicas del día por RUT.",
        )

        self.op_sin_gestion.set_data(
            _fmt_int(sin_gestion_total),
            f"{_fmt_pct(_safe_ratio(sin_gestion_total, total_deudores))} de la cartera total",
        )
        self.op_7d.set_data(
            _fmt_int(gest_period.get("ultimos_7d", 0)),
            f"Promedio diario aprox.: {_fmt_int((gest_period.get('ultimos_7d', 0) or 0) / 7)}",
        )
        self.op_contactados.set_data(
            _fmt_int(contactados),
            f"{_fmt_pct(_safe_ratio(contactados, total_deudores))} de cobertura efectiva",
        )
        self.op_recuperacion.set_data(
            _fmt_pct(pagos_vs_copago_pct),
            f"Pagos {_fmt_clp(total_pagos)} vs copago {_fmt_clp(total_copago)}",
        )

        top_funnel = sorted(estado_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        funnel_rows = [
            (
                str(estado),
                f"{_fmt_pct(_safe_ratio(cantidad, total_deudores))} de la cartera",
                _fmt_int(cantidad),
            )
            for estado, cantidad in top_funnel
        ]
        if not funnel_rows:
            funnel_rows = [("Sin datos", "Carga una base para ver el embudo", "0")]
        self._set_rows(self.funnel_rows, funnel_rows)

        tipos_hoy = gest_period.get("tipos_hoy", {})
        tipos_rows = [
            (
                str(tipo),
                "Gestiones registradas hoy",
                _fmt_int(cantidad),
            )
            for tipo, cantidad in tipos_hoy.items()
        ]
        if not tipos_rows:
            tipos_rows = [("Sin actividad", "Hoy todavía no hay gestiones registradas", "0")]
        self._set_rows(self.action_rows, tipos_rows)

        for empresa in EMPRESAS:
            self._company_cards[empresa].setVisible(empresa in empresas_visibles)
            if empresa not in empresas_visibles:
                continue
            datos = montos.get(empresa, {})
            total_emp = int(datos.get("deudores", 0) or 0)
            fecha_txt = str(datos.get("fecha", "") or "")
            fecha_dt = _parse_datetime_multi(fecha_txt)
            freshness_days = int((pd.Timestamp.now() - fecha_dt).days) if not pd.isna(fecha_dt) else None

            if df_estado.empty:
                emp_estado = pd.DataFrame()
            else:
                emp_estado = df_estado[df_estado["_empresa"] == empresa].copy()

            sin_gestion_emp = int((emp_estado["Estado_deudor"] == ESTADO_DEUDOR_DEFAULT).sum()) if not emp_estado.empty else 0
            managed_emp = max(total_emp - sin_gestion_emp, 0)
            managed_emp_pct = _safe_ratio(managed_emp, total_emp)

            if total_emp <= 0:
                status_label, status_level = "Sin base", "info"
            elif managed_emp_pct >= 70:
                status_label, status_level = "Al día", "good"
            elif managed_emp_pct >= 40:
                status_label, status_level = "Intermedio", "warn"
            else:
                status_label, status_level = "Pendiente", "danger"

            freshness_text = "Sin fecha"
            if freshness_days is not None:
                freshness_text = "Carga hoy" if freshness_days <= 0 else f"Carga hace {freshness_days} día(s)"

            subtitle = (
                f"{freshness_text} · {_fmt_int(sin_gestion_emp)} sin gestión · "
                f"{_fmt_clp(float(datos.get('saldo', 0.0) or 0.0))} de saldo"
            )
            detail = (
                f"Gestionados: {_fmt_int(managed_emp)} ({_fmt_pct(managed_emp_pct)})\n"
                f"Pagos: {_fmt_clp(float(datos.get('pagos', 0.0) or 0.0))}\n"
                f"Copago: {_fmt_clp(float(datos.get('copago', 0.0) or 0.0))}"
            )

            self._company_cards[empresa].set_data(
                main=f"{_fmt_int(total_emp)} deudores",
                subtitle=subtitle,
                percent=managed_emp_pct,
                detail=detail,
                chip_text=status_label,
                chip_level=status_level,
            )

        if self._can_view_reporte_ejecutiva():
            hoy = datetime.now()
            df_hoy = obtener_conexiones_hoy(role="ejecutivo")
            df_mes = obtener_conexiones_mes(hoy.year, hoy.month, role="ejecutivo")
            team_stats = self._build_team_stats(df_hoy, df_mes)
            self._fill_ejecutivas_table(df_hoy)

            unique_today = int(df_hoy["username"].nunique()) if not df_hoy.empty and "username" in df_hoy.columns else 0

            self.pill_conexiones_hoy.set_data(
                _fmt_int(len(df_hoy)),
                f"{_fmt_int(unique_today)} ejecutivas activas",
                "Número total de sesiones iniciadas hoy.",
            )
            self.pill_ejecutivas_hoy.set_data(
                _fmt_int(unique_today),
                f"{_fmt_int(len(df_hoy))} sesiones hoy",
                "Usuarios únicos conectados hoy con rol ejecutivo.",
            )
            self.pill_conexiones_mes.set_data(
                _fmt_int(len(df_mes)),
                f"Mes actual: {hoy.strftime('%m/%Y')}",
                "Acumulado de sesiones del mes actual.",
            )
            self.pill_duracion_prom.set_data(
                team_stats.get("avg_today", "00:00:00"),
                "Duración promedio por sesión del día",
                "Sirve para leer continuidad operativa del equipo.",
            )

            self.lbl_mes_reporte.setText(f"Mes actual: {hoy.strftime('%m/%Y')}")

            ranking_rows = []
            for item in team_stats.get("ranking", []):
                ranking_rows.append(
                    (
                        item.get("username", "Sin usuario"),
                        f"Total: {item.get('total', '00:00:00')} · Promedio: {item.get('promedio', '00:00:00')}",
                        _fmt_int(item.get("conexiones", 0)),
                    )
                )
            if not ranking_rows:
                ranking_rows = [("Sin actividad", "Aún no hay conexiones mensuales registradas", "0")]

            self._set_rows(self.team_rank_rows, ranking_rows)

        self.lbl_updated.setText(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")


