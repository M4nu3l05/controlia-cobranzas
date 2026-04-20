from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from auth.auth_service import (
    backend_create_email_template,
    backend_delete_email_template,
    backend_update_email_template,
)
from .plantillas import VARIABLES_DISPONIBLES, cargar_plantillas, guardar_plantillas
from .ui_components import Card


class TabPlantillas(QWidget):
    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        self._session = session
        self._plantillas: list[dict] = []
        self._idx_actual = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        left = QWidget()
        left.setMinimumWidth(110)
        left.setMaximumWidth(320)
        left.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        card_list = Card("Plantillas guardadas", "")
        self.lst = QTableWidget(0, 1)
        self.lst.horizontalHeader().setVisible(False)
        self.lst.verticalHeader().setVisible(False)
        self.lst.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lst.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lst.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lst.itemSelectionChanged.connect(self._on_select)
        card_list.body.addWidget(self.lst)

        self.btn_add = QPushButton("➕  Nueva plantilla")
        self.btn_add.clicked.connect(self._nueva)
        self.btn_del = QPushButton("🗑  Eliminar")
        self.btn_del.clicked.connect(self._eliminar)
        card_list.body.addWidget(self.btn_add)
        card_list.body.addWidget(self.btn_del)
        ll.addWidget(card_list)
        layout.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        card_edit = Card("Editor de plantilla", "Usa variables como {nombre}, {saldo}, {empresa}.")
        form = QFormLayout()
        self.txt_nombre_p = QLineEdit()
        self.txt_asunto = QLineEdit()
        form.addRow("Nombre plantilla:", self.txt_nombre_p)
        form.addRow("Asunto:", self.txt_asunto)
        card_edit.body.addLayout(form)

        self.txt_cuerpo = QTextEdit()
        self.txt_cuerpo.setMinimumHeight(180)
        card_edit.body.addWidget(self.txt_cuerpo, 1)

        lbl_vars = QLabel("Variables disponibles: " + "  ".join(list(VARIABLES_DISPONIBLES.keys())))
        lbl_vars.setObjectName("MutedLabel")
        lbl_vars.setWordWrap(True)
        card_edit.body.addWidget(lbl_vars)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_save = QPushButton("💾  Guardar plantilla")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._guardar_plantilla)
        btn_row.addWidget(self.btn_save)
        card_edit.body.addLayout(btn_row)
        rl.addWidget(card_edit, 1)
        layout.addWidget(right, 1)

        self._recargar_desde_fuente()
        self._aplicar_permisos()

    def _es_backend(self) -> bool:
        return bool(self._session and getattr(self._session, "auth_source", "") == "backend")

    def _puede_editar(self) -> bool:
        role = str(getattr(self._session, "role", "")).strip().lower()
        if not self._es_backend():
            return True
        return role in {"admin", "supervisor"}

    def _aplicar_permisos(self) -> None:
        can_edit = self._puede_editar()
        self.btn_add.setEnabled(can_edit)
        self.btn_del.setEnabled(can_edit)
        self.btn_save.setEnabled(can_edit)
        self.txt_nombre_p.setReadOnly(not can_edit)
        self.txt_asunto.setReadOnly(not can_edit)
        self.txt_cuerpo.setReadOnly(not can_edit)
        if not can_edit:
            tip = "Solo supervisor/admin puede modificar plantillas."
            self.btn_add.setToolTip(tip)
            self.btn_del.setToolTip(tip)
            self.btn_save.setToolTip(tip)

    def _recargar_desde_fuente(self, keep_template_id: int | None = None) -> None:
        self._plantillas = cargar_plantillas(self._session)
        if not self._plantillas:
            self._plantillas = [{"nombre": "Plantilla", "asunto": "", "cuerpo": ""}]

        if keep_template_id is not None:
            idx = next(
                (
                    i
                    for i, p in enumerate(self._plantillas)
                    if int(p.get("_id", 0) or 0) == int(keep_template_id)
                ),
                0,
            )
            self._idx_actual = idx
        else:
            self._idx_actual = min(self._idx_actual, len(self._plantillas) - 1)
            self._idx_actual = max(self._idx_actual, 0)

        self._refrescar_lista()

    def _refrescar_lista(self) -> None:
        self.lst.setRowCount(0)
        for p in self._plantillas:
            r = self.lst.rowCount()
            self.lst.insertRow(r)
            self.lst.setItem(r, 0, QTableWidgetItem(p.get("nombre", f"Plantilla {r+1}")))
        if self._plantillas:
            self.lst.selectRow(self._idx_actual)
            self._cargar_en_editor(self._idx_actual)

    def _on_select(self) -> None:
        rows = self.lst.selectedItems()
        if rows:
            self._idx_actual = self.lst.row(rows[0])
            self._cargar_en_editor(self._idx_actual)

    def _cargar_en_editor(self, idx: int) -> None:
        if 0 <= idx < len(self._plantillas):
            p = self._plantillas[idx]
            self.txt_nombre_p.setText(p.get("nombre", ""))
            self.txt_asunto.setText(p.get("asunto", ""))
            self.txt_cuerpo.setPlainText(p.get("cuerpo", ""))

    def _guardar_plantilla(self) -> None:
        if not (0 <= self._idx_actual < len(self._plantillas)):
            return

        nombre = self.txt_nombre_p.text().strip() or f"Plantilla {self._idx_actual + 1}"
        asunto = self.txt_asunto.text().strip()
        cuerpo = self.txt_cuerpo.toPlainText()
        current = dict(self._plantillas[self._idx_actual])
        template_id = int(current.get("_id", 0) or 0)

        if self._es_backend():
            if not self._puede_editar():
                QMessageBox.warning(self, "Sin permisos", "Solo supervisor/admin puede modificar plantillas.")
                return

            if template_id > 0:
                _, err = backend_update_email_template(
                    self._session,
                    template_id=template_id,
                    nombre=nombre,
                    asunto=asunto,
                    cuerpo=cuerpo,
                    is_active=True,
                )
            else:
                created, err = backend_create_email_template(
                    self._session,
                    nombre=nombre,
                    asunto=asunto,
                    cuerpo=cuerpo,
                    is_active=True,
                )
                if not err and isinstance(created, dict):
                    template_id = int(created.get("id", 0) or 0)

            if err:
                QMessageBox.warning(self, "No se pudo guardar", err)
                return

            self._recargar_desde_fuente(keep_template_id=template_id if template_id > 0 else None)
            return

        self._plantillas[self._idx_actual] = {
            "nombre": nombre,
            "asunto": asunto,
            "cuerpo": cuerpo,
        }
        guardar_plantillas(self._plantillas)
        self._refrescar_lista()
        self.lst.selectRow(self._idx_actual)

    def _nueva(self) -> None:
        self._plantillas.append({"nombre": "Nueva plantilla", "asunto": "", "cuerpo": "", "_id": 0})
        self._idx_actual = len(self._plantillas) - 1
        if not self._es_backend():
            guardar_plantillas(self._plantillas)
        self._refrescar_lista()

    def _eliminar(self) -> None:
        if not (0 <= self._idx_actual < len(self._plantillas)):
            return

        if len(self._plantillas) <= 1:
            QMessageBox.warning(self, "Minimo", "Debe haber al menos una plantilla.")
            return

        row = dict(self._plantillas[self._idx_actual])
        template_id = int(row.get("_id", 0) or 0)

        if self._es_backend():
            if not self._puede_editar():
                QMessageBox.warning(self, "Sin permisos", "Solo supervisor/admin puede eliminar plantillas.")
                return
            if template_id > 0:
                err = backend_delete_email_template(self._session, template_id=template_id)
                if err:
                    QMessageBox.warning(self, "No se pudo eliminar", err)
                    return
            self._plantillas.pop(self._idx_actual)
            self._idx_actual = max(0, self._idx_actual - 1)
            self._recargar_desde_fuente()
            return

        self._plantillas.pop(self._idx_actual)
        self._idx_actual = max(0, self._idx_actual - 1)
        guardar_plantillas(self._plantillas)
        self._refrescar_lista()

    def get_plantilla_actual(self) -> dict:
        if 0 <= self._idx_actual < len(self._plantillas):
            p = self._plantillas[self._idx_actual]
            return {
                "nombre": p.get("nombre", ""),
                "asunto": p.get("asunto", ""),
                "cuerpo": p.get("cuerpo", ""),
            }
        return {}
