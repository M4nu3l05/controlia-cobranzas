# ================================================================
#  auth/views/users_panel.py
#
#  Panel de gestión de usuarios conectado a CRM_Backend.
# ================================================================

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
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


class _TempPasswordDialog(QDialog):
    def __init__(self, *, username: str, temp_password: str, parent=None):
        super().__init__(parent)
        self._temp_password = str(temp_password or "")
        self.setWindowTitle("Contrasena temporal generada")
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel(
            "Comparte esta contrasena por canal seguro. "
            "El usuario debera cambiarla al iniciar sesion."
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

        btn_copy = QPushButton("Copiar contrasena")
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
        self.lbl_ok.setText("Contrasena copiada al portapapeles.")


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
        self.cmb_role.setCurrentIndex(2)
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
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            [
                "Nombre",
                "Correo",
                "Rol",
                "Estado",
                "Editar rol",
                "Activar / Desactivar",
                "Eliminar",
                "Recuperación asistida",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
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
        users = list_users(self._session)
        self.table.setRowCount(len(users))

        for row, u in enumerate(users):
            self.table.setRowHeight(row, 48)
            is_self = u["id"] == self._session.user_id
            uid = u["id"]

            n = QTableWidgetItem(u["username"])
            if is_self:
                n.setForeground(QColor("#2563eb"))
                n.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            self.table.setItem(row, 0, n)
            self.table.setItem(row, 1, QTableWidgetItem(u["email"]))

            badge_w = QWidget()
            bl = QHBoxLayout(badge_w)
            bl.setContentsMargins(4, 4, 4, 4)
            bl.addWidget(_badge(u["role"]))
            bl.addStretch(1)
            self.table.setCellWidget(row, 2, badge_w)

            status = "✅ Activo" if u["is_active"] else "⛔ Inactivo"
            s_item = QTableWidgetItem(status)
            s_item.setForeground(QColor("#16a34a") if u["is_active"] else QColor("#dc2626"))
            self.table.setItem(row, 3, s_item)

            cmb = QComboBox()
            cmb.setFixedHeight(30)
            cmb.setStyleSheet("""
                QComboBox { background:#f8fafc; border:1px solid #e2e8f0;
                    border-radius:6px; padding:0 8px; font-size:8.5pt; }
                QComboBox::drop-down { border:none; }
            """)
            for key, label in ROLES.items():
                cmb.addItem(label, key)
            cmb.setCurrentIndex(list(ROLES.keys()).index(u["role"]))
            if is_self:
                cmb.setEnabled(False)
            cmb.currentIndexChanged.connect(
                lambda _, c=cmb, i=uid: self._change_role(i, c.currentData())
            )
            self.table.setCellWidget(row, 4, cmb)

            if is_self:
                self.table.setItem(row, 5, QTableWidgetItem("(tu cuenta)"))
            else:
                lbl_btn = "Desactivar" if u["is_active"] else "Activar"
                btn = QPushButton(lbl_btn)
                btn.setFixedHeight(30)
                btn.setStyleSheet(_BTN_DANGER if u["is_active"] else _BTN_PRIMARY)
                btn.clicked.connect(lambda _, i=uid, active=bool(u["is_active"]): self._toggle(i, active))
                w = QWidget()
                bl2 = QHBoxLayout(w)
                bl2.setContentsMargins(4, 4, 4, 4)
                bl2.addWidget(btn)
                self.table.setCellWidget(row, 5, w)

            if is_self:
                self.table.setItem(row, 6, QTableWidgetItem("(protegido)"))
            else:
                btn_del = QPushButton("Eliminar")
                btn_del.setFixedHeight(30)
                btn_del.setStyleSheet(_BTN_DANGER)
                btn_del.clicked.connect(
                    lambda _, user_id=uid, name=u["username"], email=u["email"]: self._delete_user(user_id, name, email)
                )
                w_del = QWidget()
                bl3 = QHBoxLayout(w_del)
                bl3.setContentsMargins(4, 4, 4, 4)
                bl3.addWidget(btn_del)
                self.table.setCellWidget(row, 6, w_del)

            if self._puede_recuperar_asistido(u):
                btn_rec = QPushButton("Restablecer")
                btn_rec.setFixedHeight(30)
                btn_rec.setStyleSheet(_BTN_PRIMARY)
                btn_rec.clicked.connect(
                    lambda _, user_id=uid, name=u["username"], role=u["role"]: self._reset_asistido(user_id, name, role)
                )
                w_rec = QWidget()
                bl4 = QHBoxLayout(w_rec)
                bl4.setContentsMargins(4, 4, 4, 4)
                bl4.addWidget(btn_rec)
                self.table.setCellWidget(row, 7, w_rec)
            else:
                self.table.setItem(row, 7, QTableWidgetItem("No autorizado"))

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
            f"¿Deseas eliminar permanentemente este usuario?\n\n"
            f"Nombre: {username}\n"
            f"Correo: {email}\n\n"
            f"Esta acción no se puede deshacer.",
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
                f"✅  El usuario '{username}' fue eliminado correctamente."
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
