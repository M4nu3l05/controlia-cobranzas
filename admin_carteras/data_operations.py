from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass

import pandas as pd
from PyQt6.QtCore import QDate, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from auth.auth_service import (
    backend_apply_debtor_assignments,
    backend_import_deudores,
    backend_import_gestiones,
    backend_list_all_gestiones,
    backend_list_deudores,
    backend_preview_debtor_assignments,
    backend_preview_import_deudores,
    backend_preview_import_gestiones,
    list_users,
)
from core.excel_export import write_excel_report
from core.paths import get_data_dir
from deudores.database import EMPRESAS, base_deudores_ya_cargada
from deudores.gestiones_db import TABLA
from deudores.gestiones_import_dialog import GestionCompanyResolutionDialog
from deudores.gestiones_worker import CargaGestionesParams, CargaGestionesWorker
from deudores.import_mapping_dialog import ImportColumnMappingDialog
from deudores.worker import CargaDeudoresParams, CargaDeudoresWorker


logger = logging.getLogger(__name__)


class _OperationWorker(QThread):
    completed = pyqtSignal(object, str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            self.completed.emit(self._operation(), "")
        except Exception as exc:
            logger.exception("Falló una operación administrativa (%s)", type(exc).__name__)
            self.completed.emit(None, str(exc))


@dataclass(frozen=True)
class _DebtorImportContext:
    path: str
    empresa: str
    mapping: dict


class CarteraDataOperationsPanel(QWidget):
    """Importación y exportación de bases, desacoplada de la vista de deudores."""

    datos_actualizados = pyqtSignal()
    operation_state_changed = pyqtSignal(bool, str)

    def __init__(self, session=None, parent=None):
        super().__init__(parent)
        self._session = session
        self._workers: set[QThread] = set()
        self._deudor_context: _DebtorImportContext | None = None
        self._gestiones_path = ""
        self._busy = False

        role = str(getattr(session, "role", "") or "").strip().lower()
        self._authorized = session is None or role in {"admin", "supervisor"}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        title = QLabel("Bases y gestiones")
        title.setStyleSheet("font-size:14pt; font-weight:800; color:#0f172a;")
        subtitle = QLabel(
            "Carga de carteras, importación de gestiones y exportaciones operativas."
        )
        subtitle.setStyleSheet("color:#64748b;")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        root.addLayout(self.grid)

        self.card_deudores = self._card("Cargar base de deudores")
        self.card_gestiones = self._card("Base de gestiones")
        self.card_exportar = self._card("Descargar base de gestiones")
        self.grid.addWidget(self.card_deudores, 0, 0)
        self.grid.addWidget(self.card_gestiones, 0, 1)
        self.grid.addWidget(self.card_exportar, 0, 2)
        for column in range(3):
            self.grid.setColumnStretch(column, 1)

        self._build_deudores_card()
        self._build_gestiones_card()
        self._build_export_card()
        self.setVisible(self._authorized)

    def _card(self, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("DataOperationCard")
        card.setStyleSheet(
            "QFrame#DataOperationCard {background:#fff; border:1px solid #e2e8f0; "
            "border-radius:16px;} QLabel {border:none; background:transparent;}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:11pt; font-weight:800; color:#0f172a;")
        layout.addWidget(heading)
        return card

    @staticmethod
    def _button(text: str, *, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(38)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton {border-radius:10px; padding:8px 12px; font-weight:700; "
            + ("background:#2563eb; color:#fff; border:none;}" if primary else
               "background:#f8fafc; color:#0f172a; border:1px solid #cbd5e1;}")
        )
        return button

    def _build_deudores_card(self) -> None:
        layout = self.card_deudores.layout()
        self.cmb_empresa = QComboBox()
        self.cmb_empresa.addItems(EMPRESAS)
        self.cmb_empresa.setMinimumHeight(36)
        layout.addWidget(QLabel("Compañía"))
        layout.addWidget(self.cmb_empresa)

        self.txt_deudores = QLineEdit()
        self.txt_deudores.setReadOnly(True)
        self.txt_deudores.setPlaceholderText("Selecciona el archivo Excel…")
        layout.addWidget(self.txt_deudores)

        row = QHBoxLayout()
        self.btn_pick_deudores = self._button("Seleccionar…")
        self.btn_import_deudores = self._button("Cargar base", primary=True)
        row.addWidget(self.btn_pick_deudores)
        row.addWidget(self.btn_import_deudores, 1)
        layout.addLayout(row)

        self.btn_distribucion = self._button("Actualizar distribución")
        self.btn_distribucion.setEnabled(self._uses_backend())
        layout.addWidget(self.btn_distribucion)

        self.progress_deudores = QProgressBar()
        self.progress_deudores.setVisible(False)
        layout.addWidget(self.progress_deudores)

        self.btn_pick_deudores.clicked.connect(self._pick_deudores)
        self.btn_import_deudores.clicked.connect(self._start_deudor_import)
        self.btn_distribucion.clicked.connect(self._start_distribution_update)

    def _build_gestiones_card(self) -> None:
        layout = self.card_gestiones.layout()
        hint = QLabel("Importa hojas SMS, Email o Carta.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b;")
        layout.addWidget(hint)

        self.txt_gestiones = QLineEdit()
        self.txt_gestiones.setReadOnly(True)
        self.txt_gestiones.setPlaceholderText("Selecciona el archivo de gestiones…")
        layout.addWidget(self.txt_gestiones)

        self.btn_pick_gestiones = self._button("Seleccionar…")
        self.btn_template = self._button("Descargar plantilla")
        self.btn_import_gestiones = self._button("Cargar gestiones", primary=True)
        layout.addWidget(self.btn_pick_gestiones)
        layout.addWidget(self.btn_template)
        layout.addWidget(self.btn_import_gestiones)

        self.progress_gestiones = QProgressBar()
        self.progress_gestiones.setVisible(False)
        layout.addWidget(self.progress_gestiones)

        self.btn_pick_gestiones.clicked.connect(self._pick_gestiones)
        self.btn_template.clicked.connect(self._save_template)
        self.btn_import_gestiones.clicked.connect(self._start_gestiones_import)

    def _build_export_card(self) -> None:
        layout = self.card_exportar.layout()
        self.chk_full = QCheckBox("Descargar base completa")
        self.chk_full.setChecked(True)
        layout.addWidget(self.chk_full)

        row = QHBoxLayout()
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_to = QDateEdit(QDate.currentDate())
        for editor in (self.date_from, self.date_to):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd/MM/yyyy")
            editor.setEnabled(False)
        row.addWidget(QLabel("Desde"))
        row.addWidget(self.date_from)
        row.addWidget(QLabel("Hasta"))
        row.addWidget(self.date_to)
        layout.addLayout(row)

        self.btn_export = self._button("Descargar Excel", primary=True)
        layout.addWidget(self.btn_export)
        self.progress_export = QProgressBar()
        self.progress_export.setVisible(False)
        layout.addWidget(self.progress_export)

        self.chk_full.toggled.connect(lambda checked: self._toggle_dates(not checked))
        self.btn_export.clicked.connect(self._start_export)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        columns = 1 if self.width() < 940 else 3
        positions = [(0, 0), (0, 1), (0, 2)] if columns == 3 else [(0, 0), (1, 0), (2, 0)]
        for card, (row, column) in zip(
            (self.card_deudores, self.card_gestiones, self.card_exportar), positions
        ):
            self.grid.addWidget(card, row, column)

    def _uses_backend(self) -> bool:
        return bool(self._session and getattr(self._session, "auth_source", "") == "backend")

    def _toggle_dates(self, enabled: bool) -> None:
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        if not self._authorized:
            return
        self._busy = busy
        for widget in (
            self.cmb_empresa,
            self.btn_pick_deudores,
            self.btn_import_deudores,
            self.btn_pick_gestiones,
            self.btn_template,
            self.btn_import_gestiones,
            self.btn_export,
        ):
            widget.setEnabled(not busy)
        self.btn_distribucion.setEnabled(not busy and self._uses_backend())
        self.operation_state_changed.emit(busy, message)

    def _run(self, operation, callback) -> None:
        worker = _OperationWorker(operation, self)
        self._workers.add(worker)
        worker.completed.connect(callback)
        worker.finished.connect(lambda: self._release_worker(worker))
        worker.start()

    def _release_worker(self, worker: QThread) -> None:
        self._workers.discard(worker)
        worker.deleteLater()

    def _pick_deudores(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar base de deudores", "", "Excel (*.xlsx *.xls)"
        )
        if path:
            self.txt_deudores.setText(path)

    def _pick_gestiones(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar base de gestiones", "", "Excel (*.xlsx *.xls)"
        )
        if path:
            self.txt_gestiones.setText(path)

    def _selected_deudor_context(self) -> _DebtorImportContext | None:
        path = self.txt_deudores.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Archivo no válido", "Selecciona una base de deudores válida.")
            return None
        empresa = self.cmb_empresa.currentText().strip()
        try:
            dialog = ImportColumnMappingDialog(path, empresa, self)
        except ValueError as exc:
            QMessageBox.critical(self, "No se pudo leer el archivo", str(exc))
            return None
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return _DebtorImportContext(path, empresa, dialog.mapping_payload())

    def _start_deudor_import(self) -> None:
        context = self._selected_deudor_context()
        if context is None:
            return
        if not self._uses_backend():
            if base_deudores_ya_cargada(context.empresa, context.path):
                QMessageBox.warning(self, "Base duplicada", "Esta base ya fue cargada para la compañía.")
                return
            self._start_local_deudor_import(context)
            return

        self._deudor_context = context
        self._set_busy(True, "Analizando base de deudores…")
        self.progress_deudores.setVisible(True)
        self.progress_deudores.setRange(0, 0)

        def preview_operation():
            preview, error = backend_preview_import_deudores(
                self._session,
                empresa=context.empresa,
                excel_path=context.path,
                column_mapping=context.mapping,
            )
            if error:
                raise ValueError(error)
            assignments, error = backend_preview_debtor_assignments(
                self._session, empresa=context.empresa, excel_path=context.path
            )
            if error:
                raise ValueError(error)
            users = list_users(self._session)
            return {"preview": preview or {}, "assignments": assignments or {}, "users": users}

        self._run(preview_operation, self._on_deudor_preview)

    def _start_local_deudor_import(self, context: _DebtorImportContext) -> None:
        self._set_busy(True, "Importando base local…")
        self.progress_deudores.setVisible(True)
        self.progress_deudores.setRange(0, 100)
        worker = CargaDeudoresWorker(
            CargaDeudoresParams(
                excel_path=context.path,
                empresa=context.empresa,
                sheet_name=str(context.mapping.get("sheet_name", "")),
                column_mapping=context.mapping,
            ),
            self,
        )
        self._workers.add(worker)
        worker.progress.connect(lambda value, _message: self.progress_deudores.setValue(value))
        worker.finished_ok.connect(lambda *_args: self._finish_local_deudor_import())
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(lambda: self._release_worker(worker))
        worker.start()

    def _finish_local_deudor_import(self) -> None:
        self._finish_busy(self.progress_deudores)
        self.txt_deudores.clear()
        self.datos_actualizados.emit()
        QMessageBox.information(self, "Carga completada", "La base de deudores fue integrada correctamente.")

    def _resolve_assignment_overrides(self, preview: dict, users: list[dict]) -> dict[str, int] | None:
        unresolved = [item for item in preview.get("matches", []) if not item.get("user_id")]
        active = [
            user for user in users
            if str(user.get("role", "")).lower() == "supervisor" and user.get("is_active")
        ]
        overrides: dict[str, int] = {}
        for item in unresolved:
            if not active:
                QMessageBox.warning(self, "Sin ejecutivas", "No hay supervisoras activas para relacionar.")
                return None
            labels = [f"{u.get('username', '')} — {u.get('email', '')}" for u in active]
            from PyQt6.QtWidgets import QInputDialog

            selected, accepted = QInputDialog.getItem(
                self,
                "Relacionar ejecutiva",
                f"Ejecutiva encontrada: {item.get('source_label', '')}",
                labels,
                0,
                False,
            )
            if not accepted:
                return None
            overrides[str(item.get("normalized_label", ""))] = int(active[labels.index(selected)]["id"])
        return overrides

    def _on_deudor_preview(self, payload: object, error: str) -> None:
        if error or not isinstance(payload, dict) or self._deudor_context is None:
            self._operation_failed(error or "Vista previa inválida.")
            return
        preview = payload.get("preview") or {}
        assignments = payload.get("assignments") or {}
        if int(assignments.get("conflicting_debtors", 0) or 0):
            self._operation_failed("Hay RUT con más de una ejecutiva responsable en el archivo.")
            return
        overrides = self._resolve_assignment_overrides(assignments, payload.get("users") or [])
        if overrides is None:
            self._finish_busy(self.progress_deudores)
            return
        birlados = len(preview.get("birlados", []) or [])
        answer = QMessageBox.question(
            self,
            "Confirmar carga",
            f"Registros: {int(preview.get('registros_archivo', 0) or 0):,}\n"
            f"Nuevos: {int(preview.get('nuevos_estimados', 0) or 0):,}\n"
            f"Cambiarán a Birlado: {birlados:,}\n\n¿Continuar?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._finish_busy(self.progress_deudores)
            return
        context = self._deudor_context

        def import_operation():
            result, err = backend_import_deudores(
                self._session,
                empresa=context.empresa,
                excel_path=context.path,
                expected_file_sha256=str(preview.get("file_sha256", "")),
                confirm_birlados=True,
                column_mapping=context.mapping,
                assignment_overrides=overrides,
            )
            if err:
                raise ValueError(err)
            verification, verify_error = backend_list_deudores(
                self._session,
                empresa=context.empresa,
                periodo_carga="",
                limit=1,
            )
            if verify_error:
                raise ValueError(
                    "La carga fue aceptada, pero no se pudo verificar su lectura posterior: "
                    f"{verify_error}"
                )
            output = dict(result or {})
            output["_verified"] = bool(verification)
            return output

        self._run(import_operation, self._on_deudor_imported)

    def _on_deudor_imported(self, result: object, error: str) -> None:
        if error or not isinstance(result, dict):
            self._operation_failed(error or "El backend no confirmó la carga.")
            return
        self._finish_busy(self.progress_deudores)
        self.txt_deudores.clear()
        self.datos_actualizados.emit()
        QMessageBox.information(
            self,
            "Carga completada",
            f"Registros nuevos: {int(result.get('detalle_nuevos', result.get('detalle_insertados', 0)) or 0):,}\n"
            f"Actualizados: {int(result.get('detalle_actualizados', 0) or 0):,}\n"
            f"Asignaciones aplicadas: {int(result.get('asignaciones_aplicadas', 0) or 0):,}",
        )

    def _start_distribution_update(self) -> None:
        path = self.txt_deudores.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Archivo no válido", "Selecciona la base que contiene la distribución.")
            return
        empresa = self.cmb_empresa.currentText().strip()
        self._set_busy(True, "Analizando distribución…")
        self.progress_deudores.setVisible(True)
        self.progress_deudores.setRange(0, 0)

        def operation():
            preview, error = backend_preview_debtor_assignments(
                self._session, empresa=empresa, excel_path=path
            )
            if error:
                raise ValueError(error)
            return {"preview": preview or {}, "users": list_users(self._session), "path": path, "empresa": empresa}

        self._run(operation, self._on_distribution_preview)

    def _on_distribution_preview(self, payload: object, error: str) -> None:
        if error or not isinstance(payload, dict):
            self._operation_failed(error or "Vista previa inválida.")
            return
        preview = payload["preview"]
        if int(preview.get("conflicting_debtors", 0) or 0):
            self._operation_failed("Hay RUT con más de una ejecutiva en el archivo.")
            return
        overrides = self._resolve_assignment_overrides(preview, payload["users"])
        if overrides is None:
            self._finish_busy(self.progress_deudores)
            return
        if QMessageBox.question(
            self,
            "Confirmar distribución",
            f"Se revisaron {int(preview.get('unique_debtors', 0) or 0):,} RUT. ¿Aplicar la distribución?",
        ) != QMessageBox.StandardButton.Yes:
            self._finish_busy(self.progress_deudores)
            return

        def operation():
            result, err = backend_apply_debtor_assignments(
                self._session,
                empresa=payload["empresa"],
                excel_path=payload["path"],
                expected_file_sha256=str(preview.get("file_sha256", "")),
                overrides=overrides,
            )
            if err:
                raise ValueError(err)
            return result or {}

        self._run(operation, self._on_distribution_applied)

    def _on_distribution_applied(self, result: object, error: str) -> None:
        if error or not isinstance(result, dict):
            self._operation_failed(error or "El backend no confirmó la distribución.")
            return
        self._finish_busy(self.progress_deudores)
        self.datos_actualizados.emit()
        QMessageBox.information(
            self,
            "Distribución aplicada",
            f"Asignados: {int(result.get('assigned_debtors', 0) or 0):,}\n"
            f"Reasignados: {int(result.get('reassigned_debtors', 0) or 0):,}",
        )

    def _save_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar plantilla de gestiones", "plantilla_gestiones.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        self._set_busy(True, "Generando plantilla…")
        self.progress_gestiones.setVisible(True)
        self.progress_gestiones.setRange(0, 0)

        def operation():
            common = {
                "Rut_Afiliado": "12345678",
                "Dv": "9",
                "Empresa": "",
                "Nombre_Afiliado": "Persona Ejemplo",
                "Estado": "Contactado",
                "Fecha_gestion": "2026-01-01",
            }
            sheets = {
                "SMS": pd.DataFrame([{**common, "telefono_movil_afiliado": "912345678", "Observacion": "Ejemplo SMS"}]),
                "Email": pd.DataFrame([{**common, "mail_afiliado": "persona@example.com", "Observacion": "Ejemplo Email"}]),
                "Carta": pd.DataFrame([{**common, "direccion_afiliado": "Calle Ejemplo 123", "comuna_afiliado": "Santiago", "Observacion": "Ejemplo Carta"}]),
            }
            write_excel_report(path, sheets)
            return path

        self._run(operation, lambda result, error: self._file_written(result, error, self.progress_gestiones, "Plantilla generada"))

    def _start_gestiones_import(self) -> None:
        path = self.txt_gestiones.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Archivo no válido", "Selecciona una base de gestiones válida.")
            return
        if not self._uses_backend():
            self._set_busy(True, "Importando gestiones…")
            self.progress_gestiones.setVisible(True)
            self.progress_gestiones.setRange(0, 100)
            worker = CargaGestionesWorker(CargaGestionesParams(path), self)
            self._workers.add(worker)
            worker.progress.connect(lambda value, _message: self.progress_gestiones.setValue(value))
            worker.finished_ok.connect(self._on_local_gestiones_imported)
            worker.failed.connect(self._operation_failed)
            worker.finished.connect(lambda: self._release_worker(worker))
            worker.start()
            return

        self._gestiones_path = path
        self._set_busy(True, "Analizando gestiones…")
        self.progress_gestiones.setVisible(True)
        self.progress_gestiones.setRange(0, 0)

        def operation():
            result, err = backend_preview_import_gestiones(self._session, excel_path=path)
            if err:
                raise ValueError(err)
            return result or {}

        self._run(operation, self._on_gestiones_preview)

    def _on_local_gestiones_imported(self, inserted: int, omitted: int, errors: list) -> None:
        self._finish_busy(self.progress_gestiones)
        self.txt_gestiones.clear()
        self.datos_actualizados.emit()
        QMessageBox.information(
            self, "Gestiones cargadas", f"Nuevas: {inserted:,}\nDuplicadas omitidas: {omitted:,}\nAdvertencias: {len(errors):,}"
        )

    def _on_gestiones_preview(self, preview: object, error: str) -> None:
        if error or not isinstance(preview, dict):
            self._operation_failed(error or "Vista previa inválida.")
            return
        overrides: dict[str, str] = {}
        ambiguous = preview.get("ambiguous_debtors", []) or []
        if ambiguous:
            dialog = GestionCompanyResolutionDialog(ambiguous, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._finish_busy(self.progress_gestiones)
                return
            overrides = dialog.company_overrides()
        path = self._gestiones_path

        def operation():
            result, err = backend_import_gestiones(
                self._session,
                excel_path=path,
                expected_file_sha256=str(preview.get("file_sha256", "")),
                company_overrides=overrides,
            )
            if err:
                raise ValueError(err)
            return result or {}

        self._run(operation, self._on_backend_gestiones_imported)

    def _on_backend_gestiones_imported(self, result: object, error: str) -> None:
        if error or not isinstance(result, dict):
            self._operation_failed(error or "El backend no confirmó la importación.")
            return
        self._finish_busy(self.progress_gestiones)
        self.txt_gestiones.clear()
        self.datos_actualizados.emit()
        QMessageBox.information(
            self,
            "Gestiones cargadas",
            f"Nuevas: {int(result.get('insertados', 0) or 0):,}\n"
            f"Duplicadas omitidas: {int(result.get('omitidos_duplicados', 0) or 0):,}\n"
            f"Deudores actualizados: {int(result.get('deudores_actualizados', 0) or 0):,}",
        )

    @staticmethod
    def _normalized_gestiones(df: pd.DataFrame) -> pd.DataFrame:
        preferred = [
            "Rut_Afiliado", "Nombre_Afiliado", "Tipo_gestion", "Estado",
            "Fecha_gestion", "Observacion", "Origen",
        ]
        renamed = df.rename(columns={
            "rut_afiliado": "Rut_Afiliado",
            "nombre_afiliado": "Nombre_Afiliado",
            "tipo_gestion": "Tipo_gestion",
            "estado": "Estado",
            "fecha_gestion": "Fecha_gestion",
            "observacion": "Observacion",
            "origen": "Origen",
        }).fillna("")
        first = [column for column in preferred if column in renamed.columns]
        return renamed[first + [column for column in renamed.columns if column not in first]]

    def _start_export(self) -> None:
        if not self.chk_full.isChecked() and self.date_from.date() > self.date_to.date():
            QMessageBox.warning(self, "Rango inválido", "La fecha inicial no puede superar a la final.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar base de gestiones", "base_gestiones.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        full = self.chk_full.isChecked()
        date_from = self.date_from.date().toString("dd/MM/yyyy") if not full else ""
        date_to = self.date_to.date().toString("dd/MM/yyyy") if not full else ""
        self._set_busy(True, "Exportando gestiones…")
        self.progress_export.setVisible(True)
        self.progress_export.setRange(0, 0)

        def operation():
            if self._uses_backend():
                rows, err = backend_list_all_gestiones(
                    self._session, fecha_desde=date_from, fecha_hasta=date_to
                )
                if err:
                    raise ValueError(err)
                frame = pd.DataFrame(rows)
            else:
                db_path = os.path.join(str(get_data_dir()), "db_gestiones.sqlite")
                if not os.path.exists(db_path):
                    raise ValueError("Aún no existe una base de gestiones para exportar.")
                with sqlite3.connect(db_path) as connection:
                    frame = pd.read_sql(f"SELECT * FROM {TABLA}", connection)
                if not full and not frame.empty:
                    dates = pd.to_datetime(frame.get("fecha_gestion", frame.get("Fecha_gestion")), dayfirst=True, errors="coerce")
                    start = pd.to_datetime(date_from, dayfirst=True)
                    end = pd.to_datetime(date_to, dayfirst=True)
                    frame = frame.loc[dates.between(start, end)].copy()
            frame = self._normalized_gestiones(frame)
            if frame.empty:
                raise ValueError("No hay gestiones para el criterio seleccionado.")
            write_excel_report(path, {"Gestiones": frame})
            return path

        self._run(operation, lambda result, error: self._file_written(result, error, self.progress_export, "Exportación completada"))

    def _file_written(self, result: object, error: str, progress: QProgressBar, title: str) -> None:
        if error or not result:
            self._operation_failed(error or "No fue posible generar el archivo.")
            return
        self._finish_busy(progress)
        QMessageBox.information(self, title, f"Archivo guardado en:\n{result}")

    def _operation_failed(self, error: str) -> None:
        for progress in (self.progress_deudores, self.progress_gestiones, self.progress_export):
            progress.setVisible(False)
            progress.setRange(0, 100)
        self._set_busy(False)
        QMessageBox.critical(self, "Operación no completada", str(error or "Error desconocido."))

    def _finish_busy(self, progress: QProgressBar) -> None:
        progress.setVisible(False)
        progress.setRange(0, 100)
        self._set_busy(False)
