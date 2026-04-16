from __future__ import annotations

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from .database import EMPRESAS
from admin_carteras.service import obtener_empresas_asignadas_para_session, session_tiene_restriccion_por_cartera
from .ui_components import Card


class DeudoresSidebar(QWidget):
    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        _is_ejecutivo = session_tiene_restriccion_por_cartera(session)
        empresas_asignadas = obtener_empresas_asignadas_para_session(session) if _is_ejecutivo else list(EMPRESAS)
        empresas_sidebar = empresas_asignadas or list(EMPRESAS)

        left_layout = QVBoxLayout(self)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(14)

        self.card_carga = Card("Cargar base de deudores")
        emp_row = QHBoxLayout()
        emp_row.setSpacing(8)
        emp_row.addWidget(QLabel("Compañía:"))

        self.cmb_empresa = QComboBox()
        self.cmb_empresa.addItems(empresas_sidebar)
        self.cmb_empresa.setMinimumHeight(36)
        emp_row.addWidget(self.cmb_empresa, 1)
        self.card_carga.body.addLayout(emp_row)

        row_path = QHBoxLayout()
        row_path.setSpacing(8)

        self.txt_excel = QLineEdit()
        self.txt_excel.setPlaceholderText("Selecciona el archivo Excel (.xlsx)…")
        self.txt_excel.setReadOnly(True)
        self.txt_excel.setMinimumHeight(38)
        row_path.addWidget(self.txt_excel, 1)

        self.btn_pick = QPushButton("Seleccionar…")
        self.btn_pick.setMinimumWidth(110)
        self.btn_pick.setMinimumHeight(38)
        row_path.addWidget(self.btn_pick)

        self.card_carga.body.addLayout(row_path)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.card_carga.body.addWidget(self.progress)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_cargar = QPushButton("Cargar base")
        self.btn_cargar.setObjectName("PrimaryButton")
        self.btn_cargar.setEnabled(True)
        self.btn_cargar.setMinimumHeight(42)
        btn_row.addWidget(self.btn_cargar, 1)

        self.card_carga.body.addLayout(btn_row)
        self.card_carga.setVisible(not _is_ejecutivo)
        left_layout.addWidget(self.card_carga)

        self.card_gest = Card("Base de gestiones")
        row_gest = QHBoxLayout()
        row_gest.setSpacing(8)

        self.txt_gest_excel = QLineEdit()
        self.txt_gest_excel.setPlaceholderText("Selecciona el archivo de gestiones…")
        self.txt_gest_excel.setReadOnly(True)
        self.txt_gest_excel.setMinimumHeight(38)
        row_gest.addWidget(self.txt_gest_excel, 1)

        self.btn_pick_gest = QPushButton("Seleccionar…")
        self.btn_pick_gest.setMinimumWidth(110)
        self.btn_pick_gest.setMinimumHeight(38)
        row_gest.addWidget(self.btn_pick_gest)

        self.card_gest.body.addLayout(row_gest)

        self.progress_gest = QProgressBar()
        self.progress_gest.setVisible(False)
        self.card_gest.body.addWidget(self.progress_gest)

        btn_gest_row = QHBoxLayout()
        btn_gest_row.setSpacing(10)

        self.btn_descargar_plantilla_gest = QPushButton("📥  Descargar plantilla")
        self.btn_descargar_plantilla_gest.setObjectName("GhostButton")
        self.btn_descargar_plantilla_gest.setEnabled(True)
        self.btn_descargar_plantilla_gest.setMinimumHeight(42)
        btn_gest_row.addWidget(self.btn_descargar_plantilla_gest, 1)

        self.btn_cargar_gest = QPushButton("📋  Cargar gestiones")
        self.btn_cargar_gest.setObjectName("PrimaryButton")
        self.btn_cargar_gest.setEnabled(True)
        self.btn_cargar_gest.setMinimumHeight(42)
        btn_gest_row.addWidget(self.btn_cargar_gest, 1)

        self.card_gest.body.addLayout(btn_gest_row)
        self.card_gest.setVisible(not _is_ejecutivo)
        left_layout.addWidget(self.card_gest)

        self.card_descarga_gest = Card(
            "Descargar base de gestiones",
            "Descarga todas las gestiones o filtra por un rango de fechas."
        )

        self.chk_descarga_completa = QCheckBox("Descargar base completa")
        self.chk_descarga_completa.setChecked(True)
        self.card_descarga_gest.body.addWidget(self.chk_descarga_completa)

        rango_row = QHBoxLayout()
        rango_row.setSpacing(8)
        rango_row.addWidget(QLabel("Desde:"))

        self.date_desde = QDateEdit()
        self.date_desde.setCalendarPopup(True)
        self.date_desde.setDisplayFormat("dd/MM/yyyy")
        self.date_desde.setDate(QDate.currentDate().addMonths(-1))
        self.date_desde.setEnabled(False)
        self.date_desde.setMinimumHeight(34)
        rango_row.addWidget(self.date_desde, 1)

        rango_row.addWidget(QLabel("Hasta:"))

        self.date_hasta = QDateEdit()
        self.date_hasta.setCalendarPopup(True)
        self.date_hasta.setDisplayFormat("dd/MM/yyyy")
        self.date_hasta.setDate(QDate.currentDate())
        self.date_hasta.setEnabled(False)
        self.date_hasta.setMinimumHeight(34)
        rango_row.addWidget(self.date_hasta, 1)

        self.card_descarga_gest.body.addLayout(rango_row)

        row_btn_descarga = QHBoxLayout()
        self.btn_descargar_gestiones = QPushButton("📥  Descargar Excel")
        self.btn_descargar_gestiones.setObjectName("PrimaryButton")
        self.btn_descargar_gestiones.setMinimumHeight(42)
        row_btn_descarga.addWidget(self.btn_descargar_gestiones, 1)
        self.card_descarga_gest.body.addLayout(row_btn_descarga)
        self.card_descarga_gest.setVisible(not _is_ejecutivo)

        left_layout.addWidget(self.card_descarga_gest)

        self.card_busq = Card("Búsqueda y filtros")

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍  Escribe para buscar…")
        self.txt_search.setEnabled(False)
        self.txt_search.setMinimumHeight(38)
        search_row.addWidget(self.txt_search, 1)

        self.btn_cls = QToolButton()
        self.btn_cls.setText("✕")
        self.btn_cls.setMinimumSize(34, 34)
        search_row.addWidget(self.btn_cls)

        self.card_busq.body.addLayout(search_row)

        flt_emp_row = QHBoxLayout()
        flt_emp_row.setSpacing(8)
        flt_emp_row.addWidget(QLabel("Compañía:"))

        self.cmb_filtro_empresa = QComboBox()
        self.cmb_filtro_empresa.addItem("Todas")
        self.cmb_filtro_empresa.addItems(empresas_sidebar)
        self.cmb_filtro_empresa.setEnabled(False)
        self.cmb_filtro_empresa.setMinimumHeight(36)
        flt_emp_row.addWidget(self.cmb_filtro_empresa, 1)
        self.card_busq.body.addLayout(flt_emp_row)

        col_row = QHBoxLayout()
        col_row.setSpacing(8)
        col_row.addWidget(QLabel("Columna:"))

        self.cmb_col = QComboBox()
        self.cmb_col.addItem("Todas las columnas")
        self.cmb_col.setEnabled(False)
        self.cmb_col.setMinimumHeight(36)
        col_row.addWidget(self.cmb_col, 1)
        self.card_busq.body.addLayout(col_row)

        self.lbl_resultados = QLabel("—")
        self.lbl_resultados.setObjectName("MutedLabel")
        self.card_busq.body.addWidget(self.lbl_resultados)
        left_layout.addWidget(self.card_busq)

        self.card_tareas = Card(
            "Gestiones asignadas",
            "Solo para ejecutivos. Marca como realizada cuando finalices la gestión.",
        )
        self.tbl_tareas = QTableWidget(0, 3)
        self.tbl_tareas.setHorizontalHeaderLabels(["Realizada", "RUT", "Nombre"])
        self.tbl_tareas.verticalHeader().setVisible(False)
        self.tbl_tareas.setAlternatingRowColors(True)
        self.tbl_tareas.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_tareas.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_tareas.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_tareas.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_tareas.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_tareas.setMinimumHeight(220)
        self.card_tareas.body.addWidget(self.tbl_tareas)

        row_tareas = QHBoxLayout()
        row_tareas.setSpacing(8)
        self.btn_refrescar_tareas = QPushButton("🔄 Actualizar")
        self.btn_refrescar_tareas.setObjectName("GhostButton")
        self.btn_refrescar_tareas.setMinimumHeight(38)
        row_tareas.addWidget(self.btn_refrescar_tareas, 1)

        self.btn_marcar_tareas = QPushButton("✅ Gestión realizada")
        self.btn_marcar_tareas.setObjectName("PrimaryButton")
        self.btn_marcar_tareas.setMinimumHeight(38)
        row_tareas.addWidget(self.btn_marcar_tareas, 1)
        self.card_tareas.body.addLayout(row_tareas)
        self.card_tareas.setVisible(_is_ejecutivo)
        left_layout.addWidget(self.card_tareas)

        left_layout.addStretch(1)


class DeudoresTablePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card_tabla = Card(
            "Base de deudores",
            "Doble clic en una fila para ver el detalle completo del deudor.",
        )
        card_tabla.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.lbl_placeholder = QLabel("Carga un archivo Excel para visualizar la base de deudores.")
        self.lbl_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_placeholder.setObjectName("MutedLabel")
        self.lbl_placeholder.setFont(QFont("Segoe UI", 11))

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.setVisible(False)
        self.table.setMinimumWidth(280)

        card_tabla.body.addWidget(self.lbl_placeholder)
        card_tabla.body.addWidget(self.table, 1)
        layout.addWidget(card_tabla, 1)


def build_splitter_layout(parent: QWidget, session=None) -> tuple[QVBoxLayout, QLabel, QSplitter, DeudoresSidebar, DeudoresTablePanel]:
    root = QVBoxLayout(parent)
    root.setContentsMargins(14, 14, 14, 14)
    root.setSpacing(12)

    header = QHBoxLayout()
    title = QLabel("Búsqueda de Deudores")
    title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
    header.addWidget(title)
    header.addStretch(1)

    lbl_total = QLabel("Sin base cargada")
    lbl_total.setObjectName("HeaderHint")
    header.addWidget(lbl_total)
    root.addLayout(header)

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(8)
    splitter.setOpaqueResize(False)
    root.addWidget(splitter, 1)

    left_scroll = QScrollArea()
    left_scroll.setWidgetResizable(True)
    left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    left_scroll.setFrameShape(QFrame.Shape.NoFrame)
    left_scroll.setMinimumWidth(220)
    left_scroll.setMaximumWidth(520)
    left_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    sidebar = DeudoresSidebar(session=session)
    sidebar.setMinimumWidth(200)
    sidebar.setMaximumWidth(500)

    right = DeudoresTablePanel()
    right.setMinimumWidth(300)
    right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    left_scroll.setWidget(sidebar)

    splitter.addWidget(left_scroll)
    splitter.addWidget(right)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)

    return root, lbl_total, splitter, sidebar, right
