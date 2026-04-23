from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from auth.auth_db import ROLES, get_all_users
from auth.auth_service import (
    list_users,
    backend_clear_all_deudores,
    backend_clear_all_gestiones,
    backend_clear_empresa_deudores,
    backend_delete_deudor_individual,
    backend_list_cartera_asignaciones,
    backend_save_cartera_asignaciones,
)
from core.paths import get_data_dir
from deudores.database import EMPRESAS, limpiar_empresa, limpiar_todas, eliminar_deudor_individual
from deudores.gestiones_db import limpiar_gestiones, limpiar_gestiones_por_ruts


class AdminCarterasWidget(QWidget):
    datos_actualizados = pyqtSignal()
    bd_limpiada = pyqtSignal(list)

    def __init__(self, session=None, parent=None):
        super().__init__(parent)
        self._session = session
        self._cards_stacked = False

        self._combos_asignacion: dict[str, QComboBox] = {}

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

        self.top_grid = QGridLayout()
        self.top_grid.setHorizontalSpacing(14)
        self.top_grid.setVerticalSpacing(14)

        self.card_limpieza = self._build_card(
            "🧹  Limpieza controlada",
            "Acciones administrativas sobre cargas, bases y gestiones.",
        )
        self.card_asignacion = self._build_card(
            "👨‍💼  Asignación de carteras",
            "Asigna una empresa a un ejecutivo responsable.",
        )

        body.addLayout(self.top_grid)
        self._update_responsive_layout(force=True)

        self._build_limpieza_ui()
        self._build_asignacion_ui()

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

        self._cargar_asignaciones()
        self._append_log("Módulo de Administración de carteras listo.")

    # ============================================================
    # DB local de asignaciones
    # ============================================================

    def _db_path(self) -> str:
        return os.path.join(str(get_data_dir()), "db_admin_carteras.sqlite")

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path())
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS cartera_asignaciones (
                empresa TEXT PRIMARY KEY,
                user_id INTEGER,
                email TEXT,
                username TEXT,
                updated_at TEXT,
                updated_by TEXT
            )
            """
        )
        con.commit()
        return con

    def _limpiar_asignaciones(self) -> None:
        with self._con() as con:
            con.execute("DELETE FROM cartera_asignaciones")
            con.commit()

    def _guardar_asignacion(self, empresa: str, user_data: dict | None) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated_by = getattr(self._session, "username", "Sistema")

        with self._con() as con:
            if user_data is None:
                con.execute(
                    "DELETE FROM cartera_asignaciones WHERE empresa = ?",
                    (empresa,),
                )
            else:
                con.execute(
                    """
                    INSERT INTO cartera_asignaciones (
                        empresa, user_id, email, username, updated_at, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(empresa) DO UPDATE SET
                        user_id=excluded.user_id,
                        email=excluded.email,
                        username=excluded.username,
                        updated_at=excluded.updated_at,
                        updated_by=excluded.updated_by
                    """,
                    (
                        empresa,
                        int(user_data["id"]),
                        str(user_data["email"]),
                        str(user_data["username"]),
                        now,
                        updated_by,
                    ),
                )
            con.commit()

    def _obtener_asignaciones(self) -> dict[str, dict]:
        with self._con() as con:
            rows = con.execute(
                """
                SELECT empresa, user_id, email, username, updated_at, updated_by
                FROM cartera_asignaciones
                """
            ).fetchall()

        salida: dict[str, dict] = {}
        for empresa, user_id, email, username, updated_at, updated_by in rows:
            salida[str(empresa)] = {
                "user_id": user_id,
                "email": email,
                "username": username,
                "updated_at": updated_at,
                "updated_by": updated_by,
            }
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

        lbl_sub = QLabel(subtitle)
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("color:#64748b; font-size:9pt;")

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#eef2f7; max-height:1px; border:none;")

        lay.addWidget(lbl_title)
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

        self.btn_eliminar_deudor.clicked.connect(self._accion_eliminar_deudor_individual)
        self.btn_limpiar_empresa.clicked.connect(self._accion_limpiar_empresa)
        self.btn_limpiar_todas.clicked.connect(self._accion_limpiar_todas)
        self.btn_limpiar_gestiones.clicked.connect(self._accion_limpiar_gestiones)
        self.btn_reiniciar.clicked.connect(self._accion_reiniciar_datos_prueba)

        lay.addWidget(self.btn_eliminar_deudor)
        lay.addWidget(self.btn_limpiar_empresa)
        lay.addWidget(self.btn_limpiar_todas)
        lay.addWidget(self.btn_limpiar_gestiones)
        lay.addWidget(self.btn_reiniciar)

    def _build_asignacion_ui(self):
        lay = self.card_asignacion.layout()

        info = QLabel(
            "Selecciona el ejecutivo responsable por compañía. "
            "Las asignaciones se guardan en una base administrativa propia."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#475569; font-size:9pt;")
        lay.addWidget(info)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        ejecutivos = self._obtener_ejecutivos_activos()

        for row, empresa in enumerate(EMPRESAS):
            lbl = QLabel(empresa)
            lbl.setStyleSheet("color:#0f172a; font-weight:700;")

            combo = QComboBox()
            combo.setMinimumHeight(36)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.addItem("— Sin asignación —", None)
            for user in ejecutivos:
                display = f"{user['username']} · {user['email']}"
                combo.addItem(display, user)

            self._combos_asignacion[empresa] = combo

            grid.addWidget(lbl, row, 0)
            grid.addWidget(combo, row, 1)

        lay.addLayout(grid)

        row_btn = QHBoxLayout()
        row_btn.addStretch(1)

        self.btn_guardar_asignaciones = self._build_action_button("Guardar asignaciones", "#059669")
        self.btn_guardar_asignaciones.clicked.connect(self._accion_guardar_asignaciones)

        row_btn.addWidget(self.btn_guardar_asignaciones)
        lay.addLayout(row_btn)

    def _obtener_ejecutivos_activos(self) -> list[dict]:
        if self._session and getattr(self._session, "auth_source", "") == "backend":
            users = list_users(self._session)
        else:
            users = get_all_users()

        salida = []
        for u in users:
            if str(u.get("role", "")).strip() == "ejecutivo" and bool(u.get("is_active", 0)):
                salida.append(u)
        salida.sort(key=lambda x: str(x.get("username", "")).lower())
        return salida

    def _cargar_asignaciones(self):
        if self._session and getattr(self._session, "auth_source", "") == "backend":
            asignaciones_rows, err = backend_list_cartera_asignaciones(self._session)
            if err:
                self._append_log(f"Error al cargar asignaciones desde backend: {err}")
                asignaciones = {}
            else:
                asignaciones = {}
                for row in asignaciones_rows:
                    empresa = str(row.get("empresa", "")).strip()
                    if empresa:
                        asignaciones[empresa] = {
                            "user_id": row.get("user_id"),
                            "email": row.get("email", ""),
                            "username": row.get("username", ""),
                            "updated_at": row.get("updated_at", ""),
                            "updated_by": row.get("updated_by", ""),
                        }
        else:
            asignaciones = self._obtener_asignaciones()

        for empresa, combo in self._combos_asignacion.items():
            data = asignaciones.get(empresa)
            if not data:
                combo.setCurrentIndex(0)
                continue

            user_id = data.get("user_id")
            found = False
            for i in range(combo.count()):
                item_data = combo.itemData(i)
                if isinstance(item_data, dict) and int(item_data.get("id", 0)) == int(user_id):
                    combo.setCurrentIndex(i)
                    found = True
                    break
            if not found:
                combo.setCurrentIndex(0)

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
        empresa = self.cmb_empresa.currentText().strip()
        if not empresa:
            return

        if not self._confirmar(
            "Confirmar limpieza",
            f"Se eliminarán todos los registros cargados de la empresa '{empresa}'.\n\n¿Deseas continuar?",
        ):
            return

        if self._session and getattr(self._session, "auth_source", "") == "backend":
            err = backend_clear_empresa_deudores(self._session, empresa=empresa)
            ok = not err or "Se eliminaron" in err or "No existían" in err
            if not ok:
                QMessageBox.warning(self, "Sin cambios", err)
                return
            self._limpiar_base_local_empresa(empresa)
        else:
            ok = self._limpiar_base_local_empresa(empresa)
        if ok:
            self._append_log(f"Base de deudores limpiada para la empresa: {empresa}")
            self.bd_limpiada.emit([empresa])
            self.datos_actualizados.emit()
            QMessageBox.information(self, "Proceso completado", f"✅ Base limpiada para {empresa}.")
        else:
            QMessageBox.warning(self, "Sin cambios", f"No se pudo limpiar la base de {empresa} o no existían datos.")

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
        if not self._confirmar(
            "Confirmar limpieza de gestiones",
            "Se eliminarán todas las gestiones registradas en el sistema.\n\n¿Deseas continuar?",
        ):
            return

        if self._session and getattr(self._session, "auth_source", "") == "backend":
            msg = backend_clear_all_gestiones(self._session)
            ok = bool(msg)
            if not ok:
                QMessageBox.warning(self, "Sin cambios", "No se pudieron eliminar las gestiones en el backend.")
                return
            self._limpiar_gestiones_locales()
        else:
            ok = self._limpiar_gestiones_locales()
        if ok:
            self._append_log("Gestiones eliminadas correctamente.")
            self.datos_actualizados.emit()
            QMessageBox.information(self, "Proceso completado", "✅ Gestiones eliminadas correctamente.")
        else:
            QMessageBox.warning(self, "Sin cambios", "No se pudieron eliminar las gestiones.")

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

        if self._session and getattr(self._session, "auth_source", "") == "backend":
            assignments: list[dict] = []
            for empresa, combo in self._combos_asignacion.items():
                user_data = combo.currentData()
                assignments.append(
                    {
                        "empresa": empresa,
                        "user_id": int(user_data["id"]) if isinstance(user_data, dict) and user_data.get("id") else None,
                    }
                )
                cambios += 1

            _, err = backend_save_cartera_asignaciones(self._session, assignments=assignments)
            if err:
                self._append_log(f"Error al guardar asignaciones backend: {err}")
                QMessageBox.warning(self, "Error al guardar", err)
                return

            # Mantiene espejo local para consultas de UI en modo escritorio.
            self._limpiar_asignaciones()
            for empresa, combo in self._combos_asignacion.items():
                self._guardar_asignacion(empresa, combo.currentData())
        else:
            for empresa, combo in self._combos_asignacion.items():
                user_data = combo.currentData()
                self._guardar_asignacion(empresa, user_data)
                cambios += 1

        self._append_log(f"Asignaciones de cartera guardadas ({cambios} compañías procesadas).")
        self.datos_actualizados.emit()
        QMessageBox.information(self, "Asignaciones guardadas", "✅ Asignaciones de cartera guardadas correctamente.")
