# ================================================================
#  auth/views/users_panel.py
#
#  Panel de gestión de usuarios conectado a CRM_Backend.
# ================================================================

from __future__ import annotations

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QInputDialog, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from auth.auth_service import (
    UserSession, ROLES, ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_EJECUTIVO,
    admin_create_user, admin_delete_user, admin_update_user, list_users,
    toggle_user_active, backend_assisted_reset_password,
)

ROLE_COLORS = {
    ROLE_ADMIN: ("#dbeafe", "#1d4ed8"),
    ROLE_SUPERVISOR: ("#dcfce7", "#15803d"),
    ROLE_EJECUTIVO: ("#f1f5f9", "#475569"),
}

_BTN_PRIMARY = """
    QPushButton { background:#2563eb; color:#fff; border:none;
        border-radius:8px; font-size:9pt; font-weight:600; }
    QPushButton:hover { background:#1d4ed8; }
    QPushButton:pressed { background:#1e40af; }
    QPushButton:disabled { background:#93c5fd; }
"""
_BTN_DANGER = """
    QPushButton { background:#fee2e2; color:#dc2626; border:none;
        border-radius:8px; font-size:9pt; font-weight:600; }
    QPushButton:hover { background:#fecaca; }
"""
_BTN_SEC = """
    QPushButton { background:#f1f5f9; color:#374151;
        border:1.5px solid #e2e8f0; border-radius:8px;
        font-size:9pt; font-weight:600; }
    QPushButton:hover { background:#e2e8f0; }
"""


class _UsersLoadWorker(QThread):
    completed = pyqtSignal(object)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session

    def run(self) -> None:
        self.completed.emit(list_users(self._session))


class _TempPasswordDialog(QDialog):
    def __init__(self, *, username: str, temp_password: str, parent=None):
        super().__init__(parent)
        self._temp_password = str(temp_password or "")
        self.setWindowTitle("Contraseña temporal generada")
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel(
            "Comparte esta contraseña por canal seguro. "
            "El usuario deberá cambiarla al iniciar sesión."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#334155; font-size:9pt;")
        lay.addWidget(info)

        user_lbl = QLabel(f"Usuario: {username}")
        user_lbl.setStyleSheet("font-weight:700; color:#0f172a;")
        lay.addWidget(user_lbl)

        row = QHBoxLayout()
        self.edit = QLineEdit(self._temp_password)
        self.edit.setReadOnly(True)
        self.edit.setMinimumHeight(38)
        self.edit.setStyleSheet(
            """
            QLineEdit {
                background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px;
                padding:0 10px; font-family:Consolas; font-size:10pt; color:#0f172a;
            }
            """
        )
        row.addWidget(self.edit, 1)

        btn_copy = QPushButton("Copiar contraseña")
        btn_copy.setMinimumHeight(38)
        btn_copy.setStyleSheet(_BTN_PRIMARY)
        btn_copy.clicked.connect(self._copy)
        row.addWidget(btn_copy)
        lay.addLayout(row)

        self.lbl_ok = QLabel("")
        self.lbl_ok.setStyleSheet("color:#16a34a; font-size:8.5pt;")
        lay.addWidget(self.lbl_ok)

        btn_close = QPushButton("Cerrar")
        btn_close.setMinimumHeight(34)
        btn_close.setStyleSheet(_BTN_SEC)
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignRight)

        self.edit.selectAll()
        self.edit.setFocus()

    def _copy(self):
        QApplication.clipboard().setText(self._temp_password)
        self.lbl_ok.setText("Contraseña copiada al portapapeles.")


def _badge(role: str) -> QLabel:
    bg, fg = ROLE_COLORS.get(role, ("#f1f5f9", "#475569"))
    lbl = QLabel(ROLES.get(role, role))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setMinimumHeight(22)
    lbl.setStyleSheet(
        f"background:{bg}; color:{fg}; border-radius:6px;"
        f" padding:0 10px; font-size:8pt; font-weight:700;"
    )
    return lbl


class _CreateUserDialog(QDialog):
    def __init__(self, executor: UserSession, parent=None):
        super().__init__(parent)
        self._executor = executor
        self.created_user = None
        self.setWindowTitle("Crear nuevo usuario")
        self.setMinimumWidth(420)
        self.setStyleSheet("QDialog { background:#ffffff; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)

        t = QLabel("Nuevo usuario")
        t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        t.setStyleSheet("color:#0f172a;")
        lay.addWidget(t)

        sub = QLabel("El usuario deberá cambiar su contraseña al primer inicio de sesión.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#64748b; font-size:8.5pt;")
        lay.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#e2e8f0;")
        lay.addWidget(sep)

        lay.addWidget(self._lbl("Nombre completo"))
        self.f_name = QLineEdit()
        self._style_field(self.f_name, "Nombre del usuario")
        lay.addWidget(self.f_name)

        lay.addWidget(self._lbl("Correo electrónico"))
        self.f_email = QLineEdit()
        self._style_field(self.f_email, "correo@empresa.cl")
        lay.addWidget(self.f_email)

        lay.addWidget(self._lbl("Rol"))
        self.cmb_role = QComboBox()
        self.cmb_role.setMinimumHeight(40)
        self.cmb_role.setStyleSheet("""
            QComboBox { background:#f8fafc; border:1.5px solid #e2e8f0;
                border-radius:8px; padding:0 12px; font-size:9pt; color:#0f172a; }
            QComboBox::drop-down { border:none; }
            QComboBox:focus { border:1.5px solid #2563eb; }
        """)
        for key, label in ROLES.items():
            self.cmb_role.addItem(label, key)
        self.cmb_role.setCurrentIndex(self.cmb_role.findData("supervisor"))
        lay.addWidget(self.cmb_role)

        lay.addWidget(self._lbl("Contraseña temporal"))
        self.f_pass = QLineEdit()
        self.f_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._style_field(self.f_pass, "Mínimo 8 caracteres")
        self.f_pass.textChanged.connect(self._upd_bar)
        lay.addWidget(self.f_pass)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setStyleSheet("""
            QProgressBar { background:#e2e8f0; border:none; border-radius:2px; }
            QProgressBar::chunk { background:#2563eb; border-radius:2px; }
        """)
        lay.addWidget(self.bar)

        lay.addWidget(self._lbl("Confirmar contraseña"))
        self.f_conf = QLineEdit()
        self.f_conf.setEchoMode(QLineEdit.EchoMode.Password)
        self._style_field(self.f_conf, "Repite la contraseña")
        lay.addWidget(self.f_conf)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#dc2626; font-size:8.5pt;")
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setVisible(False)
        lay.addWidget(self.lbl_err)

        btns = QHBoxLayout()
        cancel = QPushButton("Cancelar")
        cancel.setMinimumHeight(38)
        cancel.setStyleSheet(_BTN_SEC)
        cancel.clicked.connect(self.reject)

        self.btn_ok = QPushButton("Crear usuario")
        self.btn_ok.setMinimumHeight(38)
        self.btn_ok.setStyleSheet(_BTN_PRIMARY)
        self.btn_ok.clicked.connect(self._do)

        btns.addWidget(cancel)
        btns.addWidget(self.btn_ok)
        lay.addLayout(btns)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        l.setStyleSheet("color:#374151;")
        return l

    @staticmethod
    def _style_field(edit: QLineEdit, ph: str):
        edit.setPlaceholderText(ph)
        edit.setMinimumHeight(40)
        edit.setStyleSheet("""
            QLineEdit { background:#f8fafc; border:1.5px solid #e2e8f0;
                border-radius:8px; padding:0 12px; font-size:9pt; color:#0f172a; }
            QLineEdit:focus { border:1.5px solid #2563eb; background:#fff; }
        """)

    def _upd_bar(self, text):
        if not text:
            self.bar.setValue(0)
            return
        score = 100 if len(text) >= 12 else 70 if len(text) >= 10 else 45 if len(text) >= 8 else 20
        self.bar.setValue(score)

    def _do(self):
        self.lbl_err.setVisible(False)
        role = self.cmb_role.currentData()
        user_row, errors = admin_create_user(
            self._executor,
            self.f_email.text().strip(),
            self.f_name.text().strip(),
            role,
            self.f_pass.text(),
            self.f_conf.text(),
        )
        if errors:
            self.lbl_err.setText("\n".join(f"• {e}" for e in errors))
            self.lbl_err.setVisible(True)
            return
        self.created_user = user_row
        self.accept()


class UsersPanel(QWidget):
    def __init__(self, session: UserSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._load_worker: _UsersLoadWorker | None = None
        self._reload_pending = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        hdr = QHBoxLayout()
        t = QLabel("Gestión de usuarios")
        t.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        t.setStyleSheet("color:#0f172a;")
        hdr.addWidget(t)
        hdr.addStretch(1)

        self.btn_new = QPushButton("＋  Nuevo usuario")
        self.btn_new.setMinimumHeight(38)
        self.btn_new.setStyleSheet(_BTN_PRIMARY)
        self.btn_new.clicked.connect(self._open_create)
        hdr.addWidget(self.btn_new)

        lay.addLayout(hdr)

        legend = QHBoxLayout()
        legend.setSpacing(8)
        legend.addWidget(QLabel("Roles:"))
        for role in ROLES:
            legend.addWidget(_badge(role))
        legend.addStretch(1)
        lay.addLayout(legend)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Nombre", "Correo", "Rol", "Estado", "Acciones"]
        )
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(90)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 185)
        self.table.setColumnWidth(4, 260)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget { border:1px solid #e2e8f0; border-radius:8px;
                gridline-color:#f1f5f9; font-size:9pt; }
            QTableWidget::item { padding:6px; }
            QHeaderView::section { background:#f8fafc; font-weight:600;
                color:#374151; border:none; border-bottom:1px solid #e2e8f0;
                padding:8px; }
            QTableWidget::item:alternate { background:#f8fafc; }
        """)
        lay.addWidget(self.table)

        self.reload()

    def reload(self):
        if self._load_worker is not None and self._load_worker.isRunning():
            self._reload_pending = True
            return
        self.table.setRowCount(1)
        self.table.setSpan(0, 0, 1, self.table.columnCount())
        self.table.setItem(0, 0, QTableWidgetItem("Cargando usuarios…"))
        self._load_worker = _UsersLoadWorker(self._session, parent=self)
        self._load_worker.completed.connect(self._render_users)
        self._load_worker.finished.connect(self._users_load_finished)
        self._load_worker.start()

    def _users_load_finished(self) -> None:
        worker = self._load_worker
        self._load_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._reload_pending:
            self._reload_pending = False
            self.reload()

    def _render_users(self, users: list[dict]):
        self.table.clearSpans()
        self.table.setRowCount(len(users))

        for row, u in enumerate(users):
            self.table.setRowHeight(row, 78)
            is_self = u["id"] == self._session.user_id
            uid = u["id"]

            n = QTableWidgetItem(u["username"])
            if is_self:
                n.setForeground(QColor("#2563eb"))
                n.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            self.table.setItem(row, 0, n)
            self.table.setItem(row, 1, QTableWidgetItem(u["email"]))

            cmb = QComboBox()
            cmb.setMinimumSize(132, 30)
            cmb.setStyleSheet("""
                QComboBox { background:#f8fafc; border:1px solid #e2e8f0;
                    border-radius:6px; padding:0 8px; font-size:8.5pt; }
                QComboBox::drop-down { border:none; }
            """)
            for key, label in ROLES.items():
                cmb.addItem(label, key)
            role = "supervisor" if str(u.get("role", "")).strip() == "ejecutivo" else u.get("role")
            index = cmb.findData(role)
            cmb.setCurrentIndex(index if index >= 0 else 0)
            if is_self:
                cmb.setEnabled(False)
            cmb.currentIndexChanged.connect(
                lambda _, c=cmb, i=uid: self._change_role(i, c.currentData())
            )
            role_widget = QWidget()
            role_layout = QVBoxLayout(role_widget)
            role_layout.setContentsMargins(4, 4, 4, 4)
            role_layout.addWidget(cmb)
            self.table.setCellWidget(row, 2, role_widget)

            state_widget = QWidget()
            state_layout = QVBoxLayout(state_widget)
            state_layout.setContentsMargins(4, 4, 4, 4)
            state_layout.setSpacing(4)
            state_label = QLabel("Activo" if u["is_active"] else "Inactivo")
            state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            state_label.setStyleSheet(
                "color:#16a34a; font-weight:700;" if u["is_active"]
                else "color:#dc2626; font-weight:700;"
            )
            state_layout.addWidget(state_label)
            if is_self:
                own_label = QLabel("Tu cuenta")
                own_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                own_label.setStyleSheet("color:#64748b; font-size:8pt;")
                state_layout.addWidget(own_label)
            else:
                lbl_btn = "Desactivar" if u["is_active"] else "Activar"
                btn = QPushButton(lbl_btn)
                btn.setMinimumSize(104, 26)
                btn.setStyleSheet(_BTN_DANGER if u["is_active"] else _BTN_PRIMARY)
                btn.clicked.connect(lambda _, i=uid, active=bool(u["is_active"]): self._toggle(i, active))
                state_layout.addWidget(btn)
            self.table.setCellWidget(row, 3, state_widget)

            actions_widget = QWidget()
            actions = QGridLayout(actions_widget)
            actions.setContentsMargins(4, 4, 4, 4)
            actions.setHorizontalSpacing(5)
            actions.setVerticalSpacing(5)

            btn_name = QPushButton("Renombrar")
            btn_name.setMinimumSize(104, 28)
            btn_name.setStyleSheet(_BTN_SEC)
            btn_name.clicked.connect(
                lambda _, user_id=uid, name=u["username"]: self._edit_name(user_id, name)
            )
            actions.addWidget(btn_name, 0, 0)

            if not is_self:
                btn_del = QPushButton("Eliminar")
                btn_del.setMinimumSize(104, 28)
                btn_del.setStyleSheet(_BTN_DANGER)
                btn_del.clicked.connect(
                    lambda _, user_id=uid, name=u["username"], email=u["email"]: self._delete_user(user_id, name, email)
                )
                actions.addWidget(btn_del, 0, 1)

            if self._puede_recuperar_asistido(u):
                btn_rec = QPushButton("Restablecer")
                btn_rec.setMinimumSize(104, 28)
                btn_rec.setStyleSheet(_BTN_PRIMARY)
                btn_rec.clicked.connect(
                    lambda _, user_id=uid, name=u["username"], role=u["role"]: self._reset_asistido(user_id, name, role)
                )
                actions.addWidget(btn_rec, 1, 0, 1, 2)
            self.table.setCellWidget(row, 4, actions_widget)

    def _open_create(self):
        dlg = _CreateUserDialog(self._session, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self,
                "Usuario creado",
                f"✅  Usuario '{dlg.created_user['username']}' creado correctamente.\n"
                f"Deberá cambiar su contraseña en el primer inicio de sesión."
            )
            self.reload()

    def _change_role(self, user_id: int, new_role: str):
        errors = admin_update_user(self._session, user_id, role=new_role)
        if errors:
            QMessageBox.warning(self, "Error", "\n".join(errors))
            self.reload()
            return
        message = f"El rol fue actualizado a {ROLES.get(new_role, new_role)}."
        if new_role == ROLE_SUPERVISOR:
            message += (
                "\n\nEl usuario deberá cerrar sesión y volver a ingresar para que "
                "toda la interfaz habilite las funciones de supervisión."
            )
        QMessageBox.information(self, "Rol actualizado", message)
        self.reload()

    def _edit_name(self, user_id: int, current_name: str) -> None:
        new_name, accepted = QInputDialog.getText(
            self,
            "Editar nombre del usuario",
            (
                "Ingresa el nombre que se utilizará para relacionar la columna Ejecutiva.\n"
                "El correo, la contraseña y las asignaciones no cambiarán."
            ),
            QLineEdit.EchoMode.Normal,
            current_name,
        )
        if not accepted:
            return
        new_name = new_name.strip()
        if new_name == str(current_name or "").strip():
            return

        errors = admin_update_user(self._session, user_id, username=new_name)
        if errors:
            QMessageBox.warning(self, "No se pudo cambiar el nombre", "\n".join(errors))
            return

        if user_id == self._session.user_id:
            self._session.username = new_name
        QMessageBox.information(
            self,
            "Nombre actualizado",
            f"El usuario ahora se identifica como '{new_name}'.",
        )
        self.reload()

    def _toggle(self, user_id: int, current_is_active: bool):
        errors = toggle_user_active(self._session, user_id, current_is_active)
        if errors:
            QMessageBox.warning(self, "Error", "\n".join(errors))
        self.reload()

    def _delete_user(self, user_id: int, username: str, email: str):
        if user_id == self._session.user_id:
            QMessageBox.warning(self, "Acción no permitida", "No puedes eliminar tu propia cuenta.")
            return

        resp = QMessageBox.question(
            self,
            "Eliminar usuario",
            f"¿Deseas eliminar el acceso de este usuario?\n\n"
            f"Nombre: {username}\n"
            f"Correo: {email}\n\n"
            "La cuenta no podrá volver a iniciar sesión y sus asignaciones operativas "
            "serán retiradas. La trazabilidad financiera y de auditoría se conservará.\n\n"
            "Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        errors = admin_delete_user(self._session, user_id)
        if errors:
            QMessageBox.warning(self, "No se pudo eliminar", "\n".join(errors))
        else:
            QMessageBox.information(
                self,
                "Usuario eliminado",
                f"✅  Se eliminó el acceso de '{username}' y se conservó su historial."
            )

        self.reload()

    def _puede_recuperar_asistido(self, user_row: dict) -> bool:
        if int(user_row.get("id", 0)) == int(self._session.user_id):
            return False
        if not bool(user_row.get("is_active", False)):
            return False

        target_role = str(user_row.get("role", "")).strip().lower()
        executor_role = str(self._session.role or "").strip().lower()

        if target_role == ROLE_EJECUTIVO:
            return executor_role == ROLE_SUPERVISOR
        if target_role == ROLE_SUPERVISOR:
            return executor_role == ROLE_ADMIN
        return False

    def _reset_asistido(self, user_id: int, username: str, role: str):
        resp = QMessageBox.question(
            self,
            "Recuperación asistida",
            f"¿Deseas generar una contraseña temporal para:\n\nUsuario: {username}\nRol: {ROLES.get(role, role)}?\n\n"
            "El usuario deberá cambiarla al iniciar sesión.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        data, err = backend_assisted_reset_password(self._session, user_id=user_id)
        if err:
            QMessageBox.warning(self, "No se pudo restablecer", err)
            return

        temp_password = str((data or {}).get("temporary_password", "")).strip()
        if not temp_password:
            QMessageBox.warning(self, "Sin contraseña temporal", "El backend no devolvió contraseña temporal.")
            return

        dlg = _TempPasswordDialog(username=username, temp_password=temp_password, parent=self)
        dlg.exec()
        self.reload()
