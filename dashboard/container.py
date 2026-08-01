from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .productivity_view import DashboardWidget as WorkDashboardWidget
from .view import DashboardWidget as GeneralDashboardWidget


class DashboardWidget(QWidget):
    """Contenedor de las vistas operativa y general del dashboard."""

    bd_limpiada = pyqtSignal(list)

    WORK_INDEX = 0
    GENERAL_INDEX = 1

    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        self._session = session

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        navigation = QFrame()
        navigation.setObjectName("dashboardModeNavigation")
        navigation.setStyleSheet(
            """
            QFrame#dashboardModeNavigation {
                background: #ffffff;
                border: none;
                border-bottom: 1px solid #e8ecf2;
            }
            """
        )
        nav = QHBoxLayout(navigation)
        nav.setContentsMargins(20, 10, 20, 10)
        nav.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("Dashboard")
        title.setStyleSheet("color:#1e293b;font-size:15px;font-weight:700;border:none;")
        self.mode_description = QLabel("")
        self.mode_description.setStyleSheet("color:#64748b;font-size:11px;border:none;")
        title_box.addWidget(title)
        title_box.addWidget(self.mode_description)
        nav.addLayout(title_box)
        nav.addStretch(1)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.btn_work = self._mode_button("Mi trabajo", self.WORK_INDEX)
        self.btn_general = self._mode_button("Vista general", self.GENERAL_INDEX)
        nav.addWidget(self.btn_work)
        nav.addWidget(self.btn_general)
        root.addWidget(navigation)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.work_dashboard = WorkDashboardWidget(session=session)
        self.general_dashboard = GeneralDashboardWidget(session=session)
        self.stack.addWidget(self.work_dashboard)
        self.stack.addWidget(self.general_dashboard)
        root.addWidget(self.stack, 1)

        self.work_dashboard.bd_limpiada.connect(self.bd_limpiada.emit)
        self.general_dashboard.bd_limpiada.connect(self.bd_limpiada.emit)
        self.mode_group.idClicked.connect(self._set_mode)

        default_index = self._default_index()
        self.mode_group.button(default_index).setChecked(True)
        self._set_mode(default_index)

    def _mode_button(self, text: str, index: int) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumWidth(128)
        button.setStyleSheet(
            """
            QToolButton {
                background: #f8fafc;
                color: #64748b;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 7px 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QToolButton:hover {
                color: #1e293b;
                border-color: #94a3b8;
            }
            QToolButton:checked {
                background: #2563eb;
                color: #ffffff;
                border-color: #2563eb;
                font-weight: 600;
            }
            """
        )
        self.mode_group.addButton(button, index)
        return button

    def _default_index(self) -> int:
        role = str(getattr(self._session, "role", "") or "").strip().lower()
        return self.WORK_INDEX if role == "ejecutivo" else self.GENERAL_INDEX

    def _set_mode(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == self.WORK_INDEX:
            self.mode_description.setText("Prioridades, canales disponibles y acciones para la gestión diaria")
        else:
            self.mode_description.setText("Visión consolidada de cartera, cobertura y productividad")

    def refrescar(self) -> None:
        """Mantiene la interfaz pública usada por el resto de la aplicación."""
        self.work_dashboard.refrescar()
        self.general_dashboard.refrescar()
