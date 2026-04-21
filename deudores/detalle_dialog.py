# ================================================================
#  deudores/detalle_dialog.py
# ================================================================

import datetime
import os
import subprocess

import pandas as pd

from PyQt6.QtCore import Qt, pyqtSignal, QDate, QUrl, QTimer
from PyQt6.QtGui import QFont, QColor, QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTableView, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSizePolicy, QPushButton, QGridLayout,
    QSplitter, QWidget, QComboBox, QLineEdit, QDateEdit,
    QTextEdit, QMessageBox, QFormLayout, QPlainTextEdit, QInputDialog, QScrollArea
)

from .schema_detalle import COLUMNAS_DETALLE_DEUDA, extraer_detalle_deudor
from .gestiones_db import (
    obtener_gestiones_rut,
    insertar_gestion_manual,
    insertar_gestion_pago,
    eliminar_gestion,
    obtener_gestion_por_id,
    parsear_observacion_pago,
    TIPO_COLORES,
    TIPOS_GESTION,
    ESTADOS_GESTION,
)
from .database import (
    actualizar_cliente_por_rut,
    cargar_detalle_empresa,
    cargar_empresa,
    registrar_pago_por_rut,
    revertir_pago_por_rut,
)

from envios.config import (
    cargar_config,
    cargar_sesion_smtp,
    guardar_sesion_smtp,
    sesion_smtp_activa,
)
from envios.plantillas import cargar_plantillas, renderizar, variables_desde_fila
from envios.worker import EnvioParams, EnvioWorker, ResultadoEnvio
from envios.history_db import registrar_historial_envio
from auth.auth_service import (
    backend_get_deudor_detalle,
    backend_list_gestiones,
    backend_create_gestion,
    backend_delete_gestion,
    backend_register_pago,
    backend_update_deudor_cliente,
    backend_list_cartera_asignaciones,
)
from admin_carteras.service import (
    obtener_empresas_asignadas_para_session,
    obtener_asignacion_por_empresa_local,
)


def _formatear_moneda_chilena(valor) -> str:
    try:
        if valor is None:
            return ""

        if isinstance(valor, (int, float)):
            n = float(valor)
        else:
            texto = str(valor).strip()
            if not texto or texto in ("", "nan", "None"):
                return ""

            limpio = texto.replace("$", "").replace(" ", "")

            if "," in limpio and "." in limpio:
                limpio = limpio.replace(".", "").replace(",", ".")
            elif "," in limpio:
                limpio = limpio.replace(".", "").replace(",", ".")
            elif "." in limpio:
                partes = limpio.split(".")
                if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
                    limpio = "".join(partes)

            n = float(limpio)

        return f"$ {int(round(n)):,}".replace(",", ".")
    except (ValueError, TypeError):
        texto = str(valor).strip()
        return texto if texto else ""


def _parse_monto(valor) -> float:
    try:
        if valor is None:
            return 0.0

        if isinstance(valor, (int, float)):
            return float(valor)

        limpio = str(valor).strip().replace("$", "").replace(" ", "")
        if not limpio or limpio in ("", "nan", "None"):
            return 0.0

        if "," in limpio and "." in limpio:
            limpio = limpio.replace(".", "").replace(",", ".")
        elif "," in limpio:
            limpio = limpio.replace(".", "").replace(",", ".")
        elif "." in limpio:
            partes = limpio.split(".")
            if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
                limpio = "".join(partes)

        return float(limpio)
    except Exception:
        return 0.0


def _fix_mojibake_text(value: object) -> str:
    txt = str(value or "")
    if not txt:
        return ""
    # Intenta reparar texto mal recodificado (mojibake) en 1-2 pasadas.
    for _ in range(2):
        try:
            fixed = txt.encode("latin1").decode("utf-8")
        except Exception:
            break
        if fixed == txt:
            break
        txt = fixed
    # Normalizaciones frecuentes de fallback.
    txt = txt.replace("Tel?fono", "Teléfono")
    txt = txt.replace("gestin", "gestión")
    txt = txt.replace("â€”", "—").replace("â€“", "–")
    return txt


def _limpiar_telefono_para_whatsapp(numero: str) -> str:
    raw = str(numero or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())

    if not digits:
        return ""

    if digits.startswith("56"):
        return digits

    if len(digits) == 9:
        return f"56{digits}"

    if len(digits) == 10 and digits.startswith("0"):
        return f"56{digits[1:]}"

    return digits


def _formatear_rut_completo(rut: str, dv: str = "", rut_completo: str = "") -> str:
    rut_txt = str(rut or "").strip()
    dv_txt = str(dv or "").strip().upper()
    rut_full_txt = str(rut_completo or "").strip()

    if rut_full_txt:
        bruto = rut_full_txt.replace(".", "")
        if "-" in bruto:
            base, dv_from_full = bruto.rsplit("-", 1)
            rut_txt = rut_txt or base.strip()
            dv_txt = dv_txt or dv_from_full.strip().upper()
        else:
            rut_txt = rut_txt or bruto.strip()

    rut_txt = rut_txt.replace(".", "").replace("-", "").strip().lstrip("0")
    if not rut_txt:
        return ""

    return f"{rut_txt}-{dv_txt}" if dv_txt else rut_txt


def _abrir_url_en_chrome(url: str) -> None:
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]

    for chrome_path in chrome_paths:
        if chrome_path and os.path.exists(chrome_path):
            subprocess.Popen([chrome_path, url], shell=False)
            return

    raise FileNotFoundError(
        "No se encontró Google Chrome instalado en las rutas habituales de Windows."
    )




def _backend_detalle_response_to_local(payload: dict) -> tuple[pd.DataFrame, dict]:
    detalle_rows = []
    for item in (payload.get("detalle") or []):
        detalle_rows.append({
            "_empresa": str(item.get("empresa", "")).strip(),
            "Rut_Afiliado": str(item.get("rut_afiliado", "")).strip(),
            "Dv": str(item.get("dv", "")).strip(),
            "_RUT_COMPLETO": str(item.get("rut_completo", "")).strip(),
            "Nombre_Afiliado": str(item.get("nombre_afiliado", "")).strip(),
            "mail_afiliado": str(item.get("mail_afiliado", "")).strip(),
            "BN": str(item.get("bn", "")).strip(),
            "telefono_fijo_afiliado": str(item.get("telefono_fijo_afiliado", "")).strip(),
            "telefono_movil_afiliado": str(item.get("telefono_movil_afiliado", "")).strip(),
            "Nro_Expediente": str(item.get("nro_expediente", "")).strip(),
            "Fecha_Emision": str(item.get("fecha_emision", "")).strip(),
            "Copago": item.get("copago", 0),
            "Total_Pagos": item.get("total_pagos", 0),
            "Saldo_Actual": item.get("saldo_actual", 0),
            "Cart56_Fecha_Recep": str(item.get("cart56_fecha_recep", "")).strip(),
            "Cart56_Fecha_Recep_ISA": str(item.get("cart56_fecha_recep_isa", "")).strip(),
            "Cart56_Dias_Pagar": str(item.get("cart56_dias_pagar", "")).strip(),
            "Cart56_Mto_Pagar": item.get("cart56_mto_pagar", 0),
            "Mail Emp": str(item.get("mail_emp", "")).strip(),
            "Telefono Empleador": str(item.get("telefono_empleador", "")).strip(),
            "Estado_deudor": str(item.get("estado_deudor", "")).strip() or "Sin Gestión",
        })

    resumen_raw = payload.get("resumen") or {}
    fila_resumen = {
        "_empresa": str((payload.get("empresa") or resumen_raw.get("empresa") or "")).strip(),
        "Rut_Afiliado": str(resumen_raw.get("rut_afiliado", payload.get("rut", ""))).strip(),
        "Dv": str(resumen_raw.get("dv", "")).strip(),
        "_RUT_COMPLETO": str(resumen_raw.get("rut_completo", "")).strip(),
        "Nombre_Afiliado": str(resumen_raw.get("nombre_afiliado", "")).strip(),
        "Estado_deudor": str(resumen_raw.get("estado_deudor", "")).strip() or "Sin Gestión",
        "BN": str(resumen_raw.get("bn", "")).strip(),
        "Nro_Expediente": str(resumen_raw.get("nro_expediente", "")).strip(),
        "MAX_Emision_ok": str(resumen_raw.get("max_emision_ok", "")).strip(),
        "MIN_Emision_ok": str(resumen_raw.get("min_emision_ok", "")).strip(),
        "Copago": resumen_raw.get("copago", 0),
        "Total_Pagos": resumen_raw.get("total_pagos", 0),
        "Saldo_Actual": resumen_raw.get("saldo_actual", 0),
    }
    return pd.DataFrame(detalle_rows).fillna(""), fila_resumen

class _Card(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)
        lbl = QLabel(title)
        lbl.setObjectName("CardTitle")
        lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        outer.addWidget(lbl)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        outer.addWidget(sep)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body)


class _KpiCard(QFrame):
    def __init__(self, title: str, value: str, is_balance: bool = False, parent=None):
        super().__init__(parent)
        self._is_balance = is_balance
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("MutedLabel")
        lbl_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))

        self.lbl_value = QLabel("")
        self.lbl_value.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self.lbl_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        lay.addWidget(lbl_title)
        lay.addWidget(self.lbl_value)
        lay.addStretch(1)
        self.set_value(value)

    def set_value(self, value: str):
        valor_formateado = _formatear_moneda_chilena(value)
        self.lbl_value.setText(valor_formateado if valor_formateado else "")

        if self._is_balance and valor_formateado not in ("", "$ 0", "$ 0.0", "$ 0,0", ""):
            self.lbl_value.setStyleSheet("color: #dc2626;")
        else:
            self.lbl_value.setStyleSheet("color: #0f172a;")


class _DeudaModel(QStandardItemModel):
    COLS_MONTO = {
        "Copago ($)",
        "Total Pagos ($)",
        "Saldo Actual ($)",
        "Mto Pagar",
        "Pagos",
        "Saldo Actual",
    }

    COLS_SALDO_ROJO = {
        "Saldo Actual ($)",
        "Saldo Actual",
    }

    def __init__(self, filas: list, parent=None):
        super().__init__(parent)
        encabezados = [etq for etq, _ in COLUMNAS_DETALLE_DEUDA]
        self.setHorizontalHeaderLabels(encabezados)
        for fila in filas:
            items = []
            for etq in encabezados:
                val = fila.get(etq, "")

                if etq in self.COLS_MONTO:
                    val = _formatear_moneda_chilena(val)

                item = QStandardItem(str(val))
                item.setEditable(False)

                if etq in self.COLS_MONTO:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                if etq in self.COLS_SALDO_ROJO and val not in ("", "$ 0", "$ 0.0", "$ 0,0", ""):
                    item.setForeground(QColor("#dc2626"))

                items.append(item)
            self.appendRow(items)


class _AgregarGestionDialog(QDialog):
    def __init__(self, rut: str, nombre: str, session=None, empresa: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar gestión manual")
        self.setMinimumSize(440, 370)
        self.resize(460, 390)
        self.setModal(True)
        self._session = session
        self._rut = rut
        self._nombre = nombre
        self._session = session
        self._empresa = str(empresa or "").strip()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        lbl_hdr = QLabel(f"Registrar gestión para: <b>{nombre}</b>")
        lbl_hdr.setWordWrap(True)
        lay.addWidget(lbl_hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        lay.addWidget(sep)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItems(TIPOS_GESTION)
        form.addRow("Tipo de gestión:", self.cmb_tipo)

        self.cmb_estado = QComboBox()
        self.cmb_estado.addItems(ESTADOS_GESTION)
        form.addRow("Estado:", self.cmb_estado)

        self.dte_fecha = QDateEdit()
        self.dte_fecha.setCalendarPopup(True)
        self.dte_fecha.setDate(QDate.currentDate())
        self.dte_fecha.setDisplayFormat("dd/MM/yyyy")
        form.addRow("Fecha:", self.dte_fecha)

        self.txt_obs = QTextEdit()
        self.txt_obs.setPlaceholderText("Observación (opcional)")
        self.txt_obs.setMaximumHeight(80)
        form.addRow("Observación:", self.txt_obs)

        lay.addLayout(form)
        lay.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("  Guardar")
        btn_ok.setObjectName("PrimaryButton")
        btn_ok.clicked.connect(self._guardar)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        lay.addLayout(btns)

    def _guardar(self):
        try:
            if self._session and getattr(self._session, "auth_source", "") == "backend":
                _, err = backend_create_gestion(
                    self._session,
                    rut=self._rut,
                    empresa=self._empresa,
                    nombre_afiliado=self._nombre,
                    tipo_gestion=self.cmb_tipo.currentText(),
                    estado=self.cmb_estado.currentText(),
                    fecha_gestion=self.dte_fecha.date().toString("dd/MM/yyyy"),
                    observacion=self.txt_obs.toPlainText().strip(),
                    origen="manual",
                )
                if err:
                    raise ValueError(err)
            else:
                insertar_gestion_manual(
                    rut=self._rut,
                    nombre=self._nombre,
                    tipo_gestion=self.cmb_tipo.currentText(),
                    estado=self.cmb_estado.currentText(),
                    fecha=self.dte_fecha.date().toString("dd/MM/yyyy"),
                    observacion=self.txt_obs.toPlainText().strip(),
                )
            QMessageBox.information(self, "Guardado", " Gestión registrada correctamente.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar: {e}")


class _RegistrarPagoDialog(QDialog):
    def __init__(
        self,
        saldo_actual: str,
        expedientes: list[str],
        saldos_por_expediente: dict[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Registrar pago")
        self.setMinimumSize(500, 380)
        self.resize(540, 430)
        self.setModal(True)

        self._saldo_actual = _parse_monto(saldo_actual)
        self._saldos_por_expediente = {
            str(k).strip(): _parse_monto(v)
            for k, v in (saldos_por_expediente or {}).items()
            if str(k).strip()
        }

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        lbl_hdr = QLabel("Registrar un abono o un pago total de la deuda.")
        lbl_hdr.setWordWrap(True)
        lay.addWidget(lbl_hdr)

        self.lbl_saldo = QLabel(f"Saldo Actual: {_formatear_moneda_chilena(saldo_actual)}")
        self.lbl_saldo.setStyleSheet("font-weight:700; color:#dc2626;")
        lay.addWidget(self.lbl_saldo)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        lay.addWidget(sep)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self.cmb_expediente = QComboBox()
        self.cmb_expediente.addItems(expedientes or [])
        self.cmb_expediente.currentIndexChanged.connect(self._actualizar_saldo_expediente)
        form.addRow("Expediente:", self.cmb_expediente)

        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItems(["Abono a la deuda", "Pago total de la deuda"])
        form.addRow("Tipo de pago:", self.cmb_tipo)

        self.txt_monto = QLineEdit()
        self.txt_monto.setPlaceholderText("Ej: 150000")
        form.addRow("Monto:", self.txt_monto)

        self.txt_obs = QTextEdit()
        self.txt_obs.setPlaceholderText("Ej: Transferencia banco X, N° operación, comentario, etc.")
        self.txt_obs.setMaximumHeight(90)
        form.addRow("Observaciones:", self.txt_obs)

        lay.addLayout(form)
        lay.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(" Registrar pago")
        btn_ok.setObjectName("PrimaryButton")
        btn_ok.clicked.connect(self._guardar)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        lay.addLayout(btns)

        self._actualizar_saldo_expediente()

    def _saldo_expediente_actual(self) -> float:
        expediente = self.cmb_expediente.currentText().strip()
        return self._saldos_por_expediente.get(expediente, self._saldo_actual)

    def _actualizar_saldo_expediente(self):
        saldo = self._saldo_expediente_actual()
        self.lbl_saldo.setText(f"Saldo Actual: {_formatear_moneda_chilena(str(saldo))}")

    def _guardar(self):
        expediente = self.cmb_expediente.currentText().strip()
        monto = _parse_monto(self.txt_monto.text())

        if not expediente:
            QMessageBox.warning(self, "Expediente requerido", "Debes seleccionar un expediente.")
            return

        if monto <= 0:
            QMessageBox.warning(self, "Monto inválido", "Debes ingresar un monto mayor a 0.")
            return

        saldo_expediente = self._saldo_expediente_actual()

        if self.cmb_tipo.currentText() == "Pago total de la deuda" and round(monto, 2) != round(saldo_expediente, 2):
            QMessageBox.warning(self, "Monto inválido", "Monto no corresponde al Saldo Actual, verificar monto de pago")
            return

        self.accept()

    def obtener_datos(self) -> dict:
        return {
            "expediente": self.cmb_expediente.currentText().strip(),
            "tipo_pago": self.cmb_tipo.currentText(),
            "monto": _parse_monto(self.txt_monto.text()),
            "observaciones": self.txt_obs.toPlainText().strip(),
        }


class _VistaPreviaEmailDialog(QDialog):
    def __init__(self, destinatario: str, asunto: str, cuerpo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vista previa del email")
        self.resize(760, 560)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        lbl_to = QLabel(f"<b>Para:</b> {destinatario}")
        lbl_subject = QLabel(f"<b>Asunto:</b> {asunto}")
        lbl_subject.setWordWrap(True)

        root.addWidget(lbl_to)
        root.addWidget(lbl_subject)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        root.addWidget(sep)

        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(cuerpo)
        root.addWidget(txt, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.accept)
        btn_row.addWidget(btn_cerrar)
        root.addLayout(btn_row)



_COLS_VIS = ["Tipo", "Estado", "Fecha", "Observación"]


class _GestionWidget(QWidget):
    gestiones_actualizadas = pyqtSignal()
    seleccion_eliminable_cambiada = pyqtSignal(bool)

    def __init__(self, rut: str, nombre: str, session=None, empresa: str = "", parent=None):
        super().__init__(parent)
        self._session = session
        self._empresa = str(empresa or "").strip()
        self._rut = rut
        self._nombre = nombre
        self._ids = {}
        self._allow_delete_manual = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.tbl = QTableWidget(0, len(_COLS_VIS))
        self.tbl.setHorizontalHeaderLabels(_COLS_VIS)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setAlternatingRowColors(False)
        self.tbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tbl.setMinimumHeight(150)
        lay.addWidget(self.tbl, 1)

        btn_row = QHBoxLayout()
        self.lbl_total = QLabel("Sin gestiones registradas")
        self.lbl_total.setObjectName("MutedLabel")
        btn_row.addWidget(self.lbl_total)
        btn_row.addStretch(1)
        self.btn_del = QPushButton("\U0001F5D1  Eliminar manual")
        self.btn_del.setProperty("blockableAction", True)
        self.btn_del.setEnabled(False)
        self.btn_del.setToolTip("Solo se pueden eliminar gestiones manuales")
        self.btn_del.clicked.connect(self._eliminar)
        btn_row.addWidget(self.btn_del)
        lay.addLayout(btn_row)

        self.tbl.itemSelectionChanged.connect(self._on_sel)
        QTimer.singleShot(0, self._cargar)

    def _cargar(self):
        self.tbl.setRowCount(0)
        self._ids = {}

        def _estado_legible(valor: str) -> str:
            txt = str(valor or "").strip()
            txt_low = txt.lower()
            if txt_low in {"gestion asignada", "gestin asignada"}:
                return "Gesti\u00f3n asignada"
            if txt_low in {"gestion realizada", "gestin realizada"}:
                return "Gesti\u00f3n realizada"
            return txt

        if self._session and getattr(self._session, "auth_source", "") == "backend":
            rows, err = backend_list_gestiones(self._session, rut=self._rut, empresa=self._empresa)
            if err:
                self.lbl_total.setText("Error al cargar gestiones")
                return
            if not rows:
                self.lbl_total.setText("Sin gestiones registradas")
                return

            for ri, row in enumerate(rows):
                self.tbl.insertRow(ri)
                tipo = str(row.get("tipo_gestion", ""))
                color = QColor(TIPO_COLORES.get(tipo, "#f8fafc"))
                self._ids[ri] = (str(row.get("id", "")), str(row.get("origen", "")))
                for ci, val in enumerate([
                    tipo,
                    _estado_legible(row.get("estado", "")),
                    str(row.get("fecha_gestion", "")),
                    str(row.get("observacion", "")),
                ]):
                    item = QTableWidgetItem(_fix_mojibake_text(val))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setBackground(color)
                    self.tbl.setItem(ri, ci, item)
            n = len(rows)
            self.lbl_total.setText(f"{n} gestión{'es' if n != 1 else ''}")
            return

        df = obtener_gestiones_rut(self._rut)
        if df.empty:
            self.lbl_total.setText("Sin gestiones registradas")
            return
        for ri, (_, row) in enumerate(df.iterrows()):
            self.tbl.insertRow(ri)
            tipo = str(row.get("tipo_gestion", ""))
            color = QColor(TIPO_COLORES.get(tipo, "#f8fafc"))
            self._ids[ri] = (str(row.get("id", "")), str(row.get("origen", "")))
            for ci, val in enumerate([
                tipo,
                _estado_legible(row.get("Estado", "")),
                str(row.get("Fecha_gestion", "")),
                str(row.get("Observacion", "")),
            ]):
                item = QTableWidgetItem(_fix_mojibake_text(val))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(color)
                self.tbl.setItem(ri, ci, item)
        n = len(df)
        self.lbl_total.setText(f"{n} gestión{'es' if n != 1 else ''}")

    def _on_sel(self):
        if not self._allow_delete_manual:
            self.btn_del.setEnabled(False)
            return
        rows = self.tbl.selectedItems()
        if not rows:
            self.btn_del.setEnabled(False)
            return
        _, origen = self._ids.get(self.tbl.row(rows[0]), ("", ""))
        origen_txt = str(origen or "").strip().lower()
        self.btn_del.setEnabled(not origen_txt.startswith("excel"))

    def _eliminar(self):
        if not self._allow_delete_manual:
            QMessageBox.warning(
                self,
                "Acci\u00f3n bloqueada",
                "Esta cartera no est\u00e1 asignada a tu usuario."
            )
            return
        rows = self.tbl.selectedItems()
        if not rows:
            return

        ri = self.tbl.row(rows[0])
        gid, origen = self._ids.get(ri, ("", ""))
        origen_txt = str(origen or "").strip().lower()

        if origen_txt.startswith("excel"):
            QMessageBox.warning(self, "No permitido", "No se pueden eliminar gestiones cargadas desde Excel.")
            return

        if QMessageBox.question(
            self,
            "Confirmar",
            "¿Eliminar esta gestión?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return

        try:
            if self._session and getattr(self._session, "auth_source", "") == "backend":
                err = backend_delete_gestion(self._session, gestion_id=int(gid))
                if err:
                    raise ValueError(err)
                self._cargar()
                self.gestiones_actualizadas.emit()
                return

            data = obtener_gestion_por_id(int(gid))
            if data and str(data.get("tipo_gestion", "")).strip() == "Pago":
                payload = parsear_observacion_pago(data.get("Observacion", ""))
                if payload:
                    revertir_pago_por_rut(
                        empresa=str(payload.get("empresa", "")),
                        rut=str(data.get("Rut_Afiliado", "")),
                        expediente=str(payload.get("expediente", "")),
                        monto=float(payload.get("monto", 0) or 0),
                    )

            ok = eliminar_gestion(int(gid))
            if ok:
                self._cargar()
                self.gestiones_actualizadas.emit()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo eliminar la gestión.\n\nDetalle:\n{e}")

    def refrescar(self):
        self._cargar()

    def set_allow_delete_manual(self, allow: bool) -> None:
        self._allow_delete_manual = bool(allow)
        if not self._allow_delete_manual:
            self.btn_del.setEnabled(False)
            self.btn_del.setToolTip("Bloqueado: cartera no asignada a tu usuario")
            return
        self.btn_del.setToolTip("Solo se pueden eliminar gestiones manuales")
        self._on_sel()


class _EditarClienteDialog(QDialog):
    def __init__(self, info_cliente: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar datos del cliente")
        self.setModal(True)
        self.setMinimumSize(500, 320)
        self.resize(560, 360)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        lbl = QLabel("Modifica los datos del cliente y guarda los cambios.")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        lay.addWidget(sep)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        def limpio(v: str) -> str:
            v = str(v or "").strip()
            return "" if v in ("", "nan", "None", "N") else v

        self.txt_rut = QLineEdit(limpio(info_cliente.get("RUT", "")))
        self.txt_nombre = QLineEdit(limpio(info_cliente.get("Nombre", "")))
        self.txt_correo = QLineEdit(limpio(info_cliente.get("Correo", "")))
        self.txt_correo_excel = QLineEdit(limpio(info_cliente.get("Correo (Excel)", "")))
        self.txt_tel_fijo = QLineEdit(limpio(info_cliente.get("Teléfono Fijo", "")))
        self.txt_tel_movil = QLineEdit(limpio(info_cliente.get("Teléfono Móvil", "")))

        self.txt_correo.setPlaceholderText("correo@dominio.com")
        self.txt_correo_excel.setPlaceholderText("correo alternativo / Excel")
        self.txt_tel_fijo.setPlaceholderText("Teléfono fijo")
        self.txt_tel_movil.setPlaceholderText("Teléfono móvil")

        form.addRow("RUT:", self.txt_rut)
        form.addRow("Nombre:", self.txt_nombre)
        form.addRow("Correo:", self.txt_correo)
        form.addRow("Correo (Excel):", self.txt_correo_excel)
        form.addRow("Teléfono fijo:", self.txt_tel_fijo)
        form.addRow("Teléfono móvil:", self.txt_tel_movil)

        lay.addLayout(form)
        lay.addStretch(1)

        row_btn = QHBoxLayout()
        row_btn.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton(" Guardar cambios")
        btn_save.setObjectName("PrimaryButton")
        btn_save.clicked.connect(self._guardar)

        row_btn.addWidget(btn_cancel)
        row_btn.addWidget(btn_save)
        lay.addLayout(row_btn)

    def _guardar(self):
        rut = self.txt_rut.text().strip()
        nombre = self.txt_nombre.text().strip()

        if not rut:
            QMessageBox.warning(self, "Dato obligatorio", "El RUT no puede quedar vacío.")
            return

        if not nombre:
            QMessageBox.warning(self, "Dato obligatorio", "El nombre no puede quedar vacío.")
            return

        self.accept()

    def obtener_datos(self) -> dict:
        return {
            "RUT": self.txt_rut.text().strip(),
            "Nombre": self.txt_nombre.text().strip(),
            "Correo": self.txt_correo.text().strip(),
            "Correo (Excel)": self.txt_correo_excel.text().strip(),
            "Teléfono Fijo": self.txt_tel_fijo.text().strip(),
            "Teléfono Móvil": self.txt_tel_movil.text().strip(),
        }


class _AsignarTareaDialog(QDialog):
    def __init__(self, empresa: str, ejecutivas: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asignar tarea")
        self.setModal(True)
        self.setMinimumSize(520, 300)
        self.resize(560, 340)
        self._ejecutivas = list(ejecutivas or [])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        lbl = QLabel(
            f"Empresa: <b>{empresa}</b><br>"
            "Tarea a asignar: <b>Contactar cliente</b>"
        )
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e8f0;")
        lay.addWidget(sep)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self.cmb_ejecutiva = QComboBox()
        for ej in self._ejecutivas:
            display = str(ej.get("display", "")).strip()
            if display:
                self.cmb_ejecutiva.addItem(display, dict(ej))
        if self.cmb_ejecutiva.count() == 0:
            self.cmb_ejecutiva.addItem("Sin ejecutiva asignada", None)
            self.cmb_ejecutiva.setEnabled(False)
        form.addRow("Ejecutiva destino:", self.cmb_ejecutiva)

        self.txt_obs = QTextEdit()
        self.txt_obs.setPlaceholderText("Observación para la ejecutiva (opcional)")
        self.txt_obs.setMinimumHeight(110)
        form.addRow("Observación:", self.txt_obs)
        lay.addLayout(form)
        lay.addStretch(1)

        row_btn = QHBoxLayout()
        row_btn.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("\U0001F4DD Asignar tarea")
        self.btn_ok.setObjectName("PrimaryButton")
        self.btn_ok.setEnabled(self.cmb_ejecutiva.isEnabled())
        self.btn_ok.clicked.connect(self.accept)
        row_btn.addWidget(btn_cancel)
        row_btn.addWidget(self.btn_ok)
        lay.addLayout(row_btn)

    def datos(self) -> dict:
        ej = self.cmb_ejecutiva.currentData()
        return {
            "ejecutiva": ej if isinstance(ej, dict) else {},
            "observacion": self.txt_obs.toPlainText().strip(),
            "tarea": "Contactar cliente",
        }


class DetalleDeudorDialog(QDialog):
    gestiones_actualizadas = pyqtSignal()

    def __init__(self, df_detalle, rut: str, fila_resumen: dict | None = None, parent=None, session=None):
        super().__init__(parent)
        self.setWindowTitle("Detalle del deudor")
        self.setMinimumSize(800, 520)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.MSWindowsFixedSizeDialogHint)

        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        w = min(int(screen.width() * 0.88), 1180)
        h = min(int(screen.height() * 0.85), 760)
        self.resize(w, h)
        self.setModal(True)

        self._session = session
        self._rut = rut
        self._fila_resumen = fila_resumen or {}
        self._df_detalle_completo = df_detalle
        self._email_worker: EnvioWorker | None = None
        self._ultimo_asunto = ""
        self._ultimo_email = ""
        self._ultimo_nombre = ""
        self._ultima_plantilla = ""
        self._labels_cliente: dict[str, QLabel] = {}
        self.lbl_nombre_header: QLabel | None = None
        self.lbl_rut_header: QLabel | None = None
        self.lbl_exp: QLabel | None = None
        self.tbl_deuda: QTableView | None = None
        self.kpi_copago: _KpiCard | None = None
        self.kpi_total_pagos: _KpiCard | None = None
        self.kpi_saldo_actual: _KpiCard | None = None
        self.btn_asignar_tarea: QPushButton | None = None
        self._can_operate_current_cartera = True

        info_cliente, filas_deuda = extraer_detalle_deudor(df_detalle, rut)
        self._info_cliente = info_cliente or {}
        self._filas_deuda = filas_deuda or []
        self._normalizar_fila_resumen_backend()
        self._alinear_detalle_con_resumen_backend()
        self._sincronizar_resumen_financiero_desde_detalle()

        fallbacks = {
            "RUT": self._resolver_rut_cliente(),
            "Nombre": self._fila_resumen.get("Nombre_Afiliado", ""),
            "Correo": self._fila_resumen.get("mail_afiliado", "") or self._fila_resumen.get("Mail Emp", ""),
            "Correo (Excel)": self._fila_resumen.get("BN", "") or self._fila_resumen.get("Mail Emp", ""),
            "Teléfono Fijo": self._fila_resumen.get("telefono_fijo_afiliado", "") or self._fila_resumen.get("Telefono Empleador", ""),
            "Teléfono Móvil": self._fila_resumen.get("telefono_movil_afiliado", "") or self._fila_resumen.get("Telefono Empleador", ""),
        }
        for k, v in fallbacks.items():
            actual = str(self._info_cliente.get(k, "")).strip()
            if actual in ("", "â€”", "nan", "None", "N"):
                limpio = str(v).strip()
                self._info_cliente[k] = limpio if limpio not in ("", "nan", "None", "N") else "â€”"

        self._normalizar_campos_info_cliente()

        rut_cliente = self._resolver_rut_cliente()
        if rut_cliente:
            self._info_cliente["RUT"] = rut_cliente
        nombre = self._info_cliente.get("Nombre", rut)
        rut_fmt = self._resolver_rut_cliente() or self._info_cliente.get("RUT", rut)

        self._plantillas = cargar_plantillas(self._session) or []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        hdr = QHBoxLayout()
        lbl_nombre = QLabel(nombre)
        self.lbl_nombre_header = lbl_nombre
        lbl_nombre.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        hdr.addWidget(lbl_nombre)
        hdr.addStretch(1)

        lbl_rut = QLabel(f"RUT: {rut_fmt}")
        self.lbl_rut_header = lbl_rut
        lbl_rut.setObjectName("HeaderHint")
        hdr.addWidget(lbl_rut)

        n_exp = len(self._filas_deuda)
        lbl_exp = QLabel(f"{n_exp} expediente{'s' if n_exp != 1 else ''}")
        self.lbl_exp = lbl_exp
        lbl_exp.setObjectName("MutedLabel")
        hdr.addWidget(lbl_exp)
        root.addLayout(hdr)

        if self._info_cliente:
            card_cli = _Card("Datos del cliente")
            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(5)
            campos = [(_fix_mojibake_text(k), _fix_mojibake_text(v)) for k, v in self._info_cliente.items()]
            mitad = (len(campos) + 1) // 2

            for i, (etq, val) in enumerate(campos):
                col_offset = 0 if i < mitad else 2
                fila_grid = i if i < mitad else i - mitad

                lbl_e = QLabel(f"{_fix_mojibake_text(etq)}:")
                lbl_e.setObjectName("MutedLabel")
                lbl_e.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

                lbl_v = QLabel(_fix_mojibake_text(val))
                self._labels_cliente[etq] = lbl_v
                lbl_v.setFont(QFont("Segoe UI", 10))
                lbl_v.setWordWrap(True)
                lbl_v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

                grid.addWidget(lbl_e, fila_grid, col_offset)
                grid.addWidget(lbl_v, fila_grid, col_offset + 1)

            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(3, 1)
            card_cli.body.addLayout(grid)

            row_btn_cliente = QHBoxLayout()
            row_btn_cliente.addStretch(1)
            self.btn_editar_cliente = QPushButton("\u270f\ufe0f Editar datos del cliente")
            self.btn_editar_cliente.setObjectName("PrimaryButton")
            self.btn_editar_cliente.clicked.connect(self._editar_cliente)
            row_btn_cliente.addWidget(self.btn_editar_cliente)
            card_cli.body.addLayout(row_btn_cliente)

            copago = self._obtener_monto_resumen("Copago", "Copago ($)")
            total_pagos = self._obtener_monto_resumen("Total_Pagos", "Total Pagos ($)")
            saldo_actual = self._obtener_monto_resumen("Saldo_Actual", "Saldo Actual ($)", "Saldo Actual")

            sep_fin = QFrame()
            sep_fin.setFrameShape(QFrame.Shape.HLine)
            sep_fin.setStyleSheet("color: #e2e8f0;")
            card_cli.body.addWidget(sep_fin)

            lbl_fin = QLabel("Resumen financiero")
            lbl_fin.setObjectName("MutedLabel")
            lbl_fin.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            card_cli.body.addWidget(lbl_fin)

            row_kpis = QHBoxLayout()
            row_kpis.setSpacing(12)
            self.kpi_copago = _KpiCard("Copago ($)", copago)
            self.kpi_total_pagos = _KpiCard("Total Pagos ($)", total_pagos)
            self.kpi_saldo_actual = _KpiCard("Saldo Actual ($)", saldo_actual, is_balance=True)
            row_kpis.addWidget(self.kpi_copago, 1)
            row_kpis.addWidget(self.kpi_total_pagos, 1)
            row_kpis.addWidget(self.kpi_saldo_actual, 1)

            card_cli.body.addLayout(row_kpis)
            root.addWidget(card_cli)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._main_splitter = splitter

        card_deuda = _Card(f"Detalle de deuda \u2014 {n_exp} expediente{'s' if n_exp != 1 else ''}")
        card_deuda.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if self._filas_deuda:
            model = _DeudaModel(self._filas_deuda)
            self.tbl_deuda = QTableView()
            self.tbl_deuda.setModel(model)
            self.tbl_deuda.setAlternatingRowColors(True)
            self.tbl_deuda.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.tbl_deuda.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.tbl_deuda.setSortingEnabled(True)
            self.tbl_deuda.verticalHeader().setVisible(False)
            self.tbl_deuda.horizontalHeader().setStretchLastSection(True)
            self.tbl_deuda.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.tbl_deuda.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            card_deuda.body.addWidget(self.tbl_deuda, 1)
        else:
            lbl_nd = QLabel("Sin expedientes en la hoja DETALLE.")
            lbl_nd.setObjectName("MutedLabel")
            lbl_nd.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_deuda.body.addWidget(lbl_nd)

        splitter.addWidget(card_deuda)

        card_gest = _Card("Detalle de gesti\u00f3n")
        card_gest.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._gestion_widget = _GestionWidget(
            rut=self._rut,
            nombre=nombre,
            session=self._session,
            empresa=str(self._fila_resumen.get("_empresa", "")).strip(),
        )
        self._gestion_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._gestion_widget.gestiones_actualizadas.connect(self._on_gestiones_actualizadas)

        row_btn_gest = QHBoxLayout()
        row_btn_gest.setSpacing(8)
        self.btn_agregar_gestion = QPushButton("\u2795 Agregar gesti\u00f3n manual")
        self.btn_agregar_gestion.setObjectName("PrimaryButton")
        self.btn_agregar_gestion.setProperty("blockableAction", True)
        self.btn_agregar_gestion.setMinimumHeight(34)
        self.btn_agregar_gestion.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_agregar_gestion.clicked.connect(self._agregar_gestion)
        row_btn_gest.addWidget(self.btn_agregar_gestion)

        self.btn_registrar_pago = QPushButton("\U0001F4B0 Registrar pago")
        self.btn_registrar_pago.setObjectName("PrimaryButton")
        self.btn_registrar_pago.setProperty("blockableAction", True)
        self.btn_registrar_pago.setMinimumHeight(34)
        self.btn_registrar_pago.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_registrar_pago.clicked.connect(self._registrar_pago)
        row_btn_gest.addWidget(self.btn_registrar_pago)

        self.btn_asignar_tarea = QPushButton("\U0001F4DD Asignar tarea")
        self.btn_asignar_tarea.setObjectName("PrimaryButton")
        self.btn_asignar_tarea.setMinimumHeight(34)
        self.btn_asignar_tarea.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_asignar_tarea.clicked.connect(self._asignar_tarea)
        row_btn_gest.addWidget(self.btn_asignar_tarea)

        row_btn_gest.addStretch(1)
        self._gestion_widget.btn_del.setMinimumHeight(34)
        self._gestion_widget.btn_del.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_btn_gest.addWidget(self._gestion_widget.btn_del)

        card_mail = _Card("Correo desde detalle")
        row_tpl = QHBoxLayout()
        row_tpl.addWidget(QLabel("Plantilla:"))

        self.cmb_plantilla = QComboBox()
        if self._plantillas:
            self.cmb_plantilla.addItems([p.get("nombre", "Plantilla") for p in self._plantillas])
        row_tpl.addWidget(self.cmb_plantilla, 1)
        card_mail.body.addLayout(row_tpl)

        self.lbl_email_destino = QLabel(_fix_mojibake_text(f"Destino: {self._obtener_email_destino() or 'Sin correo disponible'}"))
        self.lbl_email_destino.setObjectName("MutedLabel")
        self.lbl_email_destino.setWordWrap(True)
        card_mail.body.addWidget(self.lbl_email_destino)

        self.lbl_whatsapp_destino = QLabel(
            f"WhatsApp: {self._obtener_telefono_destino() or 'Sin teléfono disponible'}"
        )
        self.lbl_whatsapp_destino.setObjectName("MutedLabel")
        self.lbl_whatsapp_destino.setWordWrap(True)
        card_mail.body.addWidget(self.lbl_whatsapp_destino)

        row_mail_btns = QHBoxLayout()
        row_mail_btns.setSpacing(8)
        self.btn_preview_email = QPushButton("\U0001F441 Vista previa")
        self.btn_preview_email.setProperty("blockableAction", True)
        self.btn_preview_email.setMinimumHeight(34)
        self.btn_preview_email.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_preview_email.clicked.connect(self._vista_previa_email)

        self.btn_enviar_email = QPushButton("\u2709\ufe0f Enviar email")
        self.btn_enviar_email.setObjectName("PrimaryButton")
        self.btn_enviar_email.setProperty("blockableAction", True)
        self.btn_enviar_email.setMinimumHeight(34)
        self.btn_enviar_email.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_enviar_email.clicked.connect(self._enviar_email)

        self.btn_enviar_whatsapp = QPushButton("\U0001F7E2 Enviar WhatsApp")
        self.btn_enviar_whatsapp.setObjectName("PrimaryButton")
        self.btn_enviar_whatsapp.setProperty("blockableAction", True)
        self.btn_enviar_whatsapp.setMinimumHeight(34)
        self.btn_enviar_whatsapp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_enviar_whatsapp.clicked.connect(self._enviar_whatsapp)

        row_mail_btns.addWidget(self.btn_preview_email, 1)
        row_mail_btns.addWidget(self.btn_enviar_email, 1)
        row_mail_btns.addWidget(self.btn_enviar_whatsapp, 1)
        card_mail.body.addLayout(row_mail_btns)

        section_content = QWidget()
        section_layout = QVBoxLayout(section_content)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)
        section_layout.addWidget(self._gestion_widget)
        section_layout.addLayout(row_btn_gest)
        section_layout.addWidget(card_mail)
        section_layout.addStretch(1)
        card_gest.body.addWidget(section_content, 1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        right_scroll.setWidget(card_gest)
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([620, 620])
        root.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setMinimumWidth(100)
        btn_cerrar.clicked.connect(self.accept)
        btn_row.addWidget(btn_cerrar)
        root.addLayout(btn_row)

        self._aplicar_modo_backend()
        self._ajustar_layout_responsivo()
        QTimer.singleShot(0, self._actualizar_permisos_cartera)


    def _usa_backend_deudores(self) -> bool:
        return bool(self._session and getattr(self._session, "auth_source", "") == "backend")

    def _aplicar_modo_backend(self):
        if not self._usa_backend_deudores():
            return

        if getattr(self, "btn_editar_cliente", None) is not None:
            self.btn_editar_cliente.setEnabled(True)
            self.btn_editar_cliente.setToolTip("Editar datos del cliente conectado a CRM_Backend.")

        if getattr(self, "btn_registrar_pago", None) is not None:
            self.btn_registrar_pago.setEnabled(True)
            self.btn_registrar_pago.setToolTip("Registrar pago conectado a CRM_Backend.")

    def showEvent(self, event):
        super().showEvent(event)
        self._ajustar_layout_responsivo()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar_layout_responsivo()

    def _ajustar_layout_responsivo(self) -> None:
        if hasattr(self, "_main_splitter"):
            total_w = max(self._main_splitter.width(), self.width(), 1)
            left_target = int(total_w * 0.50)
            left_target = max(340, min(980, left_target))
            right_min = 420
            if total_w - left_target < right_min:
                left_target = max(300, total_w - right_min)
            self._main_splitter.setSizes([left_target, max(total_w - left_target, right_min)])

        if hasattr(self, "_right_splitter"):
            total_h = max(self._right_splitter.height(), 1)
            top_target = int(total_h * 0.42)
            top_target = max(190, min(460, top_target))
            bottom_min = 280
            if total_h - top_target < bottom_min:
                top_target = max(160, total_h - bottom_min)
            self._right_splitter.setSizes([top_target, max(total_h - top_target, bottom_min)])


    def _normalizar_fila_resumen_backend(self) -> None:
        if not isinstance(self._fila_resumen, dict):
            self._fila_resumen = {}

        resumen = dict(self._fila_resumen)
        rut_completo = _formatear_rut_completo(
            resumen.get("Rut_Afiliado", ""),
            resumen.get("Dv", ""),
            resumen.get("_RUT_COMPLETO", ""),
        )
        if rut_completo:
            rut_base, _, dv_base = rut_completo.partition("-")
            resumen["Rut_Afiliado"] = rut_base
            resumen["Dv"] = dv_base
            resumen["_RUT_COMPLETO"] = rut_completo

        if "Saldo_Actual" in resumen:
            resumen["Saldo Actual ($)"] = resumen.get("Saldo_Actual")
            resumen["Saldo Actual"] = resumen.get("Saldo_Actual")
        if "Copago" in resumen:
            resumen["Copago ($)"] = resumen.get("Copago")
        if "Total_Pagos" in resumen:
            resumen["Total Pagos ($)"] = resumen.get("Total_Pagos")

        self._fila_resumen = resumen

    def _resolver_rut_cliente(self) -> str:
        rut_info = str(self._info_cliente.get("RUT", "")).strip() if isinstance(self._info_cliente, dict) else ""
        if rut_info and rut_info not in ("â€”", "nan", "None", "N") and "-" in rut_info:
            rut_norm = _formatear_rut_completo(rut_info, "", rut_info)
            if rut_norm:
                return rut_norm

        rut_res = _formatear_rut_completo(
            self._fila_resumen.get("Rut_Afiliado", ""),
            self._fila_resumen.get("Dv", ""),
            self._fila_resumen.get("_RUT_COMPLETO", ""),
        )
        if rut_res:
            return rut_res

        if rut_info and rut_info not in ("â€”", "nan", "None", "N"):
            rut_norm = _formatear_rut_completo(rut_info, "", rut_info)
            if rut_norm:
                return rut_norm

        return _formatear_rut_completo(self._rut, "", self._rut) or self._rut

    def _normalizar_campos_info_cliente(self) -> None:
        if not isinstance(self._info_cliente, dict):
            self._info_cliente = {}
            return

        origen = dict(self._info_cliente)
        claves = {
            "RUT": ["RUT", "Rut", "rut"],
            "Nombre": ["Nombre", "Nombre_Afiliado", "nombre_afiliado"],
            "Correo": ["Correo", "mail_afiliado", "Mail Emp"],
            "Correo (Excel)": ["Correo (Excel)", "BN"],
            "Teléfono Fijo": ["Teléfono Fijo", "Tel?fono Fijo", "telefono_fijo_afiliado", "Telefono Empleador"],
            "Teléfono Móvil": ["Teléfono Móvil", "Tel?fono M?vil", "telefono_movil_afiliado", "Telefono Empleador"],
        }

        normalizado: dict[str, str] = {}
        for canon, aliases in claves.items():
            value = ""
            for key in aliases:
                raw = _fix_mojibake_text(str(origen.get(key, "")).strip())
                if raw and raw not in ("â€”", "nan", "None", "N"):
                    value = raw
                    break
            normalizado[_fix_mojibake_text(canon)] = value if value else "—"

        self._info_cliente = normalizado

    def _totales_financieros_desde_detalle(self) -> dict[str, float]:
        totales = {
            "Copago": 0.0,
            "Total_Pagos": 0.0,
            "Saldo_Actual": 0.0,
        }

        try:
            if self._df_detalle_completo is not None and not self._df_detalle_completo.empty:
                df = self._df_detalle_completo.copy()
                mask = (
                    df["Rut_Afiliado"].astype(str).str.strip()
                    .str.replace(".", "", regex=False)
                    .str.replace("-", "", regex=False)
                    .str.lstrip("0")
                    == str(self._rut).strip().replace(".", "").replace("-", "").lstrip("0")
                )
                filas = df.loc[mask]
                if not filas.empty:
                    for col in totales:
                        if col in filas.columns:
                            totales[col] = float(filas[col].apply(_parse_monto).sum())
                    return totales
        except Exception:
            pass

        for fila in self._filas_deuda or []:
            totales["Copago"] += _parse_monto(fila.get("Copago ($)", "") or fila.get("Mto Pagar", ""))
            totales["Total_Pagos"] += _parse_monto(fila.get("Total Pagos ($)", "") or fila.get("Pagos", ""))
            totales["Saldo_Actual"] += _parse_monto(fila.get("Saldo Actual ($)", "") or fila.get("Saldo Actual", ""))

        return totales

    def _sincronizar_resumen_financiero_desde_detalle(self) -> None:
        if not isinstance(self._fila_resumen, dict):
            self._fila_resumen = {}

        totales = self._totales_financieros_desde_detalle()
        self._fila_resumen["Copago"] = totales["Copago"]
        self._fila_resumen["Total_Pagos"] = totales["Total_Pagos"]
        self._fila_resumen["Saldo_Actual"] = totales["Saldo_Actual"]
        self._fila_resumen["Copago ($)"] = totales["Copago"]
        self._fila_resumen["Total Pagos ($)"] = totales["Total_Pagos"]
        self._fila_resumen["Saldo Actual ($)"] = totales["Saldo_Actual"]
        self._fila_resumen["Saldo Actual"] = totales["Saldo_Actual"]

    def _alinear_detalle_con_resumen_backend(self) -> None:
        if not self._usa_backend_deudores():
            return
        if not isinstance(self._filas_deuda, list) or len(self._filas_deuda) != 1:
            return

        fila = dict(self._filas_deuda[0])
        saldo = self._fila_resumen.get("Saldo_Actual", self._fila_resumen.get("Saldo Actual ($)", ""))
        copago = self._fila_resumen.get("Copago", self._fila_resumen.get("Copago ($)", ""))
        total_pagos = self._fila_resumen.get("Total_Pagos", self._fila_resumen.get("Total Pagos ($)", ""))

        if "Saldo Actual ($)" in fila:
            fila["Saldo Actual ($)"] = saldo
        if "Saldo Actual" in fila:
            fila["Saldo Actual"] = saldo
        if "Copago ($)" in fila:
            fila["Copago ($)"] = copago
        if "Mto Pagar" in fila:
            fila["Mto Pagar"] = copago
        if "Total Pagos ($)" in fila:
            fila["Total Pagos ($)"] = total_pagos
        if "Pagos" in fila:
            fila["Pagos"] = total_pagos

        self._filas_deuda = [fila]

    def _on_gestiones_actualizadas(self):
        self._recargar_desde_bd()
        self.gestiones_actualizadas.emit()

    def _emitir_actualizacion_gestiones(self) -> None:
        self._recargar_desde_bd()
        if hasattr(self, "_gestion_widget") and self._gestion_widget is not None:
            self._gestion_widget.refrescar()
        self.gestiones_actualizadas.emit()

    def _refrescar_gestiones_con_reintentos(self) -> None:
        self._emitir_actualizacion_gestiones()
        for delay_ms in (300, 900, 1800):
            QTimer.singleShot(delay_ms, self._emitir_actualizacion_gestiones)

    def _obtener_empresa_actual(self) -> str:
        for key in ("_empresa", "empresa", "Empresa"):
            empresa = str(self._fila_resumen.get(key, "")).strip()
            if empresa:
                return empresa

        if hasattr(self, "_gestion_widget") and self._gestion_widget is not None:
            empresa_widget = str(getattr(self._gestion_widget, "_empresa", "")).strip()
            if empresa_widget:
                return empresa_widget

        try:
            if self._df_detalle_completo is not None and not self._df_detalle_completo.empty:
                df = self._df_detalle_completo.copy()
                mask = (
                    df["Rut_Afiliado"].astype(str).str.strip()
                    .str.replace(".", "", regex=False)
                    .str.replace("-", "", regex=False)
                    .str.lstrip("0")
                    == str(self._rut).strip().replace(".", "").replace("-", "").lstrip("0")
                )
                filas = df.loc[mask]
                if not filas.empty and "_empresa" in filas.columns:
                    return str(filas.iloc[0].get("_empresa", "")).strip()
        except Exception:
            pass

        return ""

    def _es_usuario_ejecutiva(self) -> bool:
        if self._session is None:
            return False
        checker = getattr(self._session, "is_ejecutivo", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                pass
        role_txt = str(getattr(self._session, "role", "")).strip().lower()
        return role_txt.startswith("ejecut")

    def _empresas_asignadas_sesion(self) -> set[str]:
        try:
            empresas = obtener_empresas_asignadas_para_session(self._session)
        except Exception:
            empresas = []
        return {str(emp or "").strip().lower() for emp in empresas if str(emp or "").strip()}

    def _obtener_asignacion_empresa(self, empresa: str) -> dict:
        emp = str(empresa or "").strip()
        if not emp:
            return {}

        asignacion = obtener_asignacion_por_empresa_local(emp)
        if asignacion:
            return asignacion

        if self._usa_backend_deudores():
            try:
                rows, err = backend_list_cartera_asignaciones(self._session)
            except Exception:
                rows, err = [], "error"
            if not err:
                for row in rows or []:
                    if str(row.get("empresa", "")).strip().lower() == emp.lower():
                        return {
                            "empresa": str(row.get("empresa", "")).strip(),
                            "user_id": row.get("user_id"),
                            "email": str(row.get("email", "")).strip(),
                            "username": str(row.get("username", "")).strip(),
                        }
        return {}

    def _puede_operar_en_empresa_actual(self) -> bool:
        if not self._es_usuario_ejecutiva():
            return True
        empresa = str(self._obtener_empresa_actual() or "").strip().lower()
        if not empresa:
            return False

        asignacion = self._obtener_asignacion_empresa(empresa)
        if asignacion:
            user_id_actual = int(getattr(self._session, "user_id", 0) or 0)
            email_actual = str(getattr(self._session, "email", "")).strip().lower()
            user_id_asig = int(asignacion.get("user_id") or 0)
            email_asig = str(asignacion.get("email", "")).strip().lower()
            if user_id_actual and user_id_asig and user_id_actual == user_id_asig:
                return True
            if email_actual and email_asig and email_actual == email_asig:
                return True
            return False

        return empresa in self._empresas_asignadas_sesion()

    def _actualizar_permisos_cartera(self) -> None:
        can_operate = self._puede_operar_en_empresa_actual()
        self._can_operate_current_cartera = can_operate

        if getattr(self, "btn_agregar_gestion", None) is not None:
            self.btn_agregar_gestion.setEnabled(can_operate)
            self.btn_agregar_gestion.setToolTip(
                "" if can_operate else "Bloqueado: cartera no asignada a tu usuario"
            )

        if getattr(self, "btn_registrar_pago", None) is not None:
            self.btn_registrar_pago.setEnabled(can_operate)
            self.btn_registrar_pago.setToolTip(
                "Registrar pago conectado a CRM_Backend."
                if can_operate and self._usa_backend_deudores()
                else ("" if can_operate else "Bloqueado: cartera no asignada a tu usuario")
            )

        if hasattr(self, "_gestion_widget") and self._gestion_widget is not None:
            self._gestion_widget.set_allow_delete_manual(can_operate)

        if getattr(self, "btn_preview_email", None) is not None:
            self.btn_preview_email.setEnabled(can_operate)
            self.btn_preview_email.setToolTip(
                "" if can_operate else "Bloqueado: cartera no asignada a tu usuario"
            )
        if getattr(self, "btn_enviar_email", None) is not None:
            self.btn_enviar_email.setEnabled(can_operate)
            self.btn_enviar_email.setToolTip(
                "" if can_operate else "Bloqueado: cartera no asignada a tu usuario"
            )
        if getattr(self, "btn_enviar_whatsapp", None) is not None:
            self.btn_enviar_whatsapp.setEnabled(can_operate)
            self.btn_enviar_whatsapp.setToolTip(
                "" if can_operate else "Bloqueado: cartera no asignada a tu usuario"
            )

        mostrar_asignar = self._es_usuario_ejecutiva() and not can_operate
        if getattr(self, "btn_asignar_tarea", None) is not None:
            self.btn_asignar_tarea.setVisible(mostrar_asignar)
            self.btn_asignar_tarea.setEnabled(mostrar_asignar)
            self.btn_asignar_tarea.setToolTip(
                "Asignar tarea a la ejecutiva responsable de esta cartera."
            )

    def _ejecutivas_destino_por_empresa(self, empresa: str) -> list[dict]:
        asignacion = self._obtener_asignacion_empresa(empresa)
        if not asignacion:
            return []

        nombre = str(asignacion.get("username", "")).strip()
        email = str(asignacion.get("email", "")).strip()
        user_id = asignacion.get("user_id")
        if nombre and email:
            display = f"{nombre} ({email})"
        elif nombre:
            display = nombre
        elif email:
            display = email
        elif user_id:
            display = f"Ejecutiva #{user_id}"
        else:
            display = "Ejecutiva asignada"

        return [{
            "user_id": user_id,
            "username": nombre,
            "email": email,
            "display": display,
        }]

    def _refrescar_labels_cliente(self) -> None:
        for etiqueta, lbl in self._labels_cliente.items():
            valor = self._resolver_rut_cliente() if etiqueta == "RUT" else _fix_mojibake_text(str(self._info_cliente.get(etiqueta, "—")).strip())
            lbl.setText(valor if valor else "—")

        if self.lbl_nombre_header is not None:
            self.lbl_nombre_header.setText(_fix_mojibake_text(str(self._info_cliente.get("Nombre", self._rut))))

        if self.lbl_rut_header is not None:
            self.lbl_rut_header.setText(f"RUT: {self._resolver_rut_cliente()}")

        if self.lbl_exp is not None:
            n_exp = len(self._filas_deuda)
            self.lbl_exp.setText(f"{n_exp} expediente{'s' if n_exp != 1 else ''}")

        self.lbl_email_destino.setText(
            _fix_mojibake_text(f"Destino: {self._obtener_email_destino() or 'Sin correo disponible'}")
        )
        self.lbl_whatsapp_destino.setText(
            _fix_mojibake_text(f"WhatsApp: {self._obtener_telefono_destino() or 'Sin teléfono disponible'}")
        )

    def _actualizar_tabla_detalle(self):
        if self.tbl_deuda is not None:
            self.tbl_deuda.setModel(_DeudaModel(self._filas_deuda))

    def _actualizar_kpis_financieros(self):
        self._normalizar_fila_resumen_backend()
        self._sincronizar_resumen_financiero_desde_detalle()
        copago = self._obtener_monto_resumen("Copago", "Copago ($)")
        total_pagos = self._obtener_monto_resumen("Total_Pagos", "Total Pagos ($)")
        saldo_actual = self._obtener_monto_resumen("Saldo_Actual", "Saldo Actual ($)", "Saldo Actual")

        if self.kpi_copago is not None:
            self.kpi_copago.set_value(copago)
        if self.kpi_total_pagos is not None:
            self.kpi_total_pagos.set_value(total_pagos)
        if self.kpi_saldo_actual is not None:
            self.kpi_saldo_actual.set_value(saldo_actual)

    def _recargar_desde_bd(self):
        if self._usa_backend_deudores():
            empresa = self._obtener_empresa_actual()
            payload, err = backend_get_deudor_detalle(self._session, rut=self._rut, empresa=empresa)
            if err:
                return

            df_det, fila_res = _backend_detalle_response_to_local(payload or {})
            self._df_detalle_completo = df_det
            self._fila_resumen.update(fila_res)
            self._normalizar_fila_resumen_backend()

            info_cliente, filas_deuda = extraer_detalle_deudor(df_det, self._rut)
            self._info_cliente = info_cliente or self._info_cliente
            self._filas_deuda = filas_deuda or []
            self._alinear_detalle_con_resumen_backend()
            self._sincronizar_resumen_financiero_desde_detalle()
            self._normalizar_campos_info_cliente()

            self._refrescar_labels_cliente()
            self._actualizar_tabla_detalle()
            self._actualizar_kpis_financieros()
            self._actualizar_permisos_cartera()
            return

        empresa = self._obtener_empresa_actual()
        if not empresa:
            return

        df_det = cargar_detalle_empresa(empresa)
        df_res = cargar_empresa(empresa)

        self._df_detalle_completo = df_det

        if not df_res.empty:
            rut_norm = str(self._rut).strip().replace(".", "").replace("-", "").lstrip("0")
            mask = (
                df_res["Rut_Afiliado"].astype(str)
                .str.replace(".", "", regex=False)
                .str.replace("-", "", regex=False)
                .str.strip()
                .str.lstrip("0")
                == rut_norm
            )
            filas_res = df_res.loc[mask]
            if not filas_res.empty:
                self._fila_resumen = filas_res.iloc[0].to_dict()

        info_cliente, filas_deuda = extraer_detalle_deudor(df_det, self._rut)
        self._info_cliente = info_cliente or self._info_cliente
        self._filas_deuda = filas_deuda or []

        fallbacks = {
            "RUT": self._resolver_rut_cliente(),
            "Nombre": self._fila_resumen.get("Nombre_Afiliado", ""),
            "Correo": self._fila_resumen.get("mail_afiliado", "") or self._fila_resumen.get("Mail Emp", ""),
            "Correo (Excel)": self._fila_resumen.get("BN", "") or self._fila_resumen.get("Mail Emp", ""),
            "Teléfono Fijo": self._fila_resumen.get("telefono_fijo_afiliado", "") or self._fila_resumen.get("Telefono Empleador", ""),
            "Teléfono Móvil": self._fila_resumen.get("telefono_movil_afiliado", "") or self._fila_resumen.get("Telefono Empleador", ""),
        }
        for k, v in fallbacks.items():
            actual = str(self._info_cliente.get(k, "")).strip()
            if actual in ("", "â€”", "nan", "None", "N"):
                limpio = str(v).strip()
                self._info_cliente[k] = limpio if limpio not in ("", "nan", "None", "N") else "â€”"
        self._normalizar_campos_info_cliente()

        self._normalizar_fila_resumen_backend()
        self._alinear_detalle_con_resumen_backend()
        self._sincronizar_resumen_financiero_desde_detalle()
        self._refrescar_labels_cliente()
        self._actualizar_tabla_detalle()
        self._actualizar_kpis_financieros()
        self._actualizar_permisos_cartera()

    def _editar_cliente(self):
        dlg = _EditarClienteDialog(self._info_cliente, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        nuevos = dlg.obtener_datos()
        empresa = self._obtener_empresa_actual()

        try:
            if self._usa_backend_deudores():
                rut_anterior = self._rut

                _, err = backend_update_deudor_cliente(
                    self._session,
                    rut_original=rut_anterior,
                    empresa=empresa,
                    rut=nuevos.get("RUT", ""),
                    nombre=nuevos.get("Nombre", ""),
                    correo=nuevos.get("Correo", ""),
                    correo_excel=nuevos.get("Correo (Excel)", ""),
                    telefono_fijo=nuevos.get("Teléfono Fijo", ""),
                    telefono_movil=nuevos.get("Teléfono Móvil", ""),
                )
                if err:
                    raise ValueError(err)

                rut_editado = nuevos.get("RUT", rut_anterior).strip() or rut_anterior
                rut_base = rut_editado.replace(".", "")
                if "-" in rut_base:
                    rut_base = rut_base.split("-", 1)[0]
                rut_base = rut_base.replace("-", "").lstrip("0") or rut_anterior

                self._rut = rut_base
                self._info_cliente["RUT"] = rut_editado or ""
                self._info_cliente["Nombre"] = nuevos.get("Nombre", "") or ""
                self._info_cliente["Correo"] = nuevos.get("Correo", "") or ""
                self._info_cliente["Correo (Excel)"] = nuevos.get("Correo (Excel)", "") or ""
                self._info_cliente["Teléfono Fijo"] = nuevos.get("Teléfono Fijo", "") or ""
                self._info_cliente["Teléfono Móvil"] = nuevos.get("Teléfono Móvil", "") or ""

                self._fila_resumen["Rut_Afiliado"] = self._rut
                self._fila_resumen["_RUT_COMPLETO"] = self._info_cliente["RUT"]
                self._fila_resumen["Nombre_Afiliado"] = self._info_cliente["Nombre"]
                self._fila_resumen["mail_afiliado"] = self._info_cliente["Correo"]
                self._fila_resumen["BN"] = self._info_cliente["Correo (Excel)"]
                self._fila_resumen["telefono_fijo_afiliado"] = self._info_cliente["Teléfono Fijo"]
                self._fila_resumen["telefono_movil_afiliado"] = self._info_cliente["Teléfono Móvil"]

                self._refrescar_labels_cliente()
                self._recargar_desde_bd()
                self.gestiones_actualizadas.emit()

                QMessageBox.information(
                    self,
                    "Actualización exitosa",
                    " Los datos del cliente fueron actualizados correctamente en CRM_Backend."
                )
                return

            ok = actualizar_cliente_por_rut(
                empresa=empresa,
                rut_original=self._rut,
                datos_actualizados={
                    "Rut_Afiliado": nuevos.get("RUT", ""),
                    "Nombre_Afiliado": nuevos.get("Nombre", ""),
                    "mail_afiliado": nuevos.get("Correo", ""),
                    "BN": nuevos.get("Correo (Excel)", ""),
                    "telefono_fijo_afiliado": nuevos.get("Teléfono Fijo", ""),
                    "telefono_movil_afiliado": nuevos.get("Teléfono Móvil", ""),
                }
            )

            if not ok:
                QMessageBox.warning(
                    self,
                    "Sin cambios",
                    "No se encontró un registro para actualizar en la base de datos."
                )
                return

            rut_anterior = self._rut
            self._rut = nuevos.get("RUT", rut_anterior).strip() or rut_anterior

            self._info_cliente["RUT"] = nuevos.get("RUT", "") or ""
            self._info_cliente["Nombre"] = nuevos.get("Nombre", "") or ""
            self._info_cliente["Correo"] = nuevos.get("Correo", "") or ""
            self._info_cliente["Correo (Excel)"] = nuevos.get("Correo (Excel)", "") or ""
            self._info_cliente["Teléfono Fijo"] = nuevos.get("Teléfono Fijo", "") or ""
            self._info_cliente["Teléfono Móvil"] = nuevos.get("Teléfono Móvil", "") or ""

            self._fila_resumen["Rut_Afiliado"] = self._info_cliente["RUT"]
            self._fila_resumen["Nombre_Afiliado"] = self._info_cliente["Nombre"]
            self._fila_resumen["mail_afiliado"] = self._info_cliente["Correo"]
            self._fila_resumen["BN"] = self._info_cliente["Correo (Excel)"]
            self._fila_resumen["telefono_fijo_afiliado"] = self._info_cliente["Teléfono Fijo"]
            self._fila_resumen["telefono_movil_afiliado"] = self._info_cliente["Teléfono Móvil"]

            self._refrescar_labels_cliente()
            self.gestiones_actualizadas.emit()

            QMessageBox.information(
                self,
                "Actualización exitosa",
                " Los datos del cliente fueron actualizados correctamente en la base de datos."
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error al actualizar",
                f"No se pudieron actualizar los datos del cliente.\n\nDetalle:\n{e}"
            )

    def _obtener_monto_resumen(self, *keys: str) -> str:
        aliases = {
            "Copago": "Copago",
            "Copago ($)": "Copago",
            "Mto Pagar": "Copago",
            "Total_Pagos": "Total_Pagos",
            "Total Pagos ($)": "Total_Pagos",
            "Pagos": "Total_Pagos",
            "Saldo_Actual": "Saldo_Actual",
            "Saldo Actual ($)": "Saldo_Actual",
            "Saldo Actual": "Saldo_Actual",
        }

        totales_detalle = self._totales_financieros_desde_detalle()
        for key in keys:
            canon = aliases.get(key)
            if canon in totales_detalle:
                return _formatear_moneda_chilena(totales_detalle[canon])

        for key in keys:
            if key in self._fila_resumen:
                val = str(self._fila_resumen.get(key, "")).strip()
                if val and val not in ("nan", "None"):
                    return _formatear_moneda_chilena(val)
        return ""

    def _agregar_gestion(self):
        nombre = str(self._info_cliente.get("Nombre", "")).strip() or self._rut
        dlg = _AgregarGestionDialog(
            rut=self._rut,
            nombre=nombre,
            session=self._session,
            empresa=self._obtener_empresa_actual(),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refrescar_gestiones_con_reintentos()

    def _asignar_tarea(self):
        empresa = self._obtener_empresa_actual()
        if not empresa:
            QMessageBox.warning(self, "Empresa no disponible", "No fue posible determinar la cartera del deudor.")
            return

        ejecutivas = self._ejecutivas_destino_por_empresa(empresa)
        if not ejecutivas:
            QMessageBox.warning(
                self,
                "Sin ejecutiva asignada",
                "No hay una ejecutiva configurada para esta cartera. Solicita la asignacin al supervisor.",
            )
            return

        dlg = _AsignarTareaDialog(empresa=empresa, ejecutivas=ejecutivas, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        datos = dlg.datos()
        ejecutiva = datos.get("ejecutiva") if isinstance(datos, dict) else {}
        if not isinstance(ejecutiva, dict):
            ejecutiva = {}

        nombre = str(ejecutiva.get("username", "")).strip()
        email = str(ejecutiva.get("email", "")).strip()
        if nombre and email:
            destino = f"{nombre} ({email})"
        else:
            destino = nombre or email or "Ejecutiva asignada"

        obs_usuario = str(datos.get("observacion", "")).strip() if isinstance(datos, dict) else ""
        observacion = f"Tarea: Contactar cliente | Destino: {destino}"
        if obs_usuario:
            observacion += f" | Nota: {obs_usuario}"

        try:
            fecha = datetime.date.today().strftime("%d/%m/%Y")
            nombre_afiliado = str(self._info_cliente.get("Nombre", "")).strip() or self._rut
            assigned_to_user_id = ejecutiva.get("user_id")
            try:
                assigned_to_user_id = int(assigned_to_user_id) if assigned_to_user_id is not None else None
            except Exception:
                assigned_to_user_id = None

            if self._usa_backend_deudores():
                _, err = backend_create_gestion(
                    self._session,
                    rut=self._rut,
                    empresa=empresa,
                    nombre_afiliado=nombre_afiliado,
                    tipo_gestion="Manual",
                    estado="Gesti\u00f3n asignada",
                    fecha_gestion=fecha,
                    observacion=observacion,
                    origen="manual",
                    assigned_to_user_id=assigned_to_user_id,
                )
                if err:
                    raise ValueError(err)
            else:
                insertar_gestion_manual(
                    rut=self._rut,
                    nombre=nombre_afiliado,
                    tipo_gestion="Manual",
                    estado="Gesti\u00f3n asignada",
                    fecha=fecha,
                    observacion=observacion,
                )

            QMessageBox.information(self, "Tarea asignada", "\u2705 La tarea fue registrada como 'Gesti\u00f3n asignada'.")
            self._refrescar_gestiones_con_reintentos()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo asignar la tarea.\n\nDetalle:\n{e}")

    def _expedientes_disponibles(self) -> list[str]:
        expedientes = []
        for fila in self._filas_deuda:
            valor = str(
                fila.get("N° Expediente", "") or fila.get("No Licencia", "") or fila.get("Folio LIQ", "")
            ).strip()
            if valor and valor not in expedientes:
                expedientes.append(valor)
        return expedientes

    def _saldos_por_expediente(self) -> dict[str, str]:
        saldos: dict[str, str] = {}
        for fila in self._filas_deuda:
            expediente = str(
                fila.get("N° Expediente", "") or fila.get("No Licencia", "") or fila.get("Folio LIQ", "")
            ).strip()
            if not expediente:
                continue

            saldo = str(
                fila.get("Saldo Actual ($)", "") or fila.get("Saldo Actual", "")
            ).strip()
            if saldo:
                saldos[expediente] = saldo
        return saldos

    def _registrar_pago(self):
        saldo_actual = self._obtener_monto_resumen("Saldo_Actual", "Saldo Actual ($)", "Saldo Actual")
        expedientes = self._expedientes_disponibles()
        saldos_por_expediente = self._saldos_por_expediente()

        dlg = _RegistrarPagoDialog(
            saldo_actual=saldo_actual,
            expedientes=expedientes,
            saldos_por_expediente=saldos_por_expediente,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        datos = dlg.obtener_datos()
        expediente = datos["expediente"]
        tipo_pago = datos["tipo_pago"]
        monto = datos["monto"]
        observaciones = datos["observaciones"]
        empresa = self._obtener_empresa_actual()
        nombre = str(self._info_cliente.get("Nombre", "")).strip() or self._rut

        try:
            if self._usa_backend_deudores():
                resultado, err = backend_register_pago(
                    self._session,
                    rut=self._rut,
                    empresa=empresa,
                    expediente=expediente,
                    tipo_pago=tipo_pago,
                    monto=monto,
                    observaciones=observaciones,
                )
                if err:
                    raise ValueError(err)

                self._refrescar_gestiones_con_reintentos()

                QMessageBox.information(
                    self,
                    "Pago registrado",
                    " El pago fue registrado correctamente y la deuda fue actualizada."
                )
                return

            resultado = registrar_pago_por_rut(
                empresa=empresa,
                rut=self._rut,
                tipo_pago=tipo_pago,
                monto=monto,
                expediente=expediente,
            )

            estado_gestion = "Abonado" if str(tipo_pago).strip() == "Abono a la deuda" else "Pagado"

            insertar_gestion_pago(
                rut=self._rut,
                nombre=nombre,
                estado=estado_gestion,
                fecha=datetime.datetime.now().strftime("%d/%m/%Y"),
                empresa=empresa,
                expediente=expediente,
                monto=monto,
                tipo_pago=tipo_pago,
                observaciones_usuario=observaciones,
            )

            self._refrescar_gestiones_con_reintentos()

            QMessageBox.information(
                self,
                "Pago registrado",
                " El pago fue registrado correctamente y la deuda fue actualizada."
            )

        except Exception as e:
            QMessageBox.warning(self, "No se pudo registrar el pago", str(e))

    def _obtener_email_destino(self) -> str:
        posibles = [
            self._info_cliente.get("Correo", ""),
            self._info_cliente.get("Correo (Excel)", ""),
            self._fila_resumen.get("mail_afiliado", ""),
            self._fila_resumen.get("BN", ""),
            self._fila_resumen.get("Mail Emp", ""),
        ]
        for val in posibles:
            email = _fix_mojibake_text(str(val).strip())
            if email and email not in ("", "nan", "None", "N") and "@" in email:
                return email
        return ""

    def _obtener_telefono_destino(self) -> str:
        posibles = [
            self._info_cliente.get("Teléfono Móvil", ""),
            self._info_cliente.get("Teléfono Fijo", ""),
            self._fila_resumen.get("telefono_movil_afiliado", ""),
            self._fila_resumen.get("telefono_fijo_afiliado", ""),
            self._fila_resumen.get("Telefono Empleador", ""),
        ]
        for val in posibles:
            tel = _fix_mojibake_text(str(val).strip())
            if tel and tel not in ("", "nan", "None", "N"):
                return tel
        return ""

    def _plantilla_actual(self) -> dict:
        if not self._plantillas:
            return {
                "nombre": "Correo simple",
                "asunto": "Información de su cuenta",
                "cuerpo": "Estimado/a {nombre},\n\nLe contactamos por su cuenta.\n\nSaludos."
            }
        idx = self.cmb_plantilla.currentIndex()
        if idx < 0 or idx >= len(self._plantillas):
            return self._plantillas[0]
        return self._plantillas[idx]

    def _construir_fila_envio(self) -> dict:
        base = dict(self._fila_resumen)

        def _txt(v) -> str:
            return str(v or "").strip()

        def _invalido(v: str) -> bool:
            t = _txt(v).lower()
            return t in {"", "nan", "none", "n", "—", "-"}

        def _parece_contador(v: str) -> bool:
            t = _txt(v)
            return bool(t.isdigit() and int(t) <= 20)

        if "Rut_Afiliado" not in base:
            base["Rut_Afiliado"] = self._info_cliente.get("RUT", self._rut)

        if "Nombre_Afiliado" not in base:
            base["Nombre_Afiliado"] = self._info_cliente.get("Nombre", self._rut)

        if "mail_afiliado" not in base or "@" not in str(base.get("mail_afiliado", "")):
            base["mail_afiliado"] = self._obtener_email_destino()

        if "BN" not in base or "@" not in str(base.get("BN", "")):
            base["BN"] = self._obtener_email_destino()

        if "telefono_movil_afiliado" not in base or not str(base.get("telefono_movil_afiliado", "")).strip():
            base["telefono_movil_afiliado"] = self._info_cliente.get("Teléfono Móvil", "")

        if "telefono_fijo_afiliado" not in base or not str(base.get("telefono_fijo_afiliado", "")).strip():
            base["telefono_fijo_afiliado"] = self._info_cliente.get("Teléfono Fijo", "")

        if self._filas_deuda:
            primera = self._filas_deuda[0]
            exp_detalle = _txt(
                primera.get("N° Expediente", "")
                or primera.get("No Licencia", "")
                or primera.get("Folio LIQ", "")
            )
            exp_base = _txt(base.get("Nro_Expediente", base.get("nro_expediente", "")))
            empresa = _txt(base.get("_empresa", base.get("empresa", ""))).lower()

            # Prioriza el folio/licencia real del detalle cuando el resumen trae contador (ej: "1")
            # o viene sin dato.
            if exp_detalle and (_invalido(exp_base) or _parece_contador(exp_base) or empresa == "cart-56"):
                base["Nro_Expediente"] = exp_detalle
                base["nro_expediente"] = exp_detalle
                base["No_Licencia"] = exp_detalle
            elif exp_base:
                base["No_Licencia"] = exp_base
            if "Saldo_Actual" not in base:
                base["Saldo_Actual"] = primera.get("Saldo Actual ($)", "") or primera.get("Saldo Actual", "")
            if "Copago" not in base:
                base["Copago"] = primera.get("Copago ($)", "") or primera.get("Mto Pagar", "")
            if "Total_Pagos" not in base:
                base["Total_Pagos"] = primera.get("Total Pagos ($)", "") or primera.get("Pagos", "")
            if "MAX_Emision_ok" not in base:
                base["MAX_Emision_ok"] = primera.get("Fecha Emisión", "") or primera.get("Fecha Recep ISA", "")
            if "MIN_Emision_ok" not in base:
                base["MIN_Emision_ok"] = primera.get("Fecha Emisión", "") or primera.get("Fecha Recep", "")
            if "mail_afiliado" not in base or "@" not in str(base.get("mail_afiliado", "")):
                base["mail_afiliado"] = primera.get("Correo", "") if "@" in str(primera.get("Correo", "")) else self._obtener_email_destino()

        return base

    def _generar_preview(self) -> tuple[str, str, str, str, str]:
        email = self._obtener_email_destino()
        fila = self._construir_fila_envio()
        plantilla = self._plantilla_actual()
        variables = variables_desde_fila(fila)
        asunto, cuerpo = renderizar(plantilla, variables)
        nombre = str(fila.get("Nombre_Afiliado", self._rut)).strip()
        plantilla_nombre = plantilla.get("nombre", "Plantilla")
        return email, nombre, plantilla_nombre, asunto, cuerpo

    def _vista_previa_email(self):
        email, _, _, asunto, cuerpo = self._generar_preview()

        if not email:
            QMessageBox.warning(
                self,
                "Sin email",
                "El deudor no tiene un correo válido disponible en el detalle."
            )
            return

        dlg = _VistaPreviaEmailDialog(email, asunto, cuerpo, self)
        dlg.exec()

    def _smtp_config_disponible(self) -> tuple[bool, dict]:
        if sesion_smtp_activa():
            ses = cargar_sesion_smtp()
            return True, ses

        cfg = cargar_config()
        host = str(cfg.get("host", "")).strip()
        usuario = str(cfg.get("usuario", "")).strip()
        nombre_remitente = str(cfg.get("nombre_remitente", "")).strip() or usuario
        port = int(cfg.get("port", 587) or 587)
        tls = bool(cfg.get("tls", True))

        cfg_out = {
            "host": host,
            "usuario": usuario,
            "nombre_remitente": nombre_remitente,
            "port": port,
            "tls": tls,
        }
        return bool(host and usuario), cfg_out

    def _enviar_email(self):
        email, nombre, plantilla_nombre, asunto, cuerpo = self._generar_preview()

        if not email:
            QMessageBox.warning(
                self,
                "Sin email",
                "El deudor no tiene un correo válido disponible en el detalle."
            )
            return

        ok_cfg, cfg = self._smtp_config_disponible()
        if not ok_cfg:
            QMessageBox.warning(
                self,
                "Configuración SMTP requerida",
                "Debes iniciar sesión o configurar el servidor SMTP en el módulo "
                "Envíos Programados antes de enviar correos desde el detalle del deudor."
            )
            return

        if not sesion_smtp_activa():
            password, ok = QInputDialog.getText(
                self,
                "Contraseña SMTP",
                "Ingresa la contraseña o clave de aplicación del servidor:",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not str(password).strip():
                QMessageBox.information(
                    self,
                    "Envío cancelado",
                    "No se ingresó la contraseña del servidor SMTP."
                )
                return

            cfg = {
                **cfg,
                "password": str(password).strip(),
            }
            guardar_sesion_smtp(cfg)
        else:
            cfg = cargar_sesion_smtp()

        fila = self._construir_fila_envio()
        df_dest = pd.DataFrame([fila])

        params = EnvioParams(
            host=cfg["host"],
            port=cfg["port"],
            tls=cfg["tls"],
            usuario=cfg["usuario"],
            password=cfg["password"],
            nombre_remitente=cfg["nombre_remitente"],
            plantilla=self._plantilla_actual(),
            df_destinatarios=df_dest,
            col_email="mail_afiliado",
            pausa_segundos=0,
        )

        self._ultimo_asunto = asunto
        self._ultimo_email = email
        self._ultimo_nombre = nombre
        self._ultima_plantilla = plantilla_nombre

        self.btn_enviar_email.setEnabled(False)
        self.btn_preview_email.setEnabled(False)
        self.btn_enviar_whatsapp.setEnabled(False)

        self._email_worker = EnvioWorker(params, self)
        self._email_worker.resultado.connect(self._on_email_resultado)
        self._email_worker.terminado.connect(self._on_email_terminado)
        self._email_worker.error_fatal.connect(self._on_email_error_fatal)
        self._email_worker.start()

    def _enviar_whatsapp(self):
        telefono_raw = self._obtener_telefono_destino()
        telefono = _limpiar_telefono_para_whatsapp(telefono_raw)

        if not telefono:
            QMessageBox.warning(
                self,
                "Sin teléfono",
                "El deudor no tiene un teléfono válido disponible en el detalle."
            )
            return

        _, nombre, plantilla_nombre, asunto, cuerpo = self._generar_preview()
        mensaje = cuerpo.strip()

        if not mensaje:
            QMessageBox.warning(
                self,
                "Sin mensaje",
                "No se pudo generar el mensaje desde la plantilla seleccionada."
            )
            return

        try:
            texto_codificado = QUrl.toPercentEncoding(mensaje).data().decode("utf-8")
            url = f"https://web.whatsapp.com/send?phone={telefono}&text={texto_codificado}"

            _abrir_url_en_chrome(url)

            if self._usa_backend_deudores():
                _, err = backend_create_gestion(
                    self._session,
                    rut=self._rut,
                    empresa=self._obtener_empresa_actual(),
                    nombre_afiliado=nombre or self._rut,
                    tipo_gestion="Whatsapp",
                    estado="Enviado",
                    fecha_gestion=datetime.datetime.now().strftime("%d/%m/%Y"),
                    observacion=plantilla_nombre or asunto or "Mensaje enviado por WhatsApp",
                    origen="backend_whatsapp",
                )
                if err:
                    raise ValueError(err)
            else:
                insertar_gestion_manual(
                    rut=self._rut,
                    nombre=nombre or self._rut,
                    tipo_gestion="Whatsapp",
                    estado="Enviado",
                    fecha=datetime.datetime.now().strftime("%d/%m/%Y"),
                    observacion=plantilla_nombre or asunto or "Mensaje enviado por WhatsApp",
                )

            self._refrescar_gestiones_con_reintentos()

            QMessageBox.information(
                self,
                "WhatsApp abierto",
                " Se abrió WhatsApp Web en Google Chrome y la gestión fue registrada correctamente."
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error al abrir WhatsApp",
                f"No se pudo abrir WhatsApp Web en Google Chrome o registrar la gestión.\n\nDetalle:\n{e}"
            )

    def _on_email_resultado(self, resultado: ResultadoEnvio):
        estado = "Enviado" if resultado.ok else "Fallido"
        registrar_historial_envio(
            rut=self._rut,
            nombre=self._ultimo_nombre,
            email=self._ultimo_email or resultado.email,
            asunto=self._ultimo_asunto,
            plantilla=self._ultima_plantilla,
            estado=estado,
            detalle=resultado.mensaje,
            origen="detalle_deudor",
        )

    def _on_email_terminado(self, ok_count: int, fallidos: int, omitidos: int):
        can_operate = bool(getattr(self, "_can_operate_current_cartera", True))
        self.btn_enviar_email.setEnabled(can_operate)
        self.btn_preview_email.setEnabled(can_operate)
        self.btn_enviar_whatsapp.setEnabled(can_operate)

        if ok_count > 0:
            try:
                if self._usa_backend_deudores():
                    _, err = backend_create_gestion(
                        self._session,
                        rut=self._rut,
                        empresa=self._obtener_empresa_actual(),
                        nombre_afiliado=self._ultimo_nombre or self._rut,
                        tipo_gestion="Email",
                        estado="Enviado",
                        fecha_gestion=datetime.datetime.now().strftime("%d/%m/%Y"),
                        observacion=self._ultima_plantilla or "Correo enviado",
                        origen="backend_email",
                    )
                    if err:
                        raise ValueError(err)
                else:
                    insertar_gestion_manual(
                        rut=self._rut,
                        nombre=self._ultimo_nombre or self._rut,
                        tipo_gestion="Email",
                        estado="Enviado",
                        fecha=datetime.datetime.now().strftime("%d/%m/%Y"),
                        observacion=self._ultima_plantilla or "Correo enviado",
                    )

                self._refrescar_gestiones_con_reintentos()

            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Correo enviado, pero gestión no registrada",
                    f"El correo se envió correctamente, pero no se pudo registrar la gestión.\n\nDetalle:\n{e}"
                )

        if ok_count > 0 and fallidos == 0:
            QMessageBox.information(
                self,
                "Correo enviado",
                f" El correo fue enviado correctamente a {self._ultimo_email}."
            )
        else:
            QMessageBox.warning(
                self,
                "Resultado del envío",
                f"Enviados: {ok_count}\nFallidos: {fallidos}\nOmitidos: {omitidos}"
            )

    def _on_email_error_fatal(self, err: str):
        can_operate = bool(getattr(self, "_can_operate_current_cartera", True))
        self.btn_enviar_email.setEnabled(can_operate)
        self.btn_preview_email.setEnabled(can_operate)
        self.btn_enviar_whatsapp.setEnabled(can_operate)

        registrar_historial_envio(
            rut=self._rut,
            nombre=self._ultimo_nombre,
            email=self._ultimo_email,
            asunto=self._ultimo_asunto,
            plantilla=self._ultima_plantilla,
            estado="Error fatal",
            detalle=err,
            origen="detalle_deudor",
        )

        QMessageBox.critical(self, "Error al enviar email", err)
















