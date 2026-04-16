from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog,
    QMessageBox, QComboBox, QProgressBar, QCheckBox, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy, QScrollArea
)

from .config_empresas import obtener_config_empresa
from .models import ConciliacionParams
from .ui import Card
from .worker import ConciliacionWorker


class ConciliacionTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        header = QHBoxLayout()
        t = QLabel("Conciliación de Nóminas")
        t.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        header.addWidget(t)
        header.addStretch(1)
        self.lbl_company = QLabel("Compañía seleccionada: —")
        self.lbl_company.setObjectName("HeaderHint")
        header.addWidget(self.lbl_company)
        main_layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._splitter = splitter
        main_layout.addWidget(splitter, 1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setMinimumWidth(200)
        left_scroll.setMaximumWidth(520)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(12)

        card_form = Card(
            "Carga y configuración",
            "Cruza mes anterior vs mes actual y genera un reporte Excel con altas, bajas y duplicados."
        )
        card_form.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        row_emp = QHBoxLayout()
        row_emp.addWidget(QLabel("Compañía:"))
        self.cmb_empresa = QComboBox()
        self.cmb_empresa.addItems(["Colmena", "Consalud", "Cruz Blanca"])
        self.cmb_empresa.currentTextChanged.connect(self._on_company_changed)
        row_emp.addWidget(self.cmb_empresa, 1)
        card_form.body.addLayout(row_emp)

        self.txt_anterior = QLineEdit()
        self.txt_anterior.setPlaceholderText("Selecciona Mes Anterior (.xlsx)")
        btn_anterior = QPushButton("Seleccionar Mes Anterior (.xlsx)")
        btn_anterior.clicked.connect(self.pick_anterior)
        block1 = QVBoxLayout()
        block1.addWidget(QLabel("Archivo Mes Anterior:"))
        block1.addWidget(self.txt_anterior)
        block1.addWidget(btn_anterior)
        card_form.body.addLayout(block1)

        self.txt_actual = QLineEdit()
        self.txt_actual.setPlaceholderText("Selecciona Mes Actual (.xlsx)")
        btn_actual = QPushButton("Seleccionar Mes Actual (.xlsx)")
        btn_actual.clicked.connect(self.pick_actual)
        block2 = QVBoxLayout()
        block2.addWidget(QLabel("Archivo Mes Actual:"))
        block2.addWidget(self.txt_actual)
        block2.addWidget(btn_actual)
        card_form.body.addLayout(block2)

        self.txt_salida = QLineEdit()
        self.txt_salida.setPlaceholderText("Selecciona dónde guardar el reporte (.xlsx)")
        btn_salida = QPushButton("Guardar como...")
        btn_salida.clicked.connect(self.pick_salida)
        block3 = QVBoxLayout()
        block3.addWidget(QLabel("Archivo de salida:"))
        block3.addWidget(self.txt_salida)
        block3.addWidget(btn_salida)
        card_form.body.addLayout(block3)

        self.chk_export_both = QCheckBox("Exportar también 'En ambos meses' (más lento)")
        card_form.body.addWidget(self.chk_export_both)

        self.lbl_reglas = QLabel()
        self.lbl_reglas.setObjectName("MutedLabel")
        self.lbl_reglas.setWordWrap(True)
        card_form.body.addWidget(self.lbl_reglas)

        actions = QHBoxLayout()
        self.btn_run = QPushButton("Ejecutar conciliación")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self.run_conciliacion)
        self.btn_new = QPushButton("Nueva conciliación")
        self.btn_new.clicked.connect(self.reset_form)
        actions.addWidget(self.btn_run, 1)
        actions.addWidget(self.btn_new, 1)
        card_form.body.addLayout(actions)

        self.progress = QProgressBar()
        self.lbl_status = QLabel("Listo para conciliar.")
        self.lbl_status.setObjectName("StatusLabel")
        card_form.body.addWidget(self.progress)
        card_form.body.addWidget(self.lbl_status)
        left_layout.addWidget(card_form, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        card_results = Card("Previsualización de resultados", "Verás las métricas del resumen al finalizar.")
        self.tbl_metrics = QTableWidget(0, 2)
        self.tbl_metrics.setHorizontalHeaderLabels(["Métrica", "Valor"])
        self.tbl_metrics.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_metrics.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_metrics.verticalHeader().setVisible(False)
        card_results.body.addWidget(self.tbl_metrics, 1)
        self.lbl_out_hint = QLabel("Reporte: —")
        self.lbl_out_hint.setObjectName("MutedLabel")
        card_results.body.addWidget(self.lbl_out_hint)
        right_layout.addWidget(card_results, 1)

        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 9999])

        self._on_company_changed(self.cmb_empresa.currentText())

    def showEvent(self, event):
        super().showEvent(event)
        self._ajustar_splitter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar_splitter()

    def _ajustar_splitter(self) -> None:
        total = max(self._splitter.width(), self.width(), 1)
        left_target = int(total * 0.33)
        left_target = max(220, min(500, left_target))
        right_min = 360
        if total - left_target < right_min:
            left_target = max(200, total - right_min)
        self._splitter.setSizes([left_target, max(total - left_target, right_min)])

    def pick_anterior(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar Mes Anterior", "", "Excel (*.xlsx)")
        if path:
            self.txt_anterior.setText(path)
            self._suggest_output_if_missing()

    def pick_actual(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar Mes Actual", "", "Excel (*.xlsx)")
        if path:
            self.txt_actual.setText(path)
            self._suggest_output_if_missing()

    def pick_salida(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar reporte como", "resultado_conciliacion.xlsx", "Excel (*.xlsx)")
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.txt_salida.setText(path)

    def _suggest_output_if_missing(self):
        if self.txt_salida.text().strip():
            return
        a = self.txt_anterior.text().strip()
        if a:
            self.txt_salida.setText(os.path.join(os.path.dirname(a) or os.getcwd(), "resultado_conciliacion.xlsx"))

    def _validate_inputs(self) -> bool:
        a, b, o = self.txt_anterior.text().strip(), self.txt_actual.text().strip(), self.txt_salida.text().strip()
        if not a or not b:
            QMessageBox.warning(self, "Faltan archivos", "Debes seleccionar Mes Anterior y Mes Actual.")
            return False
        if not os.path.exists(a) or not os.path.exists(b):
            QMessageBox.warning(self, "Archivo no encontrado", "Verifica que ambos archivos existan.")
            return False
        if not a.lower().endswith(".xlsx") or not b.lower().endswith(".xlsx"):
            QMessageBox.warning(self, "Formato inválido", "Los archivos deben ser .xlsx")
            return False
        if not o:
            QMessageBox.warning(self, "Falta salida", "Debes indicar un archivo de salida.")
            return False
        return True

    def run_conciliacion(self):
        if not self._validate_inputs():
            return
        cfg_empresa = obtener_config_empresa(self.cmb_empresa.currentText())
        self._set_running(True)
        self.progress.setValue(0)
        self.lbl_status.setText("Iniciando...")
        params = ConciliacionParams(
            empresa=self.cmb_empresa.currentText(),
            mes_anterior_path=self.txt_anterior.text().strip(),
            mes_actual_path=self.txt_actual.text().strip(),
            salida_path=self.txt_salida.text().strip(),
            sheet_name=cfg_empresa["sheet_name"],
            id_columns=cfg_empresa["id_columns"],
            required_columns=cfg_empresa["required_columns"],
            export_both=self.chk_export_both.isChecked(),
        )
        self.worker = ConciliacionWorker(params)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished_ok)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_progress(self, pct: int, msg: str):
        self.progress.setValue(pct)
        self.lbl_status.setText(msg)

    def on_finished_ok(self, out_path: str, metrics: dict):
        self._set_running(False)
        self.lbl_status.setText("Listo ✅ Conciliación finalizada.")
        self.lbl_out_hint.setText(f"Reporte: {out_path}")
        self._set_metrics_preview(metrics)
        QMessageBox.information(self, "Conciliación finalizada", f"Reporte generado:\n{out_path}")

    def on_failed(self, err: str):
        self._set_running(False)
        self.progress.setValue(0)
        self.lbl_status.setText("Ocurrió un error ❌")
        QMessageBox.critical(self, "Error al conciliar", err)

    def reset_form(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "En proceso", "Hay una conciliación ejecutándose.")
            return
        self.txt_anterior.clear(); self.txt_actual.clear(); self.txt_salida.clear()
        self.chk_export_both.setChecked(False)
        self.progress.setValue(0)
        self.lbl_status.setText("Listo para conciliar.")
        self.lbl_out_hint.setText("Reporte: —")
        self.tbl_metrics.setRowCount(0)

    def _set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_new.setEnabled(not running)

    def _on_company_changed(self, value: str):
        self.lbl_company.setText(f"Compañía seleccionada: {value}")
        cfg = obtener_config_empresa(value)
        self.lbl_reglas.setText(
            f"Hoja: {cfg['sheet_name']} | ID: {' + '.join(cfg['id_columns'])} | "
            f"Columnas requeridas: {', '.join(cfg['required_columns'])}"
        )

    def _set_metrics_preview(self, metrics: dict):
        rows = list(metrics.items())
        self.tbl_metrics.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.tbl_metrics.setItem(r, 0, QTableWidgetItem(str(k)))
            self.tbl_metrics.setItem(r, 1, QTableWidgetItem(str(v)))
