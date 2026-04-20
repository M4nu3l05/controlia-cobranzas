from __future__ import annotations

import datetime
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from deudores.database import (
    EMPRESAS,
    cargar_contactos_empresa,
    cargar_contactos_todas,
    cargar_para_envio,
)
from deudores.gestiones_db import (
    ESTADO_DEUDOR_DEFAULT,
    insertar_gestion_manual,
    obtener_estados_deudor_por_rut,
)
from auth.auth_service import backend_create_gestion, backend_list_destinatarios
from .config import config_completa
from .plantillas import cargar_plantillas
from .ui_components import (
    Card,
    _COLOR_ENVIADO,
    _COLOR_FALLIDO,
    _COLOR_OMITIDO,
    _COLOR_PENDIENTE,
    _ESTADO_ENVIADO,
    _ESTADO_NO_ENVIADO,
    _ESTADO_OMITIDO,
    _ESTADO_PENDIENTE,
    _LOG_DETALLE,
    _LOG_EMAIL,
    _LOG_ESTADO,
)
from .worker import EnvioParams, EnvioWorker, ResultadoEnvio


METRICAS_MONTO = {
    "Sin filtro de monto": "",
    "Copago ($)": "Copago",
    "Total Pagos ($)": "Total_Pagos",
    "Saldo Actual ($)": "Saldo_Actual",
}


class TabEnvio(QWidget):
    def __init__(self, get_config_fn, get_plantilla_fn, parent=None, session=None):
        super().__init__(parent)
        self._get_config = get_config_fn
        self._get_plantilla = get_plantilla_fn
        self._session = session
        self._worker: EnvioWorker | None = None
        self._df_dest: pd.DataFrame | None = None
        self._df_base_segmentacion: pd.DataFrame | None = None
        self._col_email: str = "mail_afiliado"
        self._email_to_rows: dict[str, list[int]] = {}
        self._envio_payload_by_email: dict[str, list[dict]] = {}
        self._gestiones_pendientes_registro: list[dict] = []
        self._plantilla_envio_nombre: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel("Envío masivo de correos")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hdr.addWidget(title)
        hdr.addStretch(1)
        self.lbl_total_dest = QLabel("Sin destinatarios")
        self.lbl_total_dest.setObjectName("HeaderHint")
        hdr.addWidget(self.lbl_total_dest)
        layout.addLayout(hdr)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.setOpaqueResize(False)
        self._splitter = splitter
        layout.addWidget(splitter, 1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setMinimumWidth(220)
        left_scroll.setMaximumWidth(520)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.setSpacing(12)

        # ---------------------------------------------------------
        # Destinatarios base
        # ---------------------------------------------------------
        card_dest = Card(
            "Destinatarios",
            "Selecciona la compañía y aplica filtros para construir una campaña más precisa.",
        )

        row_emp = QHBoxLayout()
        row_emp.addWidget(QLabel("Compañía:"))
        self.cmb_empresa_filtro = QComboBox()
        self.cmb_empresa_filtro.addItem("Todas las compañías")
        self.cmb_empresa_filtro.addItems(EMPRESAS)
        row_emp.addWidget(self.cmb_empresa_filtro, 1)
        card_dest.body.addLayout(row_emp)

        self.chk_solo_validos = QCheckBox("Solo emails válidos")
        self.chk_solo_validos.setChecked(True)
        card_dest.body.addWidget(self.chk_solo_validos)

        self.chk_excluir_enviados = QCheckBox("Excluir emails ya enviados en esta carga")
        self.chk_excluir_enviados.setChecked(False)
        card_dest.body.addWidget(self.chk_excluir_enviados)

        ll.addWidget(card_dest)

        # ---------------------------------------------------------
        # Segmentación CRM
        # ---------------------------------------------------------
        card_seg = Card(
            "Segmentación de campaña",
            "Filtra por estado deudor, rangos de monto o prioriza automáticamente los montos más altos.",
        )

        form_seg = QFormLayout()
        form_seg.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_seg.setSpacing(10)

        self.cmb_estado_deudor = QComboBox()
        self.cmb_estado_deudor.addItem("Todos los estados")
        form_seg.addRow("Estado deudor:", self.cmb_estado_deudor)

        self.cmb_metrica_monto = QComboBox()
        self.cmb_metrica_monto.addItems(list(METRICAS_MONTO.keys()))
        self.cmb_metrica_monto.currentTextChanged.connect(self._on_cambio_metrica)
        form_seg.addRow("Filtro por monto:", self.cmb_metrica_monto)

        self.txt_monto_min = QLineEdit()
        self.txt_monto_min.setPlaceholderText("Ej: 50000")
        form_seg.addRow("Monto desde:", self.txt_monto_min)

        self.txt_monto_max = QLineEdit()
        self.txt_monto_max.setPlaceholderText("Ej: 250000")
        form_seg.addRow("Monto hasta:", self.txt_monto_max)

        self.chk_top_montos = QCheckBox("Priorizar solo los montos más altos")
        self.chk_top_montos.toggled.connect(self._toggle_top_n)
        form_seg.addRow("Selección top:", self.chk_top_montos)

        self.spn_top_n = QSpinBox()
        self.spn_top_n.setRange(1, 50000)
        self.spn_top_n.setValue(100)
        self.spn_top_n.setEnabled(False)
        form_seg.addRow("Top N destinatarios:", self.spn_top_n)

        card_seg.body.addLayout(form_seg)

        self.lbl_segmento = QLabel(
            "Campaña sugerida: combina Estado deudor + monto para construir campañas tipo CRM."
        )
        self.lbl_segmento.setObjectName("MutedLabel")
        self.lbl_segmento.setWordWrap(True)
        card_seg.body.addWidget(self.lbl_segmento)

        btn_cargar_dest = QPushButton("🔄  Cargar destinatarios filtrados")
        btn_cargar_dest.setObjectName("PrimaryButton")
        btn_cargar_dest.clicked.connect(self._cargar_log)
        card_seg.body.addWidget(btn_cargar_dest)

        self.lbl_dest_info = QLabel("Pulsa 'Cargar destinatarios filtrados' para generar la campaña.")
        self.lbl_dest_info.setObjectName("MutedLabel")
        self.lbl_dest_info.setWordWrap(True)
        card_seg.body.addWidget(self.lbl_dest_info)

        ll.addWidget(card_seg)

        # ---------------------------------------------------------
        # Plantilla
        # ---------------------------------------------------------
        card_pl = Card("Plantilla de correo", "")
        self.cmb_plantilla = QComboBox()
        self.cmb_plantilla.currentIndexChanged.connect(self._preview_plantilla)
        card_pl.body.addWidget(self.cmb_plantilla)
        card_pl.body.addWidget(QLabel("Vista previa asunto:"))
        self.txt_preview_asunto = QLineEdit()
        self.txt_preview_asunto.setReadOnly(True)
        card_pl.body.addWidget(self.txt_preview_asunto)
        ll.addWidget(card_pl)

        # ---------------------------------------------------------
        # Opciones
        # ---------------------------------------------------------
        card_ops = Card("Opciones", "")
        row_pausa = QHBoxLayout()
        row_pausa.addWidget(QLabel("Pausa entre envíos (seg):"))
        self.spn_pausa = QSpinBox()
        self.spn_pausa.setRange(1, 30)
        self.spn_pausa.setValue(2)
        row_pausa.addWidget(self.spn_pausa)
        row_pausa.addStretch(1)
        card_ops.body.addLayout(row_pausa)
        ll.addWidget(card_ops)

        self.btn_enviar = QPushButton("📤  Iniciar envío")
        self.btn_enviar.setObjectName("PrimaryButton")
        self.btn_enviar.setEnabled(False)
        self.btn_enviar.clicked.connect(self._iniciar_envio)
        ll.addWidget(self.btn_enviar)

        self.btn_cancelar = QPushButton("⏹  Cancelar envío")
        self.btn_cancelar.setEnabled(False)
        self.btn_cancelar.clicked.connect(self._cancelar)
        ll.addWidget(self.btn_cancelar)
        ll.addStretch(1)

        # ---------------------------------------------------------
        # Panel derecho
        # ---------------------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)

        card_prog = Card("Progreso del envío", "")
        self.progress = QProgressBar()
        self.progress.setValue(0)
        card_prog.body.addWidget(self.progress)

        self.lbl_prog = QLabel("Carga los destinatarios y pulsa 'Iniciar envío'.")
        self.lbl_prog.setObjectName("StatusLabel")
        self.lbl_prog.setWordWrap(True)
        card_prog.body.addWidget(self.lbl_prog)

        row_cnt = QHBoxLayout()
        self.lbl_cnt_enviados = QLabel("✅ Enviados: 0")
        self.lbl_cnt_fallidos = QLabel("❌ No enviados: 0")
        self.lbl_cnt_omitidos = QLabel("⚠️ Sin email: 0")
        self.lbl_cnt_pendiente = QLabel("⏳ Pendientes: 0")
        for l in (
            self.lbl_cnt_enviados,
            self.lbl_cnt_fallidos,
            self.lbl_cnt_omitidos,
            self.lbl_cnt_pendiente,
        ):
            l.setObjectName("MutedLabel")
            row_cnt.addWidget(l)
        row_cnt.addStretch(1)
        card_prog.body.addLayout(row_cnt)
        rl.addWidget(card_prog)

        card_log = Card("Log de envíos", "Todos los destinatarios aparecen aquí con su estado en tiempo real.")
        self.tbl_log = QTableWidget(0, 4)
        self.tbl_log.setHorizontalHeaderLabels(["Email", "Nombre", "Estado", "Detalle"])
        hh = self.tbl_log.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl_log.verticalHeader().setVisible(False)
        self.tbl_log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_log.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card_log.body.addWidget(self.tbl_log, 1)

        btn_log_row = QHBoxLayout()
        btn_log_row.addStretch(1)
        btn_clear = QPushButton("🧹  Limpiar log")
        btn_clear.clicked.connect(self._limpiar_log)
        btn_log_row.addWidget(btn_clear)
        card_log.body.addLayout(btn_log_row)

        rl.addWidget(card_log, 1)

        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 9999])

        self._refrescar_plantillas()
        self._on_cambio_metrica(self.cmb_metrica_monto.currentText())
        self._actualizar_contadores()
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._ajustar_splitter_inicial)
        QTimer.singleShot(120, self._ajustar_splitter_inicial)

    def _usa_backend_envios(self) -> bool:
        return bool(self._session and getattr(self._session, "auth_source", "") == "backend")

    def _ajustar_splitter_inicial(self) -> None:
        if not hasattr(self, "_splitter"):
            return

        parent_width = self._splitter.parentWidget().width() if self._splitter.parentWidget() else 0
        total = max(self._splitter.width(), self.width(), parent_width, 1)

        left_target = int(total * 0.33)
        left_target = max(240, min(520, left_target))

        right_min = 460 if total >= 980 else 340
        if total - left_target < right_min:
            left_target = max(220, total - right_min)

        right_target = max(right_min, total - left_target)
        self._splitter.setSizes([left_target, right_target])

    def showEvent(self, event):
        super().showEvent(event)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._ajustar_splitter_inicial)
        QTimer.singleShot(120, self._ajustar_splitter_inicial)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._ajustar_splitter_si_hace_falta)

    def _ajustar_splitter_si_hace_falta(self) -> None:
        if not hasattr(self, "_splitter"):
            return

        sizes = self._splitter.sizes()
        if len(sizes) != 2:
            return

        left_size, right_size = sizes
        if left_size < 230 or right_size < 330:
            self._ajustar_splitter_inicial()

    # =========================================================
    # Utilidades UI
    # =========================================================
    def _toggle_top_n(self, checked: bool):
        self.spn_top_n.setEnabled(checked)

    def _on_cambio_metrica(self, texto: str):
        habilitado = bool(METRICAS_MONTO.get(texto, ""))
        self.txt_monto_min.setEnabled(habilitado)
        self.txt_monto_max.setEnabled(habilitado)
        if not habilitado:
            self.txt_monto_min.clear()
            self.txt_monto_max.clear()

    def _refrescar_plantillas(self):
        self.cmb_plantilla.blockSignals(True)
        self.cmb_plantilla.clear()
        for p in cargar_plantillas(self._session):
            self.cmb_plantilla.addItem(p.get("nombre", "Sin nombre"))
        self.cmb_plantilla.blockSignals(False)
        self._preview_plantilla()

    def _preview_plantilla(self):
        idx = self.cmb_plantilla.currentIndex()
        pls = cargar_plantillas(self._session)
        if 0 <= idx < len(pls):
            self.txt_preview_asunto.setText(pls[idx].get("asunto", ""))
        else:
            self.txt_preview_asunto.clear()

    def _set_fila_log(self, row: int, email: str, nombre: str, estado: str, detalle: str, color: QColor):
        for col, val in enumerate([email, nombre, estado, detalle]):
            item = self.tbl_log.item(row, col)
            if item is None:
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl_log.setItem(row, col, item)
            else:
                item.setText(val)
            item.setBackground(color)

    def _actualizar_contadores(self):
        enviados = pendientes = fallidos = omitidos = 0
        for r in range(self.tbl_log.rowCount()):
            item = self.tbl_log.item(r, _LOG_ESTADO)
            if item is None:
                continue
            txt = item.text()
            if txt == _ESTADO_ENVIADO:
                enviados += 1
            elif txt == _ESTADO_NO_ENVIADO:
                fallidos += 1
            elif txt == _ESTADO_OMITIDO:
                omitidos += 1
            else:
                pendientes += 1

        self.lbl_cnt_enviados.setText(f"✅ Enviados: {enviados}")
        self.lbl_cnt_fallidos.setText(f"❌ No enviados: {fallidos}")
        self.lbl_cnt_omitidos.setText(f"⚠️ Sin email: {omitidos}")
        self.lbl_cnt_pendiente.setText(f"⏳ Pendientes: {pendientes}")

    def _limpiar_log(self):
        self.tbl_log.setRowCount(0)
        self._email_to_rows.clear()
        self._envio_payload_by_email.clear()
        self._gestiones_pendientes_registro.clear()
        self._df_dest = None
        self.btn_enviar.setEnabled(False)
        self.lbl_dest_info.setText("Log limpiado. Pulsa 'Cargar destinatarios filtrados'.")
        self.lbl_total_dest.setText("Sin destinatarios")
        self.progress.setValue(0)
        self._actualizar_contadores()

    def _email_key(self, value: str) -> str:
        return str(value or "").strip().lower()

    def _find_row_for_email(self, email: str, *, consume: bool) -> int | None:
        key = self._email_key(email)
        if not key:
            return None

        rows = self._email_to_rows.get(key, [])
        while rows:
            candidate = rows[0]
            item = self.tbl_log.item(candidate, _LOG_ESTADO)
            estado = item.text() if item else ""
            if estado in (_ESTADO_PENDIENTE, "📨 Enviando…"):
                if consume:
                    rows.pop(0)
                return candidate
            rows.pop(0)

        # Fallback defensivo: busca la primera fila pendiente con ese email.
        for r in range(self.tbl_log.rowCount()):
            email_item = self.tbl_log.item(r, _LOG_EMAIL)
            estado_item = self.tbl_log.item(r, _LOG_ESTADO)
            if not email_item or not estado_item:
                continue
            if self._email_key(email_item.text()) != key:
                continue
            if estado_item.text() in (_ESTADO_PENDIENTE, "📨 Enviando…"):
                return r

        return None

    def _pop_payload_for_email(self, email: str) -> dict | None:
        key = self._email_key(email)
        if not key:
            return None
        rows = self._envio_payload_by_email.get(key, [])
        if not rows:
            return None
        return rows.pop(0)

    # =========================================================
    # Utilidades de datos
    # =========================================================
    def _normalizar_rut(self, valor) -> str:
        return str(valor or "").strip().replace(".", "").replace("-", "")

    def _email_valido(self, valor) -> bool:
        email = str(valor or "").strip()
        return email not in ("", "nan", "None", "NaN", "N", "—") and "@" in email

    def _parse_float(self, valor) -> float | None:
        texto = str(valor or "").strip()
        if texto in ("", "nan", "None", "NaN", "N", "—"):
            return None

        texto = texto.replace("$", "").replace(" ", "")

        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(",", ".")

        try:
            return float(texto)
        except Exception:
            try:
                return float(texto.replace(".", ""))
            except Exception:
                return None

    def _enriquecer_destinatarios(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        df_out = df.copy()

        if "mail_afiliado" not in df_out.columns:
            df_out["mail_afiliado"] = ""
        if "Nombre_Afiliado" not in df_out.columns:
            df_out["Nombre_Afiliado"] = ""
        if "_empresa" not in df_out.columns:
            df_out["_empresa"] = ""

        if self._usa_backend_envios() and "Estado_deudor" in df_out.columns:
            df_out["Estado_deudor"] = (
                df_out["Estado_deudor"].astype(str).str.strip().replace({"nan": "", "None": ""}).replace("", ESTADO_DEUDOR_DEFAULT)
            )
        else:
            mapa_estados = obtener_estados_deudor_por_rut()
            if "Rut_Afiliado" in df_out.columns:
                rut_norm = df_out["Rut_Afiliado"].apply(self._normalizar_rut)
                df_out["Estado_deudor"] = rut_norm.map(mapa_estados).fillna(ESTADO_DEUDOR_DEFAULT)
            else:
                df_out["Estado_deudor"] = ESTADO_DEUDOR_DEFAULT

        df_out["_email_valido"] = df_out["mail_afiliado"].apply(self._email_valido)
        df_out["_monto_copago"] = df_out.get("Copago", pd.Series(index=df_out.index, dtype=object)).apply(self._parse_float)
        df_out["_monto_total_pagos"] = df_out.get("Total_Pagos", pd.Series(index=df_out.index, dtype=object)).apply(self._parse_float)
        df_out["_monto_saldo_actual"] = df_out.get("Saldo_Actual", pd.Series(index=df_out.index, dtype=object)).apply(self._parse_float)

        return df_out

    def _actualizar_combo_estados(self, df: pd.DataFrame):
        estado_actual = self.cmb_estado_deudor.currentText()
        estados = []

        if df is not None and not df.empty and "Estado_deudor" in df.columns:
            estados = sorted(
                [
                    str(v).strip()
                    for v in df["Estado_deudor"].dropna().unique().tolist()
                    if str(v).strip()
                ]
            )

        self.cmb_estado_deudor.blockSignals(True)
        self.cmb_estado_deudor.clear()
        self.cmb_estado_deudor.addItem("Todos los estados")
        self.cmb_estado_deudor.addItems(estados)

        idx = self.cmb_estado_deudor.findText(estado_actual)
        if idx >= 0:
            self.cmb_estado_deudor.setCurrentIndex(idx)

        self.cmb_estado_deudor.blockSignals(False)

    def _columna_metrica_actual(self) -> str:
        return METRICAS_MONTO.get(self.cmb_metrica_monto.currentText(), "")

    def _serie_monto(self, df: pd.DataFrame, columna_metrica: str) -> pd.Series:
        if columna_metrica == "Copago":
            return df["_monto_copago"]
        if columna_metrica == "Total_Pagos":
            return df["_monto_total_pagos"]
        if columna_metrica == "Saldo_Actual":
            return df["_monto_saldo_actual"]
        return pd.Series(index=df.index, dtype=float)

    def _aplicar_filtros(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        if df is None or df.empty:
            return pd.DataFrame(), []

        filtrado = df.copy()
        resumen: list[str] = []

        empresa = self.cmb_empresa_filtro.currentText()
        if empresa != "Todas las compañías" and "_empresa" in filtrado.columns:
            filtrado = filtrado[filtrado["_empresa"].astype(str).str.strip() == empresa]
            resumen.append(f"Compañía: {empresa}")

        estado = self.cmb_estado_deudor.currentText().strip()
        if estado and estado != "Todos los estados" and "Estado_deudor" in filtrado.columns:
            filtrado = filtrado[filtrado["Estado_deudor"].astype(str).str.strip() == estado]
            resumen.append(f"Estado: {estado}")

        if self.chk_solo_validos.isChecked() and "_email_valido" in filtrado.columns:
            filtrado = filtrado[filtrado["_email_valido"]]
            resumen.append("Solo emails válidos")

        columna_metrica = self._columna_metrica_actual()
        serie_monto = self._serie_monto(filtrado, columna_metrica) if columna_metrica else None

        monto_min_txt = self.txt_monto_min.text().strip()
        monto_max_txt = self.txt_monto_max.text().strip()
        monto_min = self._parse_float(monto_min_txt) if monto_min_txt else None
        monto_max = self._parse_float(monto_max_txt) if monto_max_txt else None

        if (monto_min_txt or monto_max_txt or self.chk_top_montos.isChecked()) and not columna_metrica:
            raise ValueError("Debes seleccionar una métrica de monto antes de aplicar rango o top de mayores montos.")

        if monto_min_txt and monto_min is None:
            raise ValueError("El valor 'Monto desde' no es válido.")
        if monto_max_txt and monto_max is None:
            raise ValueError("El valor 'Monto hasta' no es válido.")
        if monto_min is not None and monto_max is not None and monto_min > monto_max:
            raise ValueError("'Monto desde' no puede ser mayor que 'Monto hasta'.")

        if columna_metrica:
            if monto_min is not None:
                filtrado = filtrado[serie_monto.fillna(-1) >= monto_min]
                serie_monto = self._serie_monto(filtrado, columna_metrica)

            if monto_max is not None:
                filtrado = filtrado[serie_monto.fillna(float("inf")) <= monto_max]
                serie_monto = self._serie_monto(filtrado, columna_metrica)

            if monto_min is not None or monto_max is not None:
                etiqueta = self.cmb_metrica_monto.currentText()
                desde_txt = monto_min_txt or "0"
                hasta_txt = monto_max_txt or "sin tope"
                resumen.append(f"{etiqueta}: {desde_txt} a {hasta_txt}")

            if self.chk_top_montos.isChecked():
                top_n = int(self.spn_top_n.value())
                filtrado = filtrado.assign(_orden_top=serie_monto).sort_values(
                    by=["_orden_top", "Nombre_Afiliado"],
                    ascending=[False, True],
                    na_position="last",
                    kind="mergesort",
                ).head(top_n).drop(columns=["_orden_top"])
                resumen.append(f"Top {top_n} por {self.cmb_metrica_monto.currentText()}")

        if self.chk_excluir_enviados.isChecked() and self.tbl_log.rowCount() > 0:
            enviados_previos = {
                self.tbl_log.item(r, _LOG_EMAIL).text().strip().lower()
                for r in range(self.tbl_log.rowCount())
                if self.tbl_log.item(r, _LOG_ESTADO)
                and self.tbl_log.item(r, _LOG_ESTADO).text() == _ESTADO_ENVIADO
                and self.tbl_log.item(r, _LOG_EMAIL)
            }
            if enviados_previos:
                filtrado = filtrado[
                    ~filtrado["mail_afiliado"].astype(str).str.strip().str.lower().isin(enviados_previos)
                ]
                resumen.append("Excluye enviados previos")

        return filtrado.reset_index(drop=True), resumen

    # =========================================================
    # Carga y envío
    # =========================================================
    def _cargar_log(self):
        empresa = self.cmb_empresa_filtro.currentText()
        emp_param = "" if empresa == "Todas las compañías" else empresa

        df = pd.DataFrame()
        if self._usa_backend_envios():
            rows, err = backend_list_destinatarios(
                self._session,
                empresa=emp_param,
                limit=50000,
            )
            if err:
                QMessageBox.warning(self, "Error al cargar destinatarios", err)
                return
            if rows:
                df = pd.DataFrame(
                    [
                        {
                            "_empresa": str(r.get("empresa", "")).strip(),
                            "Rut_Afiliado": str(r.get("rut_afiliado", "")).strip(),
                            "Nombre_Afiliado": str(r.get("nombre_afiliado", "")).strip(),
                            "mail_afiliado": str(r.get("mail_afiliado", "")).strip(),
                            "Estado_deudor": str(r.get("estado_deudor", "")).strip(),
                            "Copago": r.get("copago", 0),
                            "Total_Pagos": r.get("total_pagos", 0),
                            "Saldo_Actual": r.get("saldo_actual", 0),
                        }
                        for r in rows
                    ]
                )
        else:
            df = cargar_para_envio(emp_param)
            if df.empty or "mail_afiliado" not in df.columns or df["mail_afiliado"].astype(str).str.strip().eq("").all():
                df = cargar_contactos_empresa(emp_param) if emp_param else cargar_contactos_todas()

        if df.empty:
            QMessageBox.warning(self, "Sin datos", "Carga antes una base en Búsqueda de Deudores.")
            return

        if "mail_afiliado" not in df.columns:
            QMessageBox.warning(self, "Sin columna email", "No se encontró 'mail_afiliado' en la base de datos.")
            return

        df = self._enriquecer_destinatarios(df)
        self._df_base_segmentacion = df
        self._actualizar_combo_estados(df)

        try:
            df_filtrado, resumen = self._aplicar_filtros(df)
        except ValueError as e:
            QMessageBox.warning(self, "Filtros inválidos", str(e))
            return

        if df_filtrado.empty:
            self._limpiar_log()
            self.lbl_segmento.setText("No se encontraron destinatarios con los criterios actuales.")
            QMessageBox.information(
                self,
                "Sin coincidencias",
                "No se encontraron destinatarios que cumplan los criterios seleccionados.",
            )
            return

        self._df_dest = df_filtrado
        self._col_email = "mail_afiliado"
        self.tbl_log.setRowCount(0)
        self._email_to_rows.clear()

        total = len(df_filtrado)
        n_validos = 0
        n_sin = 0

        for _, fila in df_filtrado.iterrows():
            email = str(fila.get("mail_afiliado", "")).strip()
            nombre = str(fila.get("Nombre_Afiliado", "")).strip()

            email = "" if email in ("nan", "None", "NaN", "N") else email
            nombre = "" if nombre in ("nan", "None", "NaN") else nombre

            valido = self._email_valido(email)
            row = self.tbl_log.rowCount()
            self.tbl_log.insertRow(row)

            if valido:
                estado, color = _ESTADO_PENDIENTE, _COLOR_PENDIENTE
                n_validos += 1
                key = self._email_key(email)
                if key:
                    self._email_to_rows.setdefault(key, []).append(row)
            else:
                estado, color = _ESTADO_OMITIDO, _COLOR_OMITIDO
                n_sin += 1
                email = email or "(sin email)"

            detalle_partes = [
                str(fila.get("_empresa", "—")).strip() or "—",
                str(fila.get("Estado_deudor", ESTADO_DEUDOR_DEFAULT)).strip() or ESTADO_DEUDOR_DEFAULT,
            ]

            col_metrica = self._columna_metrica_actual()
            if col_metrica:
                valor_metrica = fila.get(col_metrica, "")
                if str(valor_metrica).strip():
                    detalle_partes.append(f"{self.cmb_metrica_monto.currentText()}: {valor_metrica}")

            detalle = " | ".join(detalle_partes)
            self._set_fila_log(row, email, nombre, estado, detalle, color)

        resumen_txt = " | ".join(resumen) if resumen else "Sin filtros avanzados"
        self.lbl_segmento.setText(f"Campaña preparada: {resumen_txt}")
        self.lbl_dest_info.setText(
            f"✅ {n_validos:,} con email válido  |  ⚠️ {n_sin:,} sin email  |  {total:,} total filtrado"
        )
        self.lbl_total_dest.setText(f"{total:,} destinatarios")
        self.progress.setMaximum(max(n_validos, 1))
        self.progress.setValue(0)
        self.btn_enviar.setEnabled(n_validos > 0)
        self._actualizar_contadores()

    def _iniciar_envio(self):
        cfg = self._get_config()

        if not config_completa(cfg):
            QMessageBox.warning(self, "Sin configuración SMTP", "Configura el servidor de correo primero.")
            return

        if self._df_dest is None or self._df_dest.empty:
            QMessageBox.warning(self, "Sin destinatarios", "Pulsa primero 'Cargar destinatarios filtrados'.")
            return

        n_pendientes = sum(
            1
            for r in range(self.tbl_log.rowCount())
            if self.tbl_log.item(r, _LOG_ESTADO)
            and self.tbl_log.item(r, _LOG_ESTADO).text() == _ESTADO_PENDIENTE
        )

        if n_pendientes == 0:
            QMessageBox.information(self, "Sin pendientes", "No hay destinatarios pendientes de envío.")
            return

        idx = self.cmb_plantilla.currentIndex()
        pls = cargar_plantillas(self._session)
        if idx < 0 or idx >= len(pls):
            QMessageBox.warning(self, "Sin plantilla", "Selecciona una plantilla.")
            return

        plantilla = pls[idx]
        self._plantilla_envio_nombre = str(plantilla.get("nombre", "")).strip()

        if (
            QMessageBox.question(
                self,
                "Confirmar envío",
                f"¿Enviar a {n_pendientes:,} destinatarios con la plantilla '{plantilla.get('nombre', 'Sin nombre')}'?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        emails_pendientes = {
            self.tbl_log.item(r, _LOG_EMAIL).text()
            for r in range(self.tbl_log.rowCount())
            if self.tbl_log.item(r, _LOG_ESTADO)
            and self.tbl_log.item(r, _LOG_ESTADO).text() == _ESTADO_PENDIENTE
        }

        mask = self._df_dest[self._col_email].astype(str).isin(emails_pendientes)
        df_enviar = self._df_dest[mask].copy()
        self._envio_payload_by_email.clear()
        self._gestiones_pendientes_registro.clear()
        for _, fila in df_enviar.iterrows():
            email_key = self._email_key(str(fila.get(self._col_email, "")).strip())
            if not email_key:
                continue
            self._envio_payload_by_email.setdefault(email_key, []).append(dict(fila))

        params = EnvioParams(
            host=cfg["host"],
            port=cfg["port"],
            tls=cfg["tls"],
            usuario=cfg["usuario"],
            password=cfg["password"],
            nombre_remitente=cfg.get("nombre_remitente", "Controlia Cobranzas"),
            plantilla=plantilla,
            df_destinatarios=df_enviar,
            col_email=self._col_email,
            pausa_segundos=float(self.spn_pausa.value()),
        )

        self._worker = EnvioWorker(params)
        self._worker.progreso.connect(self._on_progreso)
        self._worker.resultado.connect(self._on_resultado)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.error_fatal.connect(self._on_error_fatal)
        self._worker.start()

        self.btn_enviar.setEnabled(False)
        self.btn_cancelar.setEnabled(True)

    def _cancelar(self):
        if self._worker:
            self._worker.cancelar()
        self.btn_cancelar.setEnabled(False)
        self.lbl_prog.setText("Cancelando…")

    def _on_progreso(self, enviados: int, total: int, email: str, nombre: str):
        self.progress.setValue(enviados)
        if email:
            self.lbl_prog.setText(f"Enviando → {nombre} ({email}) [{enviados} / {total}]")
            row = self._find_row_for_email(email, consume=False)
            if row is not None:
                item = self.tbl_log.item(row, _LOG_ESTADO)
                if item and item.text() == _ESTADO_PENDIENTE:
                    item.setText("📨 Enviando…")

    def _on_resultado(self, res: ResultadoEnvio):
        payload = self._pop_payload_for_email(res.email)
        row = self._find_row_for_email(res.email, consume=True)
        if row is None:
            row = self.tbl_log.rowCount()
            self.tbl_log.insertRow(row)

        if res.ok:
            estado, color = _ESTADO_ENVIADO, _COLOR_ENVIADO
        elif "Omitido" in res.mensaje:
            estado, color = _ESTADO_OMITIDO, _COLOR_OMITIDO
        else:
            estado, color = _ESTADO_NO_ENVIADO, _COLOR_FALLIDO

        self._set_fila_log(row, res.email, res.nombre, estado, res.mensaje, color)
        if res.ok and isinstance(payload, dict):
            self._gestiones_pendientes_registro.append(payload)
        self._actualizar_contadores()


    def _registrar_gestiones_envio_masivo(self) -> tuple[int, list[str]]:
        if not self._gestiones_pendientes_registro:
            return 0, []

        ok_count = 0
        errores: list[str] = []
        fecha_hoy = datetime.datetime.now().strftime("%d/%m/%Y")
        empresa_filtro = self.cmb_empresa_filtro.currentText().strip()
        empresa_fallback = "" if empresa_filtro.lower().startswith("todas") else empresa_filtro
        observacion = f"Envio masivo | Plantilla: {self._plantilla_envio_nombre or 'Plantilla'}"

        for fila in self._gestiones_pendientes_registro:
            rut = str(fila.get("Rut_Afiliado", "")).strip()
            if not rut:
                continue
            nombre = str(fila.get("Nombre_Afiliado", "")).strip() or rut
            empresa = str(fila.get("_empresa", "")).strip() or empresa_fallback
            try:
                if self._usa_backend_envios():
                    _, err = backend_create_gestion(
                        self._session,
                        rut=rut,
                        empresa=empresa,
                        nombre_afiliado=nombre,
                        tipo_gestion="Email",
                        estado="Enviado",
                        fecha_gestion=fecha_hoy,
                        observacion=observacion,
                        origen="backend_email_masivo",
                    )
                    if err:
                        raise ValueError(err)
                else:
                    insertar_gestion_manual(
                        rut=rut,
                        nombre=nombre,
                        tipo_gestion="Email",
                        estado="Enviado",
                        fecha=fecha_hoy,
                        observacion=observacion,
                    )
                ok_count += 1
            except Exception as exc:
                errores.append(f"{rut}: {exc}")

        self._gestiones_pendientes_registro.clear()
        return ok_count, errores

    def _on_terminado(self, ok: int, fallidos: int, omitidos: int):
        self.btn_enviar.setEnabled(True)
        self.btn_cancelar.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        self.lbl_prog.setText(
            f"Proceso finalizado - enviados={ok}, no_enviados={fallidos}, sin_email={omitidos}"
        )
        self._actualizar_contadores()
        gest_ok, gest_err = self._registrar_gestiones_envio_masivo()

        if gest_err:
            detalle = "\n".join(gest_err[:5])
            QMessageBox.warning(
                self,
                "Envio completado con advertencias",
                f"Enviados: {ok}\nNo enviados: {fallidos}\nSin email: {omitidos}\n"
                f"Gestiones registradas: {gest_ok}\n\nErrores de registro:\n{detalle}",
            )
        else:
            QMessageBox.information(
                self,
                "Envio completado",
                f"Enviados: {ok}\nNo enviados: {fallidos}\nSin email: {omitidos}\n"
                f"Gestiones registradas: {gest_ok}",
            )

    def _on_error_fatal(self, err: str):
        self.btn_enviar.setEnabled(True)
        self.btn_cancelar.setEnabled(False)
        self.lbl_prog.setText("Error de conexión ❌")
        QMessageBox.critical(self, "Error SMTP", err)
