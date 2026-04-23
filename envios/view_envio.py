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
    cargar_detalle_empresa,
    cargar_contactos_empresa,
    cargar_contactos_todas,
    cargar_para_envio,
)
from deudores.gestiones_db import (
    ESTADO_DEUDOR_DEFAULT,
    insertar_gestion_manual,
    obtener_estados_deudor_por_rut,
)
from auth.auth_service import backend_create_gestion, backend_get_deudor_detalle, backend_list_destinatarios
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
        self._modo_envio_ejecucion: str = "individual"

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
        row_modo = QHBoxLayout()
        row_modo.addWidget(QLabel("Modo de envío:"))
        self.cmb_modo_envio = QComboBox()
        self.cmb_modo_envio.addItem("Individual (actual)")
        self.cmb_modo_envio.addItem("Consolidado (todas las licencias)")
        row_modo.addWidget(self.cmb_modo_envio, 1)
        card_ops.body.addLayout(row_modo)
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

    def _find_rows_for_email(self, email: str) -> list[int]:
        key = self._email_key(email)
        if not key:
            return []
        rows: list[int] = []
        for r in range(self.tbl_log.rowCount()):
            email_item = self.tbl_log.item(r, _LOG_EMAIL)
            if not email_item:
                continue
            if self._email_key(email_item.text()) == key:
                rows.append(r)
        return rows

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

    def _modo_envio_consolidado(self) -> bool:
        return "consolidado" in self.cmb_modo_envio.currentText().strip().lower()

    def _txt(self, v) -> str:
        return str(v or "").strip()

    def _valor_limpio(self, v, default: str = "-") -> str:
        txt = self._txt(v)
        if txt.lower() in {"", "nan", "none", "n", "-"}:
            return default
        return txt

    def _fmt_monto_detalle(self, v) -> str:
        nro = self._parse_float(v)
        if nro is None:
            return "-"
        return f"{int(round(nro)):,}".replace(",", ".")

    def _linea_detalle_licencia(self, item: dict) -> str:
        no_lic = self._valor_limpio(item.get("No_Licencia", ""))
        nom = self._valor_limpio(item.get("Nombre Afil", ""))
        rut = self._valor_limpio(item.get("RUT Afil", ""))
        fec = self._valor_limpio(item.get("Fecha Pago", ""))
        cop = self._fmt_monto_detalle(item.get("Copago", ""))
        sal = self._fmt_monto_detalle(item.get("Saldo_Actual", ""))
        return (
            f"- Licencia: {no_lic} | Nombre Afil: {nom} | "
            f"RUT Afil: {rut} | Fecha Pago: {fec} | Copago: ${cop} | Saldo: ${sal}"
        )

    def _resolver_detalles_deudor(self, rut: str, empresa: str) -> list[dict]:
        empresa_txt = self._txt(empresa)
        rut_norm = self._normalizar_rut(rut)
        if not empresa_txt or not rut_norm:
            return []

        detalles: list[dict] = []
        if self._usa_backend_envios():
            payload, err = backend_get_deudor_detalle(self._session, rut=rut, empresa=empresa_txt)
            if not err and isinstance(payload, dict):
                for item in payload.get("detalle") or []:
                    it = item or {}
                    detalles.append(
                        {
                            "No_Licencia": self._txt(it.get("nro_expediente", "")),
                            "Nombre Afil": self._txt(it.get("nombre_afil", it.get("nombre_afiliado", ""))),
                            "RUT Afil": self._txt(it.get("rut_afil", it.get("rut_afiliado", ""))),
                            "Fecha Pago": self._txt(it.get("fecha_pago", "")),
                            "Copago": it.get("copago", ""),
                            "Saldo_Actual": it.get("saldo_actual", ""),
                        }
                    )

        if detalles:
            return detalles

        try:
            local = cargar_detalle_empresa(empresa_txt).copy().fillna("")
        except Exception:
            local = pd.DataFrame()

        if local.empty or "Rut_Afiliado" not in local.columns:
            return []

        mask = (
            local["Rut_Afiliado"].astype(str).str.replace(".", "", regex=False).str.replace("-", "", regex=False).str.strip()
            == rut_norm
        )
        subset = local.loc[mask].copy()
        if subset.empty:
            return []

        for _, row in subset.iterrows():
            detalles.append(
                {
                    "No_Licencia": self._txt(row.get("Nro_Expediente", row.get("No_Licencia", ""))),
                    "Nombre Afil": self._txt(row.get("Nombre Afil", row.get("nombre_afil", ""))),
                    "RUT Afil": self._txt(row.get("RUT Afil", row.get("rut_afil", ""))),
                    "Fecha Pago": self._txt(row.get("Fecha Pago", row.get("fecha_pago", ""))),
                    "Copago": row.get("Copago", ""),
                    "Saldo_Actual": row.get("Saldo_Actual", ""),
                }
            )
        return detalles

    def _construir_df_envio_consolidado(self, df_enviar: pd.DataFrame) -> pd.DataFrame:
        if df_enviar is None or df_enviar.empty:
            return pd.DataFrame()

        cache: dict[tuple[str, str], list[dict]] = {}
        salida: list[dict] = []

        for email, grupo in df_enviar.groupby(df_enviar[self._col_email].astype(str).str.strip(), sort=False):
            email_txt = self._txt(email)
            if not email_txt:
                continue

            base = dict(grupo.iloc[0])
            detalle_total: list[dict] = []
            usados: set[tuple[str, str]] = set()

            for _, fila in grupo.iterrows():
                empresa = self._txt(fila.get("_empresa", ""))
                rut = self._txt(fila.get("Rut_Afiliado", ""))
                key = (empresa.lower(), self._normalizar_rut(rut))
                if not key[0] or not key[1] or key in usados:
                    continue
                usados.add(key)
                if key not in cache:
                    cache[key] = self._resolver_detalles_deudor(rut=rut, empresa=empresa)
                detalle_total.extend(cache[key])

            if not detalle_total:
                for _, fila in grupo.iterrows():
                    detalle_total.append(
                        {
                            "No_Licencia": self._txt(fila.get("No_Licencia", fila.get("Nro_Expediente", ""))),
                            "Nombre Afil": self._txt(fila.get("Nombre Afil", fila.get("nombre_afil", ""))),
                            "RUT Afil": self._txt(fila.get("RUT Afil", fila.get("rut_afil", ""))),
                            "Fecha Pago": self._txt(fila.get("Fecha Pago", fila.get("fecha_pago", ""))),
                            "Copago": fila.get("Copago", ""),
                            "Saldo_Actual": fila.get("Saldo_Actual", ""),
                        }
                    )

            unicos: list[dict] = []
            vistos: set[tuple[str, str, str, str]] = set()
            for item in detalle_total:
                sig = (
                    self._txt(item.get("No_Licencia", "")),
                    self._txt(item.get("RUT Afil", "")),
                    self._txt(item.get("Nombre Afil", "")),
                    self._txt(item.get("Fecha Pago", "")),
                )
                if sig in vistos:
                    continue
                vistos.add(sig)
                unicos.append(item)

            lineas = [self._linea_detalle_licencia(item) for item in unicos] or ["- Sin detalle de licencias"]
            base["detalle_licencias"] = "\n".join(lineas)
            if unicos:
                primero = unicos[0]
                base["No_Licencia"] = self._txt(primero.get("No_Licencia", base.get("No_Licencia", "")))
                base["Nro_Expediente"] = self._txt(primero.get("No_Licencia", base.get("Nro_Expediente", "")))
                base["Nombre Afil"] = self._txt(primero.get("Nombre Afil", base.get("Nombre Afil", "")))
                base["RUT Afil"] = self._txt(primero.get("RUT Afil", base.get("RUT Afil", "")))
                base["Fecha Pago"] = self._txt(primero.get("Fecha Pago", base.get("Fecha Pago", "")))

            salida.append(base)

        if not salida:
            return pd.DataFrame()
        return pd.DataFrame(salida).fillna("")

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
                            "Nro_Expediente": str(r.get("nro_expediente", "")).strip(),
                            "No_Licencia": str(r.get("nro_expediente", "")).strip(),
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
        if self._usa_backend_envios():
            asunto_tpl = str(plantilla.get("asunto", "") or "")
            cuerpo_tpl = str(plantilla.get("cuerpo", "") or "")
            tokens = (
                "{No_Licencia}",
                "{nombre_afil}",
                "{rut_afil}",
                "{fecha_pago}",
                "{Nombre_Afil}",
                "{RUT_Afil}",
                "{Fecha_Pago}",
                "{detalle_licencias}",
                "{Detalle_Licencias}",
            )
            if any(t in asunto_tpl or t in cuerpo_tpl for t in tokens):
                df_enviar = self._enriquecer_placeholders_cart56_para_envio(df_enviar)

        modo_consolidado = self._modo_envio_consolidado()
        self._modo_envio_ejecucion = "consolidado" if modo_consolidado else "individual"
        if modo_consolidado:
            df_enviar = self._construir_df_envio_consolidado(df_enviar)

        if df_enviar.empty:
            QMessageBox.warning(self, "Sin destinatarios", "No hay destinatarios validos para el modo seleccionado.")
            return

        if modo_consolidado:
            self.progress.setMaximum(max(len(df_enviar), 1))
            self.progress.setValue(0)

        self._envio_payload_by_email.clear()
        self._gestiones_pendientes_registro.clear()
        for _, fila in df_enviar.iterrows():
            email_key = self._email_key(str(fila.get(self._col_email, "")).strip())
            if not email_key:
                continue
            if modo_consolidado and email_key in self._envio_payload_by_email:
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

    def _enriquecer_placeholders_cart56_para_envio(self, df_enviar: pd.DataFrame) -> pd.DataFrame:
        if df_enviar is None or df_enviar.empty:
            return df_enviar

        df_out = df_enviar.copy()
        if "No_Licencia" not in df_out.columns:
            df_out["No_Licencia"] = ""
        if "Nro_Expediente" not in df_out.columns:
            df_out["Nro_Expediente"] = ""
        if "Nombre Afil" not in df_out.columns:
            df_out["Nombre Afil"] = ""
        if "RUT Afil" not in df_out.columns:
            df_out["RUT Afil"] = ""
        if "Fecha Pago" not in df_out.columns:
            df_out["Fecha Pago"] = ""

        cache: dict[tuple[str, str], dict] = {}

        def _txt(v) -> str:
            return str(v or "").strip()

        def _invalido(v: str) -> bool:
            t = _txt(v).lower()
            return t in {"", "nan", "none", "n", "—", "-"}

        def _parece_contador(v: str) -> bool:
            t = _txt(v)
            return bool(t.isdigit() and int(t) <= 20)

        detalle_local = pd.DataFrame()
        try:
            detalle_local = cargar_detalle_empresa("Cart-56").copy().fillna("")
        except Exception:
            detalle_local = pd.DataFrame()

        def _resolver_desde_local(rut_norm: str, exp_ref: str) -> dict:
            if detalle_local.empty or "Rut_Afiliado" not in detalle_local.columns:
                return {}

            d = detalle_local.copy()
            rut_mask = (
                d["Rut_Afiliado"].astype(str).str.replace(".", "", regex=False).str.replace("-", "", regex=False).str.strip()
                == rut_norm
            )
            d = d.loc[rut_mask].copy()
            if d.empty:
                return {}

            if exp_ref and "Nro_Expediente" in d.columns:
                dd = d.loc[d["Nro_Expediente"].astype(str).str.strip() == exp_ref].copy()
                if not dd.empty:
                    d = dd

            r0 = d.iloc[0]
            return {
                "No_Licencia": _txt(r0.get("Nro_Expediente", "")),
                "Nombre Afil": _txt(r0.get("Nombre Afil", "")),
                "RUT Afil": _txt(r0.get("RUT Afil", "")),
                "Fecha Pago": _txt(r0.get("Fecha Pago", "")),
            }

        for idx, row in df_out.iterrows():
            empresa = _txt(row.get("_empresa", ""))
            rut = _txt(row.get("Rut_Afiliado", ""))
            if not empresa or not rut:
                continue
            if empresa.lower() != "cart-56":
                continue

            actual = _txt(row.get("No_Licencia", "")) or _txt(row.get("Nro_Expediente", ""))
            faltan_campos = any(
                _invalido(_txt(row.get(col, "")))
                for col in ("Nombre Afil", "RUT Afil", "Fecha Pago")
            )
            if not (_invalido(actual) or _parece_contador(actual) or faltan_campos):
                continue

            key = (empresa.lower(), self._normalizar_rut(rut))
            if key in cache:
                resolved_payload = cache[key]
            else:
                payload, err = backend_get_deudor_detalle(self._session, rut=rut, empresa=empresa)
                resolved_payload: dict = {}
                if not err and isinstance(payload, dict):
                    detalle = payload.get("detalle") or []
                    chosen = None
                    if actual:
                        for item in detalle:
                            val = _txt((item or {}).get("nro_expediente", ""))
                            if val == actual:
                                chosen = item or {}
                                break
                    if chosen is None:
                        for item in detalle:
                            val = _txt((item or {}).get("nro_expediente", ""))
                            if not _invalido(val) and not _parece_contador(val):
                                chosen = item or {}
                                break
                    chosen = chosen or (detalle[0] if detalle else {})

                    resolved_payload = {
                        "No_Licencia": _txt(chosen.get("nro_expediente", "")),
                        "Nombre Afil": _txt(chosen.get("nombre_afil", "")),
                        "RUT Afil": _txt(chosen.get("rut_afil", "")),
                        "Fecha Pago": _txt(chosen.get("fecha_pago", "")),
                    }
                    if _invalido(resolved_payload.get("No_Licencia", "")):
                        resumen = payload.get("resumen") or {}
                        val = _txt((resumen or {}).get("nro_expediente", ""))
                        if not _invalido(val):
                            resolved_payload["No_Licencia"] = val

                if not resolved_payload:
                    resolved_payload = _resolver_desde_local(self._normalizar_rut(rut), actual)
                else:
                    local_payload = _resolver_desde_local(
                        self._normalizar_rut(rut),
                        resolved_payload.get("No_Licencia", "") or actual,
                    )
                    for k, v in local_payload.items():
                        if _invalido(_txt(resolved_payload.get(k, ""))) and not _invalido(_txt(v)):
                            resolved_payload[k] = v
                cache[key] = resolved_payload

            resolved = _txt(resolved_payload.get("No_Licencia", ""))
            if resolved:
                df_out.at[idx, "No_Licencia"] = resolved
                df_out.at[idx, "Nro_Expediente"] = resolved
            if _invalido(_txt(row.get("Nombre Afil", ""))):
                val = _txt(resolved_payload.get("Nombre Afil", ""))
                if val:
                    df_out.at[idx, "Nombre Afil"] = val
            if _invalido(_txt(row.get("RUT Afil", ""))):
                val = _txt(resolved_payload.get("RUT Afil", ""))
                if val:
                    df_out.at[idx, "RUT Afil"] = val
            if _invalido(_txt(row.get("Fecha Pago", ""))):
                val = _txt(resolved_payload.get("Fecha Pago", ""))
                if val:
                    df_out.at[idx, "Fecha Pago"] = val

        return df_out

    def _cancelar(self):
        if self._worker:
            self._worker.cancelar()
        self.btn_cancelar.setEnabled(False)
        self.lbl_prog.setText("Cancelando…")

    def _on_progreso(self, enviados: int, total: int, email: str, nombre: str):
        self.progress.setValue(enviados)
        if email:
            self.lbl_prog.setText(f"Enviando → {nombre} ({email}) [{enviados} / {total}]")
            if self._modo_envio_ejecucion == "consolidado":
                for row in self._find_rows_for_email(email):
                    item = self.tbl_log.item(row, _LOG_ESTADO)
                    if item and item.text() == _ESTADO_PENDIENTE:
                        item.setText("📨 Enviando…")
                return
            row = self._find_row_for_email(email, consume=False)
            if row is not None:
                item = self.tbl_log.item(row, _LOG_ESTADO)
                if item and item.text() == _ESTADO_PENDIENTE:
                    item.setText("📨 Enviando…")

    def _on_resultado(self, res: ResultadoEnvio):
        payload = self._pop_payload_for_email(res.email)

        if res.ok:
            estado, color = _ESTADO_ENVIADO, _COLOR_ENVIADO
        elif "Omitido" in res.mensaje:
            estado, color = _ESTADO_OMITIDO, _COLOR_OMITIDO
        else:
            estado, color = _ESTADO_NO_ENVIADO, _COLOR_FALLIDO

        if self._modo_envio_ejecucion == "consolidado":
            rows = [
                r
                for r in self._find_rows_for_email(res.email)
                if (
                    self.tbl_log.item(r, _LOG_ESTADO)
                    and self.tbl_log.item(r, _LOG_ESTADO).text() in (_ESTADO_PENDIENTE, "📨 Enviando…")
                )
            ]
            if not rows:
                rows = [self._find_row_for_email(res.email, consume=True)]
            for row in rows:
                if row is None:
                    continue
                self._set_fila_log(row, res.email, res.nombre, estado, res.mensaje, color)
        else:
            row = self._find_row_for_email(res.email, consume=True)
            if row is None:
                row = self.tbl_log.rowCount()
                self.tbl_log.insertRow(row)
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
