from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QTabBar, QTabWidget, QVBoxLayout, QWidget

from .view_config import TabConfig
from .view_envio import TabEnvio
from .view_plantillas import TabPlantillas


class _SubTabBar(QTabBar):
    ACCENT = QColor("#2563eb")
    MUTED = QColor("#94a3b8")
    TAB_H = 40
    IND_H = 3

    def tabSizeHint(self, index: int):
        sz = super().tabSizeHint(index)
        sz.setHeight(self.TAB_H)
        sz.setWidth(max(sz.width(), 130))
        return sz

    def minimumTabSizeHint(self, index: int):
        sz = super().minimumTabSizeHint(index)
        sz.setHeight(self.TAB_H)
        return sz

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        for i in range(self.count()):
            rect = self.tabRect(i)
            is_sel = self.currentIndex() == i

            p.fillRect(rect, QColor(37, 99, 235, 12) if is_sel else QColor("#ffffff"))

            if i < self.count() - 1:
                p.setPen(QColor("#e2e8f0"))
                p.drawLine(rect.right(), rect.top() + 8, rect.right(), rect.bottom() - 8)

            p.save()
            p.setPen(self.ACCENT if is_sel else self.MUTED)
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold if is_sel else QFont.Weight.Normal))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.tabText(i))
            p.restore()

            if is_sel:
                p.fillRect(
                    QRect(rect.left(), rect.bottom() - self.IND_H, rect.width(), self.IND_H),
                    self.ACCENT,
                )

        p.end()


class EnviosWidget(QWidget):
    def __init__(self, parent=None, session=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setTabBar(_SubTabBar())

        self.tab_config = TabConfig()
        self.tab_plantillas = TabPlantillas(session=session)
        self.tab_envio = TabEnvio(
            get_config_fn=self.tab_config.get_config,
            get_plantilla_fn=self.tab_plantillas.get_plantilla_actual,
            session=session,
        )

        self.tabs.addTab(self.tab_config, "⚙️ Configuración SMTP")
        self.tabs.addTab(self.tab_plantillas, "📝 Plantillas")
        self.tabs.addTab(self.tab_envio, "📤 Envío")

        layout.addWidget(self.tabs)
