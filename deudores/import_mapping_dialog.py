from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


NA_TEXT = "N/A — sin columna asignada"


@dataclass(frozen=True)
class ImportField:
    key: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()


COMMON_SUMMARY_FIELDS = (
    ImportField("Rut_Afiliado", "RUT", True, ("rut afiliado", "rut deudor", "rut")),
    ImportField("Dv", "DV", False, ("digito verificador", "dv rut")),
    ImportField("Nombre_Afiliado", "Nombre", True, ("nombre afiliado", "nombre deudor", "nombre")),
    ImportField("Estado_deudor", "Estado deudor", False, ("estado", "estado gestion", "estado caso")),
    ImportField("Nro_Expediente", "N° Expediente", False, ("numero expediente", "expediente", "id deuda")),
    ImportField("MAX_Emision_ok", "Última Emisión", False, ("ultima emision", "max emision")),
    ImportField("MIN_Emision_ok", "Primera Emisión", False, ("primera emision", "min emision")),
    ImportField("Copago", "Copago ($)", False, ("monto cobrar", "monto")),
    ImportField("Total_Pagos", "Total Pagos ($)", False, ("total pagos", "pagos")),
    ImportField("Saldo_Actual", "Saldo Actual ($)", False, ("saldo actual", "saldo")),
)


IMPORT_FIELDS: dict[str, tuple[ImportField, ...]] = {
    "Consalud": COMMON_SUMMARY_FIELDS,
    "Cart-56": (
        ImportField("RUT Emp", "RUT", True, ("rut empresa", "rut empleador")),
        ImportField("Empresa", "Nombre", False, ("nombre empresa", "empleador")),
        ImportField("Mail Emp", "Correo", False, ("email empresa", "correo empresa", "mail empleador")),
        ImportField("Telefono Empleador", "Teléfono", False, ("telefono empresa", "fono empleador")),
        ImportField("No Licencia", "N° Licencia", True, ("folio liq", "numero licencia", "nro licencia")),
        ImportField("Nombre Afil", "Nombre afiliado", False, ("nombre afiliado",)),
        ImportField("RUT Afil", "RUT afiliado", False, ("rut afiliado",)),
        ImportField("Fecha Pago", "Fecha pago", False),
        ImportField("Fecha Recep", "Fecha recepción", False, ("fecha recepcion",)),
        ImportField("Fecha Recep ISA", "Fecha recepción ISA", False, ("fecha recepcion isa",)),
        ImportField("Dias Pagar", "Días para pagar", False, ("dias pago",)),
        ImportField("Mto Pagar", "Monto a pagar", True, ("monto pagar", "monto")),
    ),
    "Cruz Blanca": (
        ImportField("Mandante", "Compañía", True, ("compania", "empresa")),
        ImportField("RUT_Deudor", "RUT deudor", True, ("rut", "rut afiliado")),
        ImportField("Nombre_Deudor", "Nombre", True, ("nombre", "nombre afiliado")),
        ImportField("Estado_Gestion", "Estado deudor", True, ("estado", "estado gestion")),
        ImportField("ID_Deuda", "ID deuda", False, ("expediente", "numero expediente")),
        ImportField("Email_Deudor", "Correo", False, ("email", "correo")),
        ImportField("Telefono3_Deudor", "Teléfono", False, ("telefono 3", "telefono", "fono")),
        ImportField("Direccion_Deudor", "Dirección", False, ("direccion",)),
        ImportField("Comuna_Deudor", "Comuna", False, ("comuna",)),
        ImportField("Ciudad_Deudor", "Ciudad", False, ("ciudad",)),
        ImportField("Fecha_Emision_Deuda", "Fecha emisión", True, ("fecha emision",)),
        ImportField("Fecha_Vencimiento_Deuda", "Fecha vencimiento", True, ("fecha vencimiento",)),
        ImportField("Fecha_Prestacion", "Fecha prestación", False, ("fecha prestacion",)),
        ImportField("Fecha_Prestacion2", "Fecha prestación 2", False, ("fecha prestacion 2",)),
        ImportField("Prestador", "Prestador", False),
        ImportField("Monto_Total", "Monto total", False),
        ImportField("Monto_Cobrar", "Monto cobrar", True, ("monto a cobrar",)),
        ImportField("Monto_Facturado", "Monto facturado", False),
        ImportField("Monto_Liquidado", "Monto liquidado", False),
        ImportField("Monto_Pagado_Parcial", "Monto pagado parcial", False),
        ImportField("Monto_Condonado", "Monto condonado", False),
        ImportField("Monto_Gestionado", "Monto gestionado", False),
        ImportField("Cuota_Acordada", "Cuota acordada", False),
    ),
    "Colmena": (
        ImportField("Mandante", "Compañía", True, ("compania", "empresa")),
        ImportField("RUT_Deudor", "RUT deudor", True, ("rut", "rut afiliado")),
        ImportField("Nombre_Deudor", "Nombre", True, ("nombre", "nombre afiliado")),
        ImportField("Estado_Caso", "Estado deudor", True, ("estado", "estado caso")),
        ImportField("ID_Deuda", "ID deuda", False, ("expediente", "numero expediente")),
        ImportField("Email_Deudor", "Correo", False, ("email", "correo")),
        ImportField("Telefono1_Deudor", "Teléfono fijo", False, ("telefono 1", "telefono fijo")),
        ImportField("Telefono2_Deudor", "Teléfono móvil", False, ("telefono 2", "telefono movil")),
        ImportField("Direccion_Deudor", "Dirección", False, ("direccion",)),
        ImportField("Comuna_Deudor", "Comuna", False, ("comuna",)),
        ImportField("Ciudad_Deudor", "Ciudad", False, ("ciudad",)),
        ImportField("Fecha_Emision", "Fecha emisión", True, ("fecha emision",)),
        ImportField("Fecha_Prestacion", "Fecha prestación", True, ("fecha prestacion",)),
        ImportField("Prestador", "Prestador", False),
        ImportField("Monto_Total", "Monto total", False),
        ImportField("Monto_Cobrar", "Monto cobrar", True, ("monto a cobrar",)),
    ),
}


def normalize_header(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def apply_column_mapping(df: pd.DataFrame, payload: dict | None) -> pd.DataFrame:
    """Crea las columnas canónicas elegidas sin alterar las columnas originales."""
    if not payload or not isinstance(payload.get("columns"), dict):
        return df
    result = df.copy()
    available = {str(column): column for column in result.columns}
    for target, source in payload["columns"].items():
        source_text = str(source or "").strip()
        if source_text and source_text in available:
            result[str(target)] = result[available[source_text]]
        else:
            result[str(target)] = ""
    return result


class ImportColumnMappingDialog(QDialog):
    def __init__(self, excel_path: str, empresa: str, parent=None):
        super().__init__(parent)
        self.excel_path = excel_path
        self.empresa = empresa
        self.fields = IMPORT_FIELDS.get(empresa, COMMON_SUMMARY_FIELDS)
        self._headers_by_sheet = self._read_headers()
        self._combos: dict[str, QComboBox] = {}

        self.setWindowTitle("Asociar columnas del archivo Excel")
        self.setMinimumSize(760, 620)
        root = QVBoxLayout(self)
        intro = QLabel(
            f"Asocia las columnas del archivo con los datos de {empresa}. "
            "Las coincidencias conocidas se seleccionaron automáticamente."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Hoja del archivo:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.addItems(list(self._headers_by_sheet))
        sheet_row.addWidget(self.sheet_combo, 1)
        root.addLayout(sheet_row)

        note = QLabel("* Campo obligatorio. Los campos opcionales sin asociación se importarán como N/A.")
        note.setStyleSheet("color: #5f6b7a;")
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        frame = QFrame()
        self.form = QFormLayout(frame)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(frame)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continuar con la vista previa")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        best_sheet = self._best_sheet()
        if best_sheet:
            self.sheet_combo.setCurrentText(best_sheet)
        self.sheet_combo.currentTextChanged.connect(self._build_rows)
        self._build_rows(self.sheet_combo.currentText())

    def _read_headers(self) -> dict[str, list[str]]:
        try:
            xls = pd.ExcelFile(self.excel_path)
            output: dict[str, list[str]] = {}
            for sheet in xls.sheet_names:
                header_df = pd.read_excel(self.excel_path, sheet_name=sheet, nrows=0)
                output[str(sheet)] = [str(column).strip() for column in header_df.columns]
            if not output:
                raise ValueError("El archivo no contiene hojas.")
            return output
        except Exception as exc:
            raise ValueError(f"No se pudieron leer los títulos de la primera fila: {exc}") from exc

    def _match_header(self, field: ImportField, headers: list[str]) -> str:
        normalized = {normalize_header(header): header for header in headers}
        candidates = (field.key, field.label, *field.aliases)
        for candidate in candidates:
            match = normalized.get(normalize_header(candidate))
            if match:
                return match
        return ""

    def _best_sheet(self) -> str:
        required = [field for field in self.fields if field.required]
        best_name = ""
        best_score = -1
        for sheet, headers in self._headers_by_sheet.items():
            score = sum(bool(self._match_header(field, headers)) for field in required)
            if score > best_score:
                best_name, best_score = sheet, score
        return best_name

    def _clear_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._combos.clear()

    def _build_rows(self, sheet: str) -> None:
        self._clear_form()
        headers = self._headers_by_sheet.get(sheet, [])
        for field in self.fields:
            label = QLabel(f"{field.label}{' *' if field.required else ''}")
            combo = QComboBox()
            combo.addItem(NA_TEXT, "")
            for header in headers:
                combo.addItem(header, header)
            match = self._match_header(field, headers)
            if match:
                combo.setCurrentIndex(combo.findData(match))
            combo.currentIndexChanged.connect(lambda _index, c=combo: self._update_combo_style(c))
            self._update_combo_style(combo)
            self.form.addRow(label, combo)
            self._combos[field.key] = combo

    @staticmethod
    def _update_combo_style(combo: QComboBox) -> None:
        if combo.currentData():
            combo.setStyleSheet("")
        else:
            combo.setStyleSheet("QComboBox { color: #9a5b00; background: #fff4d6; }")

    def _validate_and_accept(self) -> None:
        missing = [field.label for field in self.fields if field.required and not self._combos[field.key].currentData()]
        if missing:
            QMessageBox.warning(
                self,
                "Faltan asociaciones obligatorias",
                "Debes asociar estas columnas antes de continuar:\n\n• " + "\n• ".join(missing),
            )
            return
        self.accept()

    def mapping_payload(self) -> dict:
        return {
            "sheet_name": self.sheet_combo.currentText(),
            "columns": {key: str(combo.currentData() or "") for key, combo in self._combos.items()},
        }

