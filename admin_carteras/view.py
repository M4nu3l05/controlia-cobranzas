from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from PyQt6.QtCore import QDateTime, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFrame,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from auth.auth_db import ROLES, get_all_users
from auth.auth_service import (
    list_users,
    backend_clear_all_deudores,
    backend_clear_all_gestiones,
    backend_clear_all_gestiones_con_estado,
    backend_clear_empresa_deudores_con_estado,
    backend_delete_deudor_individual,
    backend_list_cartera_asignaciones,
    backend_list_customer_change_audit,
    backend_create_replacement,
    backend_end_replacement,
    backend_list_replacements,
    backend_save_cartera_asignaciones,
)
from comisiones.service import guardar_tasas as guardar_tasas_comision, obtener_tasas as obtener_tasas_comision
from core.paths import get_data_dir
from core.db_migrations import Migration, apply_migrations
from core.excel_export import write_excel_report
from deudores.database import EMPRESAS, limpiar_empresa, limpiar_todas, eliminar_deudor_individual
from deudores.gestiones_db import limpiar_gestiones, limpiar_gestiones_por_ruts
from .data_operations import CarteraDataOperationsPanel


def _m1_create_assignment_teams(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS cartera_asignaciones (
            empresa TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            email TEXT,
            username TEXT,
            updated_at TEXT,
            updated_by TEXT,
            PRIMARY KEY (empresa, user_id)
        )
    """)


def _m2_migrate_assignment_teams(con: sqlite3.Connection) -> None:
    columns = con.execute("PRAGMA table_info(cartera_asignaciones)").fetchall()
    names = {str(row[1]) for row in columns}
    primary = {str(row[1]) for row in columns if int(row[5] or 0) > 0}
    if "is_primary" in names and primary == {"empresa", "user_id"}:
        return
    con.execute("ALTER TABLE cartera_asignaciones RENAME TO cartera_asignaciones_legacy_v2")
    _m1_create_assignment_teams(con)
    con.execute("""
        INSERT INTO cartera_asignaciones(
            empresa, user_id, is_primary, email, username, updated_at, updated_by
        )
        SELECT empresa, user_id, 1, email, username, updated_at, updated_by
        FROM cartera_asignaciones_legacy_v2
        WHERE user_id IS NOT NULL
    """)
    con.execute("DROP TABLE cartera_asignaciones_legacy_v2")


_ASSIGNMENT_MIGRATIONS = [
    Migration(1, "Create portfolio assignment teams", _m1_create_assignment_teams),
    Migration(2, "Migrate portfolio assignments to teams", _m2_migrate_assignment_teams),
]


class _CheckableUserCombo(QComboBox):
    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.setModel(QStandardItemModel(self))
        self.view().pressed.connect(self._toggle_item)
        self._update_summary()

    def set_users(self, users: list[dict]) -> None:
        model = self.model()
        model.clear()
        for user in users:
            item = QStandardItem(f"{user.get('username', '')} · {user.get('email', '')}")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
            item.setData(dict(user), Qt.ItemDataRole.UserRole)
            model.appendRow(item)
        self._update_summary()

    def selected_users(self) -> list[dict]:
        selected: list[dict] = []
        model = self.model()
        for row in range(model.rowCount()):
            item = model.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict):
                    selected.append(dict(data))
        return selected

    def set_selected_ids(self, user_ids: set[int]) -> None:
        model = self.model()
        for row in range(model.rowCount()):
            item = model.item(row)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            checked = int(data.get("id", 0) or 0) in user_ids
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._update_summary()
        self.selectionChanged.emit()

    def _toggle_item(self, index) -> None:
        item = self.model().itemFromIndex(index)
        if item is None:
            return
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        self._update_summary()
        self.selectionChanged.emit()

    def _update_summary(self) -> None:
        names = [str(user.get("username", "")).strip() for user in self.selected_users()]
        if not names:
            text = "— Sin asignación —"
        elif len(names) <= 2:
            text = ", ".join(names)
        else:
            text = f"{len(names)} supervisores seleccionados"
        self.lineEdit().setText(text)


class _AdminInitialLoadWorker(QThread):
    completed = pyqtSignal(object)

    def __init__(self, loaders: dict[str, object], parent=None):
        super().__init__(parent)
        self._loaders = dict(loaders)

    def run(self) -> None:
        results = {}
        with ThreadPoolExecutor(max_workers=max(1, len(self._loaders))) as pool:
            pending = {pool.submit(loader): name for name, loader in self._loaders.items()}
            for future in as_completed(pending):
                name = pending[future]
                try:
                    results[name] = {"value": future.result(), "error": ""}
                except Exception as exc:
                    results[name] = {"value": None, "error": str(exc)}
        self.completed.emit(results)


class _AdminActionWorker(QThread):
    completed = pyqtSignal(object, str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            result, error = self._operation()
        except Exception as exc:
            result, error = None, str(exc)
        self.completed.emit(result, str(error or ""))


class AdminCarterasWidget(QWidget):
    datos_actualizados = pyqtSignal()
    bd_limpiada = pyqtSignal(list)

    def __init__(self, session=None, parent=None):
        super().__init__(parent)
        self._session = session
        self._cards_stacked = False
        self._users_cache: list[dict] = []
        self._initial_worker: _AdminInitialLoadWorker | None = None
        self._clear_empresa_worker: _AdminActionWorker | None = None
        self._clear_gestiones_worker: _AdminActionWorker | None = None

        self._combos_asignacion: dict[str, _CheckableUserCombo] = {}
        self._combos_titular: dict[str, QComboBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        root.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)

        body = QVBoxLayout(content)
        body.setContentsMargins(18, 18, 18, 18)
        body.setSpacing(14)

        header = self._build_header()
        body.addWidget(header)

        self.data_operations = CarteraDataOperationsPanel(session=session, parent=self)
        self.data_operations.datos_actualizados.connect(self.datos_actualizados.emit)
        self.data_operations.operation_state_changed.connect(self._on_data_operation_state)
        body.addWidget(self.data_operations)

        self.top_grid = QGridLayout()
        self.top_grid.setHorizontalSpacing(14)
        self.top_grid.setVerticalSpacing(14)

        self.card_limpieza = self._build_card(
            "🧹  Limpieza controlada",
            "Acciones administrativas sobre cargas, bases y gestiones.",
        )
        self.card_asignacion = self._build_card(
            "👨‍💼  Asignación de carteras",
            "",
        )

        body.addLayout(self.top_grid)
        self._update_responsive_layout(force=True)

        self._build_limpieza_ui()
        self._build_asignacion_ui()

        self.card_reemplazos = self._build_card(
            "Reemplazos temporales",
            "Otorga acceso operativo por un periodo sin compartir credenciales.",
        )
        body.addWidget(self.card_reemplazos)
        self._build_reemplazos_ui()

        self.card_log = self._build_card(
            "📋  Bitácora administrativa",
            "Registro visual de acciones ejecutadas desde este módulo.",
        )
        body.addWidget(self.card_log)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(180)
        self.txt_log.setStyleSheet(
            """
            QTextEdit {
                background:#0f172a;
                color:#e2e8f0;
                border:1px solid #1e293b;
                border-radius:14px;
                padding:10px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 9pt;
            }
            """
        )
        self.card_log.layout().addWidget(self.txt_log)

        self._append_log("Módulo listo. Cargando datos administrativos…")
        QTimer.singleShot(0, self._start_initial_load)

    def _on_data_operation_state(self, busy: bool, message: str) -> None:
        if message:
            self._append_log(message if busy else f"Finalizado: {message}")

    # ============================================================
    # DB local de asignaciones
    # ============================================================

    def _db_path(self) -> str:
        return os.path.join(str(get_data_dir()), "db_admin_carteras.sqlite")

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path())
        apply_migrations(con, _ASSIGNMENT_MIGRATIONS)
        return con

    def _limpiar_asignaciones(self) -> None:
        with self._con() as con:
            con.execute("DELETE FROM cartera_asignaciones")
            con.commit()

    def _guardar_asignaciones_empresa(
        self,
        empresa: str,
        users: list[dict],
        primary_user_id: int | None,
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated_by = getattr(self._session, "username", "Sistema")

        with self._con() as con:
            con.execute("DELETE FROM cartera_asignaciones WHERE empresa = ?", (empresa,))
            for user_data in users:
                con.execute(
                    """
                    INSERT INTO cartera_asignaciones (
                        empresa, user_id, is_primary, email, username, updated_at, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        empresa,
                        int(user_data["id"]),
                        1 if int(user_data["id"]) == int(primary_user_id or 0) else 0,
                        str(user_data.get("email", "")),
                        str(user_data.get("username", "")),
                        now,
                        updated_by,
                    ),
                )
            con.commit()

    def _obtener_asignaciones(self) -> dict[str, list[dict]]:
        with self._con() as con:
            rows = con.execute(
                """
                SELECT empresa, user_id, is_primary, email, username, updated_at, updated_by
                FROM cartera_asignaciones
                ORDER BY empresa, is_primary DESC, username
                """
            ).fetchall()

        salida: dict[str, list[dict]] = {}
        for empresa, user_id, is_primary, email, username, updated_at, updated_by in rows:
            salida.setdefault(str(empresa), []).append({
                "user_id": user_id,
                "is_primary": bool(is_primary),
                "email": email,
                "username": username,
                "updated_at": updated_at,
                "updated_by": updated_by,
            })
        return salida

    # ============================================================
    # UI
    # ============================================================

    def _build_header(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(
            """
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f172a,
                    stop:0.55 #1d4ed8,
                    stop:1 #38bdf8
                );
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.08);
            }
            QLabel { background: transparent; border: none; }
            """
        )

        lay = QVBoxLayout(w)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(4)

        lbl_kicker = QLabel("MÓDULO RESTRINGIDO")
        lbl_kicker.setStyleSheet("color: rgba(255,255,255,0.72); font-size:8pt; font-weight:800;")

        lbl_title = QLabel("Administración de carteras")
        lbl_title.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color:#ffffff;")

        role_label = "Sin sesión"
        if self._session:
            role_label = ROLES.get(self._session.role, self._session.role.capitalize())

        lbl_sub = QLabel(
            f"Usuario actual: {getattr(self._session, 'username', 'Sistema')} · Rol: {role_label}\n"
            "Aquí se concentran las acciones sensibles del sistema, con enfoque operativo y controlado."
        )
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("color: rgba(255,255,255,0.9); font-size:9.3pt;")

        lay.addWidget(lbl_kicker)
        lay.addWidget(lbl_title)
        lay.addWidget(lbl_sub)

        return w

    def _build_card(self, title: str, subtitle: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            """
            QFrame {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 18px;
            }
            QLabel { background: transparent; border: none; }
            """
        )

        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        lbl_title = QLabel(title)
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color:#0f172a;")

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#eef2f7; max-height:1px; border:none;")

        lay.addWidget(lbl_title)
        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setWordWrap(True)
            lbl_sub.setStyleSheet("color:#64748b; font-size:9pt;")
            lay.addWidget(lbl_sub)
        lay.addWidget(sep)

        return card

    def _build_action_button(self, text: str, color: str = "#0f172a") -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setMinimumHeight(42)
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background:{color};
                color:#ffffff;
                border:none;
                border-radius:12px;
                padding: 10px 14px;
                min-height: 42px;
                font-weight:700;
            }}
            QPushButton:hover {{
                background:#1e293b;
            }}
            """
        )
        return btn

    def _build_limpieza_ui(self):
        lay = self.card_limpieza.layout()

        row_empresa = QHBoxLayout()
        lbl_empresa = QLabel("Empresa:")
        lbl_empresa.setStyleSheet("color:#334155; font-weight:700;")
        self.cmb_empresa = QComboBox()
        self.cmb_empresa.addItems(EMPRESAS)
        self.cmb_empresa.setMinimumHeight(36)

        row_empresa.addWidget(lbl_empresa)
        row_empresa.addWidget(self.cmb_empresa, 1)
        lay.addLayout(row_empresa)

        row_rut = QHBoxLayout()
        lbl_rut = QLabel("RUT deudor:")
        lbl_rut.setStyleSheet("color:#334155; font-weight:700;")
        self.txt_rut_eliminar = QLineEdit()
        self.txt_rut_eliminar.setPlaceholderText("Ej: 7606634177 o 76.066.341-7")
        self.txt_rut_eliminar.setMinimumHeight(36)
        row_rut.addWidget(lbl_rut)
        row_rut.addWidget(self.txt_rut_eliminar, 1)
        lay.addLayout(row_rut)

        self.btn_eliminar_deudor = self._build_action_button("Eliminar deudor individual", "#ef4444")
        self.btn_limpiar_empresa = self._build_action_button("Limpiar base de deudores de empresa", "#dc2626")
        self.btn_limpiar_todas = self._build_action_button("Limpiar todas las cargas", "#b91c1c")
        self.btn_limpiar_gestiones = self._build_action_button("Limpiar gestiones", "#7c3aed")
        self.btn_reiniciar = self._build_action_button("Reiniciar datos de prueba", "#ea580c")
        self.btn_exportar_auditoria = self._build_action_button("Descargar auditoría de cambios", "#0369a1")

        self.btn_eliminar_deudor.clicked.connect(self._accion_eliminar_deudor_individual)
        self.btn_limpiar_empresa.clicked.connect(self._accion_limpiar_empresa)
        self.btn_limpiar_todas.clicked.connect(self._accion_limpiar_todas)
        self.btn_limpiar_gestiones.clicked.connect(self._accion_limpiar_gestiones)
        self.btn_reiniciar.clicked.connect(self._accion_reiniciar_datos_prueba)
        self.btn_exportar_auditoria.clicked.connect(self._accion_exportar_auditoria)

        lay.addWidget(self.btn_eliminar_deudor)
        lay.addWidget(self.btn_limpiar_empresa)
        lay.addWidget(self.btn_limpiar_todas)
        lay.addWidget(self.btn_limpiar_gestiones)
        lay.addWidget(self.btn_reiniciar)
        lay.addWidget(self.btn_exportar_auditoria)

    def _accion_exportar_auditoria(self):
        if not self._session or getattr(self._session, "auth_source", "") != "backend":
            QMessageBox.warning(self, "Auditoría", "La auditoría central requiere conexión al backend de pruebas.")
            return

        empresa = self.cmb_empresa.currentText().strip() if hasattr(self, "cmb_empresa") else ""
        rows, err = backend_list_customer_change_audit(self._session, empresa=empresa)
        if err:
            QMessageBox.warning(self, "Auditoría", err)
            return
        if not rows:
            QMessageBox.information(self, "Auditoría", "No existen cambios registrados para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar auditoría de cambios",
            f"auditoria_cambios_{empresa or 'todas'}.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        columns = {
            "empresa": "Cartera",
            "rut_original": "RUT",
            "field_name": "Campo",
            "old_value": "Valor anterior",
            "new_value": "Valor nuevo",
            "changed_by_username": "Modificado por",
            "changed_at": "Fecha modificación",
        }
        df = pd.DataFrame(rows).rename(columns=columns)
        visible = [name for name in columns.values() if name in df.columns]
        write_excel_report(path, {"Auditoría": df[visible]})
        QMessageBox.information(self, "Auditoría", f"Reporte guardado correctamente en:\n{path}")

    def _build_reemplazos_ui(self):
        lay = self.card_reemplazos.layout()
        form = QGridLayout()

        self.cmb_reemplazo_empresa = QComboBox()
        self.cmb_reemplazo_empresa.addItems(EMPRESAS)
        self.cmb_reemplazo_usuario = QComboBox()
        self._replacement_users: list[dict] = []
        for user in self._obtener_supervisores_activos():
            self._replacement_users.append(user)
            self.cmb_reemplazo_usuario.addItem(
                f"{user.get('username', '')} ({user.get('email', '')})",
                int(user.get("id", 0) or 0),
            )

        self.dt_reemplazo_inicio = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_reemplazo_inicio.setCalendarPopup(True)
        self.dt_reemplazo_inicio.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.dt_reemplazo_fin = QDateTimeEdit(QDateTime.currentDateTime().addDays(1))
        self.dt_reemplazo_fin.setCalendarPopup(True)
        self.dt_reemplazo_fin.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.txt_reemplazo_motivo = QLineEdit()
        self.txt_reemplazo_motivo.setPlaceholderText("Vacaciones, licencia u otro motivo")

        form.addWidget(QLabel("Cartera:"), 0, 0)
        form.addWidget(self.cmb_reemplazo_empresa, 0, 1)
        form.addWidget(QLabel("Reemplazante:"), 0, 2)
        form.addWidget(self.cmb_reemplazo_usuario, 0, 3)
        form.addWidget(QLabel("Inicio:"), 1, 0)
        form.addWidget(self.dt_reemplazo_inicio, 1, 1)
        form.addWidget(QLabel("Término:"), 1, 2)
        form.addWidget(self.dt_reemplazo_fin, 1, 3)
        form.addWidget(QLabel("Motivo:"), 2, 0)
        form.addWidget(self.txt_reemplazo_motivo, 2, 1, 1, 3)
        lay.addLayout(form)

        self.btn_crear_reemplazo = self._build_action_button("Crear reemplazo temporal", "#0f766e")
        self.btn_crear_reemplazo.clicked.connect(self._crear_reemplazo)
        lay.addWidget(self.btn_crear_reemplazo)

        self.tbl_reemplazos = QTableWidget(0, 6)
        self.tbl_reemplazos.setHorizontalHeaderLabels(
            ["Cartera", "Titular", "Reemplazante", "Inicio", "Término", "Estado"]
        )
        self.tbl_reemplazos.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_reemplazos.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_reemplazos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_reemplazos.setMinimumHeight(180)
        lay.addWidget(self.tbl_reemplazos)

        self.btn_finalizar_reemplazo = self._build_action_button("Finalizar reemplazo seleccionado", "#b45309")
        self.btn_finalizar_reemplazo.clicked.connect(self._finalizar_reemplazo)
        lay.addWidget(self.btn_finalizar_reemplazo)

    def _cargar_reemplazos(self):
        if not hasattr(self, "tbl_reemplazos"):
            return
        if not self._session or getattr(self._session, "auth_source", "") != "backend":
            self.tbl_reemplazos.setRowCount(0)
            return
        rows, err = backend_list_replacements(self._session)
        if err:
            self._append_log(f"No se pudieron cargar reemplazos: {err}")
            return
        self.tbl_reemplazos.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                row.get("empresa", ""),
                row.get("titular_username", ""),
                row.get("replacement_username", ""),
                row.get("starts_at", ""),
                row.get("ends_at", ""),
                "Activo" if bool(row.get("is_active")) else "Finalizado",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row.get("id", 0) or 0))
                    item.setData(Qt.ItemDataRole.UserRole + 1, bool(row.get("is_active")))
                self.tbl_reemplazos.setItem(index, column, item)

    def _crear_reemplazo(self):
        user_id = int(self.cmb_reemplazo_usuario.currentData() or 0)
        if not user_id:
            QMessageBox.warning(self, "Reemplazos", "Selecciona una ejecutiva reemplazante.")
            return
        _, err = backend_create_replacement(
            self._session,
            empresa=self.cmb_reemplazo_empresa.currentText().strip(),
            replacement_user_id=user_id,
            starts_at=self.dt_reemplazo_inicio.dateTime().toString(Qt.DateFormat.ISODate),
            ends_at=self.dt_reemplazo_fin.dateTime().toString(Qt.DateFormat.ISODate),
            reason=self.txt_reemplazo_motivo.text().strip(),
        )
        if err:
            QMessageBox.warning(self, "Reemplazos", err)
            return
        self.txt_reemplazo_motivo.clear()
        self._cargar_reemplazos()
        self._append_log("Reemplazo temporal creado correctamente.")

    def _finalizar_reemplazo(self):
        row = self.tbl_reemplazos.currentRow()
        if row < 0:
            QMessageBox.information(self, "Reemplazos", "Selecciona un reemplazo.")
            return
        item = self.tbl_reemplazos.item(row, 0)
        replacement_id = int(item.data(Qt.ItemDataRole.UserRole) or 0) if item else 0
        is_active = bool(item.data(Qt.ItemDataRole.UserRole + 1)) if item else False
        if not replacement_id or not is_active:
            QMessageBox.information(self, "Reemplazos", "El reemplazo ya está finalizado.")
            return
        err = backend_end_replacement(self._session, replacement_id=replacement_id)
        if err:
            QMessageBox.warning(self, "Reemplazos", err)
            return
        self._cargar_reemplazos()
        self._append_log("Reemplazo temporal finalizado.")

    def _build_asignacion_ui(self):
        lay = self.card_asignacion.layout()

        self.tbl_comisiones = QTableWidget(len(EMPRESAS), 2)
        self.tbl_comisiones.setHorizontalHeaderLabels(["Cartera", "% Comisión"])
        self.tbl_comisiones.verticalHeader().setVisible(False)
        self.tbl_comisiones.verticalHeader().setDefaultSectionSize(40)
        self.tbl_comisiones.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.tbl_comisiones.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_comisiones.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_comisiones.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_comisiones.setStyleSheet(
            """
            QTableWidget {
                background:#ffffff;
                border:1px solid #e2e8f0;
                border-radius:12px;
                gridline-color:#eef2f7;
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

        self._spins_comision = {}
        for row, empresa in enumerate(EMPRESAS):
            item = QTableWidgetItem(empresa)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_comisiones.setItem(row, 0, item)

            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setSuffix(" %")
            spin.setMinimumHeight(30)
            spin.setStyleSheet("QDoubleSpinBox { border:1px solid #cbd5e1; border-radius:8px; padding:3px 6px; }")
            self._spins_comision[empresa] = spin
            self.tbl_comisiones.setCellWidget(row, 1, spin)

        alto_filas = self.tbl_comisiones.horizontalHeader().height() + len(EMPRESAS) * 40 + 8
        self.tbl_comisiones.setFixedHeight(alto_filas)
        lay.addWidget(self.tbl_comisiones)

        info = QLabel(
            "El porcentaje se aplica sobre cada pago que la ejecutiva registra en la cartera."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#475569; font-size:9pt;")
        lay.addWidget(info)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        supervisores = self._obtener_supervisores_activos()

        grid.addWidget(QLabel("Isapre"), 0, 0)
        grid.addWidget(QLabel("Supervisores asignados"), 0, 1)
        grid.addWidget(QLabel("Titular"), 0, 2)

        for row, empresa in enumerate(EMPRESAS, start=1):
            lbl = QLabel(empresa)
            lbl.setStyleSheet("color:#0f172a; font-weight:700;")

            combo = _CheckableUserCombo()
            combo.setMinimumHeight(36)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.set_users(supervisores)

            primary_combo = QComboBox()
            primary_combo.setMinimumHeight(36)
            primary_combo.addItem("— Sin titular —", None)
            combo.selectionChanged.connect(
                lambda emp=empresa: self._sync_primary_combo(emp)
            )

            self._combos_asignacion[empresa] = combo
            self._combos_titular[empresa] = primary_combo

            grid.addWidget(lbl, row, 0)
            grid.addWidget(combo, row, 1)
            grid.addWidget(primary_combo, row, 2)

        lay.addLayout(grid)

        row_btn = QHBoxLayout()
        row_btn.addStretch(1)

        self.btn_guardar_asignaciones = self._build_action_button(
            "Guardar asignaciones y comisiones", "#059669"
        )
        self.btn_guardar_asignaciones.clicked.connect(self._accion_guardar_asignaciones)

        row_btn.addWidget(self.btn_guardar_asignaciones)
        lay.addLayout(row_btn)

    def _obtener_supervisores_activos(self) -> list[dict]:
        users = list(self._users_cache)

        salida = []
        for u in users:
            if str(u.get("role", "")).strip().lower() == "supervisor" and bool(u.get("is_active", 0)):
                salida.append(u)
        salida.sort(key=lambda x: str(x.get("username", "")).lower())
        return salida

    def _sync_primary_combo(self, empresa: str, preferred_user_id: int | None = None) -> None:
        assignment_combo = self._combos_asignacion[empresa]
        primary_combo = self._combos_titular[empresa]
        current_id = preferred_user_id if preferred_user_id is not None else primary_combo.currentData()
        selected = assignment_combo.selected_users()
        primary_combo.blockSignals(True)
        primary_combo.clear()
        primary_combo.addItem("— Sin titular —", None)
        for user in selected:
            primary_combo.addItem(
                f"{user.get('username', '')} · {user.get('email', '')}",
                int(user.get("id", 0) or 0),
            )
        target = primary_combo.findData(current_id)
        if target < 0 and len(selected) == 1:
            target = 1
        primary_combo.setCurrentIndex(max(0, target))
        primary_combo.blockSignals(False)

    def _start_initial_load(self) -> None:
        backend = bool(self._session and getattr(self._session, "auth_source", "") == "backend")
        loaders = {
            "users": (lambda: list_users(self._session)) if backend else get_all_users,
            "assignments": (
                (lambda: backend_list_cartera_asignaciones(self._session))
                if backend else self._obtener_asignaciones
            ),
            "rates": lambda: obtener_tasas_comision(self._session),
        }
        if backend:
            loaders["replacements"] = lambda: backend_list_replacements(self._session)
        self._initial_worker = _AdminInitialLoadWorker(loaders, parent=self)
        self._initial_worker.completed.connect(self._apply_initial_data)
        self._initial_worker.finished.connect(self._initial_load_finished)
        self._initial_worker.start()

    def _populate_user_selectors(self, users: list[dict]) -> None:
        self._users_cache = [dict(user) for user in users]
        supervisores = self._obtener_supervisores_activos()
        for empresa, combo in self._combos_asignacion.items():
            combo.blockSignals(True)
            combo.set_users(supervisores)
            combo.blockSignals(False)
            self._sync_primary_combo(empresa)

        self._replacement_users = list(supervisores)
        self.cmb_reemplazo_usuario.blockSignals(True)
        self.cmb_reemplazo_usuario.clear()
        for user in supervisores:
            self.cmb_reemplazo_usuario.addItem(
                f"{user.get('username', '')} ({user.get('email', '')})",
                int(user.get("id", 0) or 0),
            )
        self.cmb_reemplazo_usuario.blockSignals(False)

    def _apply_assignment_values(self, value) -> None:
        rows, err = value if isinstance(value, tuple) else (value, "")
        if err:
            self._append_log(f"Error al cargar asignaciones desde backend: {err}")
            rows = []
        if isinstance(rows, dict):
            asignaciones = {
                empresa: value if isinstance(value, list) else [value]
                for empresa, value in rows.items()
            }
        else:
            asignaciones: dict[str, list[dict]] = {}
            for row in rows or []:
                empresa = str(row.get("empresa", "")).strip()
                if empresa:
                    asignaciones.setdefault(empresa, []).append(row)
        for empresa, combo in self._combos_asignacion.items():
            data = asignaciones.get(empresa, [])
            selected_ids = {
                int(item.get("user_id", 0) or 0)
                for item in data
                if int(item.get("user_id", 0) or 0) > 0
            }
            primary_id = next(
                (int(item.get("user_id")) for item in data if item.get("is_primary") and item.get("user_id")),
                None,
            )
            combo.set_selected_ids(selected_ids)
            self._sync_primary_combo(empresa, primary_id)

    def _apply_rate_values(self, value) -> None:
        tasas, err = value if isinstance(value, tuple) else (value, "")
        if err:
            self._append_log(f"Error al cargar porcentajes de comisión: {err}")
            return
        normalizadas = {self._clave_empresa(empresa): valor for empresa, valor in (tasas or {}).items()}
        for empresa, spin in self._spins_comision.items():
            spin.setValue(float(normalizadas.get(self._clave_empresa(empresa), 0.0) or 0.0))

    def _apply_replacement_values(self, value) -> None:
        rows, err = value if isinstance(value, tuple) else (value, "")
        if err:
            self._append_log(f"No se pudieron cargar reemplazos: {err}")
            return
        self.tbl_reemplazos.setRowCount(len(rows or []))
        for index, row in enumerate(rows or []):
            values = [
                row.get("empresa", ""), row.get("titular_username", ""),
                row.get("replacement_username", ""), row.get("starts_at", ""),
                row.get("ends_at", ""), "Activo" if bool(row.get("is_active")) else "Finalizado",
            ]
            for column, cell_value in enumerate(values):
                item = QTableWidgetItem(str(cell_value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row.get("id", 0) or 0))
                    item.setData(Qt.ItemDataRole.UserRole + 1, bool(row.get("is_active")))
                self.tbl_reemplazos.setItem(index, column, item)

    def _apply_initial_data(self, results: dict) -> None:
        users_result = results.get("users", {})
        if users_result.get("error"):
            self._append_log(f"No fue posible cargar usuarios: {users_result['error']}")
        else:
            self._populate_user_selectors(users_result.get("value") or [])

        assignments = results.get("assignments", {})
        if assignments.get("error"):
            self._append_log(f"No fue posible cargar asignaciones: {assignments['error']}")
        else:
            self._apply_assignment_values(assignments.get("value"))

        rates = results.get("rates", {})
        if rates.get("error"):
            self._append_log(f"No fue posible cargar comisiones: {rates['error']}")
        else:
            self._apply_rate_values(rates.get("value"))

        replacements = results.get("replacements")
        if replacements:
            if replacements.get("error"):
                self._append_log(f"No fue posible cargar reemplazos: {replacements['error']}")
            else:
                self._apply_replacement_values(replacements.get("value"))
        self._append_log("Datos administrativos cargados.")

    def _initial_load_finished(self) -> None:
        worker = self._initial_worker
        self._initial_worker = None
        if worker is not None:
            worker.deleteLater()

    def _cargar_asignaciones(self):
        if self._session and getattr(self._session, "auth_source", "") == "backend":
            asignaciones_rows, err = backend_list_cartera_asignaciones(self._session)
            self._apply_assignment_values((asignaciones_rows, err))
        else:
            self._apply_assignment_values(self._obtener_asignaciones())

        self._cargar_comisiones()

    def _cargar_comisiones(self):
        tasas, err = obtener_tasas_comision(self._session)
        if err:
            self._append_log(f"Error al cargar los porcentajes de comisión: {err}")
            return

        normalizadas = {self._clave_empresa(empresa): valor for empresa, valor in tasas.items()}
        for empresa, spin in self._spins_comision.items():
            spin.blockSignals(True)
            spin.setValue(float(normalizadas.get(self._clave_empresa(empresa), 0.0) or 0.0))
            spin.blockSignals(False)

    @staticmethod
    def _clave_empresa(valor: str) -> str:
        return "".join(ch for ch in str(valor or "").strip().lower() if ch.isalnum())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _update_responsive_layout(self, force: bool = False) -> None:
        stacked = self.width() < 1220
        if not force and stacked == self._cards_stacked:
            return
        self._cards_stacked = stacked

        self.top_grid.removeWidget(self.card_limpieza)
        self.top_grid.removeWidget(self.card_asignacion)

        if stacked:
            self.top_grid.addWidget(self.card_limpieza, 0, 0)
            self.top_grid.addWidget(self.card_asignacion, 1, 0)
            self.top_grid.setColumnStretch(0, 1)
            self.top_grid.setColumnStretch(1, 0)
        else:
            self.top_grid.addWidget(self.card_limpieza, 0, 0)
            self.top_grid.addWidget(self.card_asignacion, 0, 1)
            self.top_grid.setColumnStretch(0, 1)
            self.top_grid.setColumnStretch(1, 1)

    # ============================================================
    # Acciones
    # ============================================================

    def _confirmar(self, titulo: str, texto: str) -> bool:
        resp = QMessageBox.question(
            self,
            titulo,
            texto,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return resp == QMessageBox.StandardButton.Yes

    def _append_log(self, texto: str):
        stamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.txt_log.append(f"[{stamp}] {texto}")

    def _limpiar_base_local_empresa(self, empresa: str) -> bool:
        try:
            return limpiar_empresa(empresa)
        except Exception:
            return False

    def _limpiar_bases_locales(self) -> list[str]:
        try:
            return limpiar_todas()
        except Exception:
            return []

    def _limpiar_gestiones_locales(self) -> bool:
        try:
            return limpiar_gestiones()
        except Exception:
            return False

    def _normalizar_rut(self, rut: str) -> str:
        txt = str(rut or "").strip().replace(".", "")
        if "-" in txt:
            txt = txt.split("-", 1)[0]
        return txt.replace("-", "").lstrip("0")

    def _accion_eliminar_deudor_individual(self):
        empresa = self.cmb_empresa.currentText().strip()
        rut_input = self.txt_rut_eliminar.text().strip() if hasattr(self, "txt_rut_eliminar") else ""
        rut_norm = self._normalizar_rut(rut_input)

        if not empresa:
            QMessageBox.warning(self, "Dato requerido", "Debes seleccionar una empresa.")
            return
        if not rut_norm:
            QMessageBox.warning(self, "Dato requerido", "Debes ingresar un RUT válido del deudor.")
            return

        if not self._confirmar(
            "Confirmar eliminación individual",
            (
                f"Se eliminará el registro completo del deudor '{rut_input}' en la empresa '{empresa}'.\n"
                "Esta acción borra el deudor de la base de deudores y sus gestiones asociadas.\n\n"
                "¿Deseas continuar?"
            ),
        ):
            return

        ok = False
        backend_msg = ""
        if self._session and getattr(self._session, "auth_source", "") == "backend":
            backend_msg = backend_delete_deudor_individual(
                self._session,
                empresa=empresa,
                rut=rut_input,
            )
            ok = bool(backend_msg) and ("Se eliminó" in backend_msg or "No existían" in backend_msg)

            # Mantiene espejo local consistente aunque el origen sea backend.
            local_deleted = eliminar_deudor_individual(empresa, rut_input)
            _ = limpiar_gestiones_por_ruts([rut_input])
            ok = ok or local_deleted
        else:
            local_deleted = eliminar_deudor_individual(empresa, rut_input)
            gest_deleted = limpiar_gestiones_por_ruts([rut_input])
            ok = bool(local_deleted or gest_deleted)

        if ok:
            self._append_log(f"Eliminación individual ejecutada: empresa={empresa}, rut={rut_input}")
            self.bd_limpiada.emit([empresa])
            self.datos_actualizados.emit()
            if hasattr(self, "txt_rut_eliminar"):
                self.txt_rut_eliminar.clear()
            QMessageBox.information(
                self,
                "Proceso completado",
                backend_msg or f"✅ Se eliminó el deudor {rut_input} de la empresa {empresa}.",
            )
        else:
            QMessageBox.warning(
                self,
                "Sin cambios",
                backend_msg or "No se encontró el deudor indicado o no se pudo completar la eliminación.",
            )

    def _accion_limpiar_empresa(self):
        if self._clear_empresa_worker is not None:
            return
        empresa = self.cmb_empresa.currentText().strip()
        if not empresa:
            return

        if not self._confirmar(
            "Confirmar limpieza",
            f"Se eliminarán todos los registros cargados de la empresa '{empresa}'.\n\n¿Deseas continuar?",
        ):
            return

        uses_backend = bool(
            self._session and getattr(self._session, "auth_source", "") == "backend"
        )

        def operation():
            message = ""
            if uses_backend:
                message, error = backend_clear_empresa_deudores_con_estado(
                    self._session,
                    empresa=empresa,
                )
                if error:
                    return None, error
                self._limpiar_base_local_empresa(empresa)
                return {"message": message, "empresa": empresa}, ""
            if not self._limpiar_base_local_empresa(empresa):
                return None, f"No se pudo limpiar la base de {empresa} o no existían datos."
            return {"message": "", "empresa": empresa}, ""

        self.btn_limpiar_empresa.setEnabled(False)
        self.btn_limpiar_empresa.setText("Eliminando base…")
        self._append_log(f"Eliminación de base iniciada para {empresa}…")
        worker = _AdminActionWorker(operation, self)
        self._clear_empresa_worker = worker
        worker.completed.connect(self._on_limpiar_empresa_completed)
        worker.finished.connect(lambda: self._release_clear_empresa_worker(worker))
        worker.start()

    def _release_clear_empresa_worker(self, worker: _AdminActionWorker) -> None:
        if self._clear_empresa_worker is worker:
            self._clear_empresa_worker = None
        worker.deleteLater()

    def _on_limpiar_empresa_completed(self, result: object, error: str) -> None:
        self.btn_limpiar_empresa.setEnabled(True)
        self.btn_limpiar_empresa.setText("Limpiar base de deudores de empresa")
        if error:
            self._append_log(f"No se pudo eliminar la base: {error}")
            QMessageBox.warning(self, "Sin cambios", error)
            return
        payload = result if isinstance(result, dict) else {}
        empresa = str(payload.get("empresa", "")).strip()
        message = str(payload.get("message", "")).strip()
        self._append_log(f"Base de deudores limpiada para la empresa: {empresa}")
        self.bd_limpiada.emit([empresa])
        self.datos_actualizados.emit()
        QMessageBox.information(
            self,
            "Proceso completado",
            message or f"✅ Base limpiada para {empresa}.",
        )

    def _accion_limpiar_todas(self):
        if not self._confirmar(
            "Confirmar limpieza total",
            "Se eliminarán todas las cargas de deudores de todas las empresas.\n\n¿Deseas continuar?",
        ):
            return

        if self._session and getattr(self._session, "auth_source", "") == "backend":
            msg = backend_clear_all_deudores(self._session)
            if not msg:
                QMessageBox.warning(self, "Sin cambios", "No se pudo ejecutar la limpieza total de cargas.")
                return
            empresas = list(set(self._limpiar_bases_locales()) | set(EMPRESAS))
        else:
            empresas = self._limpiar_bases_locales()
        self._append_log(f"Limpieza total de cargas ejecutada. Empresas afectadas: {', '.join(empresas) if empresas else 'ninguna'}")
        self.bd_limpiada.emit(empresas)
        self.datos_actualizados.emit()
        QMessageBox.information(self, "Proceso completado", "✅ Se ejecutó la limpieza total de cargas.")

    def _accion_limpiar_gestiones(self):
        if self._clear_gestiones_worker is not None:
            return
        if not self._confirmar(
            "Confirmar limpieza de gestiones",
            "Se eliminarán todas las gestiones registradas en el sistema.\n\n¿Deseas continuar?",
        ):
            return

        uses_backend = bool(
            self._session and getattr(self._session, "auth_source", "") == "backend"
        )

        def operation():
            message = ""
            if uses_backend:
                message, error = backend_clear_all_gestiones_con_estado(self._session)
                if error:
                    return None, error
            local_ok = self._limpiar_gestiones_locales()
            if not local_ok:
                return None, "No se pudo limpiar la copia local de gestiones."
            return {"message": message}, ""

        self.btn_limpiar_gestiones.setEnabled(False)
        self.btn_limpiar_gestiones.setText("Eliminando gestiones…")
        self._append_log("Eliminación completa de gestiones iniciada…")
        worker = _AdminActionWorker(operation, self)
        self._clear_gestiones_worker = worker
        worker.completed.connect(self._on_limpiar_gestiones_completed)
        worker.finished.connect(lambda: self._release_clear_gestiones_worker(worker))
        worker.start()

    def _release_clear_gestiones_worker(self, worker: _AdminActionWorker) -> None:
        if self._clear_gestiones_worker is worker:
            self._clear_gestiones_worker = None
        worker.deleteLater()

    def _on_limpiar_gestiones_completed(self, result: object, error: str) -> None:
        self.btn_limpiar_gestiones.setEnabled(True)
        self.btn_limpiar_gestiones.setText("Limpiar gestiones")
        if error:
            self._append_log(f"No se pudieron eliminar las gestiones: {error}")
            QMessageBox.warning(self, "No se completó la eliminación", error)
            return
        self._append_log("Gestiones eliminadas correctamente.")
        self.datos_actualizados.emit()
        message = str((result or {}).get("message", "")).strip() if isinstance(result, dict) else ""
        QMessageBox.information(
            self,
            "Proceso completado",
            message or "✅ Gestiones eliminadas correctamente.",
        )

    def _accion_reiniciar_datos_prueba(self):
        if not self._confirmar(
            "Confirmar reinicio",
            "Esto limpiará:\n"
            "• cargas de deudores\n"
            "• gestiones\n"
            "• asignaciones de cartera\n\n"
            "¿Deseas continuar?",
        ):
            return

        if self._session and getattr(self._session, "auth_source", "") == "backend":
            msg_deu = backend_clear_all_deudores(self._session)
            empresas = list(set(self._limpiar_bases_locales()) | set(EMPRESAS)) if msg_deu else self._limpiar_bases_locales()
            ok_gest = bool(backend_clear_all_gestiones(self._session))
            self._limpiar_gestiones_locales()
            _, err = backend_save_cartera_asignaciones(self._session, assignments=[])
            if err:
                self._append_log(f"Error al reiniciar asignaciones backend: {err}")
            self._limpiar_asignaciones()
        else:
            empresas = self._limpiar_bases_locales()
            ok_gest = self._limpiar_gestiones_locales()
            self._limpiar_asignaciones()
        self._cargar_asignaciones()
        self._cargar_reemplazos()

        self._append_log(
            "Reinicio de datos de prueba ejecutado. "
            f"Empresas limpiadas: {', '.join(empresas) if empresas else 'ninguna'} | "
            f"Gestiones limpiadas: {'sí' if ok_gest else 'no'} | Asignaciones reiniciadas: sí"
        )
        self.bd_limpiada.emit(empresas)
        self.datos_actualizados.emit()
        QMessageBox.information(self, "Proceso completado", "✅ Datos de prueba reiniciados correctamente.")

    def _accion_guardar_asignaciones(self):
        cambios = 0
        assignments: list[dict] = []
        values_by_company: dict[str, tuple[list[dict], int | None]] = {}
        for empresa, combo in self._combos_asignacion.items():
            selected = combo.selected_users()
            primary_id = self._combos_titular[empresa].currentData()
            selected_ids = {int(user.get("id", 0) or 0) for user in selected}
            if selected and int(primary_id or 0) not in selected_ids:
                QMessageBox.warning(
                    self,
                    "Falta supervisor titular",
                    f"Selecciona un supervisor titular para {empresa}.",
                )
                return
            values_by_company[empresa] = (selected, int(primary_id) if primary_id else None)
            if not selected:
                assignments.append({"empresa": empresa, "user_id": None, "is_primary": False})
            else:
                assignments.extend(
                    {
                        "empresa": empresa,
                        "user_id": int(user["id"]),
                        "is_primary": int(user["id"]) == int(primary_id),
                    }
                    for user in selected
                )
            cambios += 1

        if self._session and getattr(self._session, "auth_source", "") == "backend":
            _, err = backend_save_cartera_asignaciones(self._session, assignments=assignments)
            if err:
                self._append_log(f"Error al guardar asignaciones backend: {err}")
                QMessageBox.warning(self, "Error al guardar", err)
                return

            # Mantiene espejo local para consultas de UI en modo escritorio.
            self._limpiar_asignaciones()
            for empresa, (selected, primary_id) in values_by_company.items():
                self._guardar_asignaciones_empresa(empresa, selected, primary_id)
        else:
            for empresa, (selected, primary_id) in values_by_company.items():
                self._guardar_asignaciones_empresa(empresa, selected, primary_id)

        tasas = {empresa: float(spin.value()) for empresa, spin in self._spins_comision.items()}
        err_comision = guardar_tasas_comision(self._session, tasas)
        if err_comision:
            self._append_log(f"Error al guardar los porcentajes de comisión: {err_comision}")
            QMessageBox.warning(
                self,
                "Comisiones no guardadas",
                f"Las asignaciones se guardaron, pero los porcentajes de comisión no:\n\n{err_comision}",
            )
            self.datos_actualizados.emit()
            return

        self._append_log(
            f"Asignaciones de cartera guardadas ({cambios} compañías procesadas) "
            f"y porcentajes de comisión actualizados."
        )
        self.datos_actualizados.emit()
        QMessageBox.information(
            self,
            "Asignaciones guardadas",
            "✅ Asignaciones de cartera y porcentajes de comisión guardados correctamente.",
        )
