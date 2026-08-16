from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html import escape

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


NA_TEXT = "N/A — sin columna asignada"
SIN_HOJA_TEXT = "— Sin hoja de detalle —"

HOJA_PRINCIPAL = "principal"
HOJA_DETALLE_KEY = "detalle"


@dataclass(frozen=True)
class ImportField:
    """Campo visible en 'Detalle del deudor' que se puede asociar a una columna del Excel.

    `key` es el nombre de columna que crea la asociación; `derived` describe el
    origen cuando el valor lo calcula la aplicación y no se puede asociar.
    """

    key: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()
    derived: str = ""


@dataclass(frozen=True)
class ImportSection:
    title: str
    fields: tuple[ImportField, ...]
    hint: str = ""


@dataclass(frozen=True)
class ImportSheet:
    key: str
    title: str
    sections: tuple[ImportSection, ...]
    preferred_sheets: tuple[str, ...] = ()
    optional: bool = False


# ================================================================
#  Catálogo de campos por compañía.
#  Las etiquetas replican las que muestra "Detalle del deudor"
#  (deudores/schema_detalle.py) para que el supervisor asocie cada
#  dato de su archivo con el lugar donde se va a mostrar.
# ================================================================

HINT_CLIENTE = "Bloque 'Datos del cliente' del Detalle del deudor."
HINT_FINANCIERO = "Tarjetas del bloque 'Resumen financiero'."
HINT_DEUDA = "Columnas de la tabla 'Detalle de deuda'."
HINT_SISTEMA = "Datos que la aplicación necesita para clasificar la carga."


_CONSALUD_RESUMEN = ImportSheet(
    key=HOJA_PRINCIPAL,
    title="Hoja de resumen (un registro por deudor)",
    preferred_sheets=("RESUMEN",),
    sections=(
        ImportSection(
            "Datos del cliente",
            (
                ImportField("Rut_Afiliado", "RUT", True, ("rut afiliado", "rut deudor", "rut")),
                ImportField("Dv", "DV", False, ("digito verificador", "dv rut")),
                ImportField("Nombre_Afiliado", "Nombre", True, ("nombre afiliado", "nombre deudor", "nombre")),
                ImportField("Estado_deudor", "Estado deudor", False, ("estado", "estado gestion", "estado caso")),
            ),
            HINT_CLIENTE,
        ),
        ImportSection(
            "Resumen financiero",
            (
                ImportField("Nro_Expediente", "N° Expediente", False, ("numero expediente", "expediente", "id deuda")),
                ImportField("MAX_Emision_ok", "Última Emisión", False, ("ultima emision", "max emision")),
                ImportField("MIN_Emision_ok", "Primera Emisión", False, ("primera emision", "min emision")),
                ImportField("Copago", "Copago ($)", False, ("monto cobrar", "monto")),
                ImportField("Total_Pagos", "Total Pagos ($)", False, ("total pagos", "pagos")),
                ImportField("Saldo_Actual", "Saldo Actual ($)", False, ("saldo actual", "saldo")),
            ),
            HINT_FINANCIERO,
        ),
    ),
)


_CONSALUD_DETALLE = ImportSheet(
    key=HOJA_DETALLE_KEY,
    title="Hoja de detalle (una fila por expediente)",
    preferred_sheets=("DETALLE",),
    optional=True,
    sections=(
        ImportSection(
            "Datos del cliente",
            (
                ImportField("Rut_Afiliado", "RUT", True, ("rut afiliado", "rut deudor", "rut")),
                ImportField("Dv", "DV", False, ("digito verificador", "dv rut")),
                ImportField("Nombre_Afiliado", "Nombre", False, ("nombre afiliado", "nombre deudor", "nombre")),
                ImportField("mail_afiliado", "Correo", False, ("mail afiliado", "email", "correo")),
                ImportField("BN", "Correo (Excel)", False, ("correo excel", "mail excel")),
                ImportField("telefono_fijo_afiliado", "Teléfono Fijo", False, ("telefono fijo", "fono", "telefono")),
                ImportField("telefono_movil_afiliado", "Teléfono Móvil", False, ("telefono movil", "celular", "movil")),
            ),
            HINT_CLIENTE,
        ),
        ImportSection(
            "Detalle de deuda",
            (
                ImportField("Nro_Expediente", "N° Expediente", True, ("numero expediente", "expediente")),
                ImportField("Nombre Afil", "Nombre Afil", False, ("nombre afiliado", "nom afil")),
                ImportField("RUT Afil", "RUT Afil", False, ("rut afiliado",)),
                ImportField("Fecha Pago", "Fecha Pago", False, ("fecha de pago", "fec pago")),
                ImportField("Fecha_Emision", "Fecha Emisión", False, ("fecha emision",)),
                ImportField("Copago", "Copago ($)", False, ("monto cobrar", "monto")),
                ImportField("Total_Pagos", "Total Pagos ($)", False, ("total pagos", "pagos")),
                ImportField("Saldo_Actual", "Saldo Actual ($)", False, ("saldo actual", "saldo")),
            ),
            HINT_DEUDA,
        ),
    ),
)


_CART56 = ImportSheet(
    key=HOJA_PRINCIPAL,
    title="Hoja de la nómina Cart-56",
    sections=(
        ImportSection(
            "Datos del cliente",
            (
                ImportField("RUT Emp", "RUT", True, ("rut empresa", "rut empleador")),
                ImportField("Empresa", "Nombre", False, ("nombre empresa", "razon social", "empleador")),
                ImportField("mail_afiliado", "Correo", False, ("mail emp", "email empresa", "correo empresa", "email", "correo")),
                ImportField("BN", "Correo (Excel)", False, ("correo excel", "mail excel")),
                ImportField("telefono_fijo_afiliado", "Teléfono Fijo", False, ("telefono fijo", "fono", "telefono empleador")),
                ImportField("telefono_movil_afiliado", "Teléfono Móvil", False, ("telefono movil", "celular", "movil", "telefono empleador")),
            ),
            HINT_CLIENTE,
        ),
        ImportSection(
            "Resumen financiero",
            (
                ImportField("Copago", "Copago ($)", derived="Suma de 'Mto Pagar'."),
                ImportField("Total_Pagos", "Total Pagos ($)", derived="Parte en 0 y crece con los pagos registrados."),
                ImportField("Saldo_Actual", "Saldo Actual ($)", derived="Copago menos los pagos registrados."),
            ),
            HINT_FINANCIERO,
        ),
        ImportSection(
            "Detalle de deuda",
            (
                ImportField("No Licencia", "No Licencia", True, ("folio liq", "numero licencia", "nro licencia", "n licencia")),
                ImportField("Nombre Afil", "Nombre Afil", False, ("nombre afiliado", "nom afil")),
                ImportField("RUT Afil", "RUT Afil", False, ("rut afiliado",)),
                ImportField("Fecha Pago", "Fecha Pago", False, ("fecha de pago", "fec pago")),
                ImportField("Fecha Recep", "Fecha Recep", False, ("fecha recepcion",)),
                ImportField("Fecha Recep ISA", "Fecha Recep ISA", False, ("fecha recepcion isa",)),
                ImportField("Dias Pagar", "Dias Pagar", False, ("dias pago", "dias de pagar")),
                ImportField("Mto Pagar", "Mto Pagar", True, ("monto pagar", "monto")),
                ImportField("__pagos__", "Pagos", derived="Se calcula con los pagos registrados en la gestión."),
                ImportField("__saldo__", "Saldo Actual", derived="Mto Pagar menos los pagos registrados."),
                ImportField("__correo_deuda__", "Correo", derived="Usa el correo asociado en 'Datos del cliente'."),
            ),
            HINT_DEUDA,
        ),
    ),
)


_CRUZ_BLANCA = ImportSheet(
    key=HOJA_PRINCIPAL,
    title="Hoja de la nómina Cruz Blanca",
    sections=(
        ImportSection(
            "Datos del cliente",
            (
                ImportField("RUT_Deudor", "RUT", True, ("rut", "rut afiliado")),
                ImportField("Nombre_Deudor", "Nombre", True, ("nombre", "nombre afiliado")),
                ImportField("Email_Deudor", "Correo", False, ("email", "correo")),
                ImportField("BN", "Correo (Excel)", False, ("correo excel", "mail excel")),
                ImportField("Telefono3_Deudor", "Teléfono Fijo", False, ("telefono 3", "telefono", "fono")),
                ImportField("__telefono_movil__", "Teléfono Móvil", derived="Usa el mismo teléfono asociado arriba."),
                ImportField("Direccion_Deudor", "Dirección", False, ("direccion",)),
                ImportField("Comuna_Deudor", "Comuna", False, ("comuna",)),
                ImportField("Ciudad_Deudor", "Ciudad", False, ("ciudad",)),
            ),
            HINT_CLIENTE,
        ),
        ImportSection(
            "Resumen financiero",
            (
                ImportField("Copago", "Copago ($)", derived="Suma de 'Monto_Cobrar'."),
                ImportField("Total_Pagos", "Total Pagos ($)", derived="Parte en 0 y crece con los pagos registrados."),
                ImportField("Saldo_Actual", "Saldo Actual ($)", derived="Copago menos los pagos registrados."),
            ),
            HINT_FINANCIERO,
        ),
        ImportSection(
            "Detalle de deuda",
            (
                ImportField("ID_Deuda", "No Licencia", False, ("id deuda", "expediente", "numero expediente")),
                ImportField("__nombre_afil__", "Nombre Afil", derived="Usa el nombre asociado en 'Datos del cliente'."),
                ImportField("__rut_afil__", "RUT Afil", derived="Usa el RUT asociado en 'Datos del cliente'."),
                ImportField("Fecha_Prestacion", "Fecha_Prestacion", False, ("fecha prestacion",)),
                ImportField("Fecha_Prestacion2", "Fecha_Prestacion2", False, ("fecha prestacion 2",)),
                ImportField("Prestador", "Prestador", False),
                ImportField("Monto_Total", "Mto Pagar", False, ("monto total",)),
                ImportField("Monto_Cobrar", "Monto_Cobrar", True, ("monto a cobrar",)),
                ImportField("Monto_Facturado", "Monto_Facturado", False),
                ImportField("Monto_Liquidado", "Monto_Liquidado", False),
                ImportField("Monto_Pagado_Parcial", "Monto_Pagado_Parcial", False),
                ImportField("Monto_Condonado", "Monto_Condonado", False),
                ImportField("Monto_Gestionado", "Monto_Gestionado", False),
                ImportField("Cuota_Acordada", "Cuota_Acordada", False),
                ImportField("__pagos__", "Pagos", derived="Se calcula con los pagos registrados en la gestión."),
                ImportField("__saldo__", "Saldo Actual", derived="Monto_Cobrar menos los pagos registrados."),
                ImportField("__correo_deuda__", "Correo", derived="Usa el correo asociado en 'Datos del cliente'."),
            ),
            HINT_DEUDA,
        ),
        ImportSection(
            "Datos de la carga",
            (
                ImportField("Mandante", "Compañía", True, ("compania", "empresa")),
                ImportField("Estado_Gestion", "Estado deudor", True, ("estado", "estado gestion")),
                ImportField("Fecha_Emision_Deuda", "Fecha emisión", True, ("fecha emision",)),
                ImportField("Fecha_Vencimiento_Deuda", "Fecha vencimiento", True, ("fecha vencimiento",)),
            ),
            HINT_SISTEMA,
        ),
    ),
)


_COLMENA = ImportSheet(
    key=HOJA_PRINCIPAL,
    title="Hoja de la nómina Colmena",
    sections=(
        ImportSection(
            "Datos del cliente",
            (
                ImportField("RUT_Deudor", "RUT", True, ("rut", "rut afiliado")),
                ImportField("Nombre_Deudor", "Nombre", True, ("nombre", "nombre afiliado")),
                ImportField("Email_Deudor", "Correo", False, ("email", "correo")),
                ImportField("BN", "Correo (Excel)", False, ("correo excel", "mail excel")),
                ImportField("Telefono1_Deudor", "Teléfono Fijo", False, ("telefono 1", "telefono fijo")),
                ImportField("Telefono2_Deudor", "Teléfono Móvil", False, ("telefono 2", "telefono movil", "celular")),
                ImportField("Direccion_Deudor", "Dirección", False, ("direccion",)),
                ImportField("Comuna_Deudor", "Comuna", False, ("comuna",)),
                ImportField("Ciudad_Deudor", "Ciudad", False, ("ciudad",)),
            ),
            HINT_CLIENTE,
        ),
        ImportSection(
            "Resumen financiero",
            (
                ImportField("Copago", "Copago ($)", derived="Suma de 'Monto_Cobrar'."),
                ImportField("Total_Pagos", "Total Pagos ($)", derived="Parte en 0 y crece con los pagos registrados."),
                ImportField("Saldo_Actual", "Saldo Actual ($)", derived="Copago menos los pagos registrados."),
            ),
            HINT_FINANCIERO,
        ),
        ImportSection(
            "Detalle de deuda",
            (
                ImportField("ID_Deuda", "No Licencia", False, ("id deuda", "expediente", "numero expediente")),
                ImportField("__nombre_afil__", "Nombre Afil", derived="Usa el nombre asociado en 'Datos del cliente'."),
                ImportField("__rut_afil__", "RUT Afil", derived="Usa el RUT asociado en 'Datos del cliente'."),
                ImportField("__fecha_prestacion__", "Fecha_Prestacion", derived="Usa la fecha de emisión de la carga."),
                ImportField("Fecha_Prestacion", "Fecha_Prestacion2", True, ("fecha prestacion",)),
                ImportField("Prestador", "Prestador", False),
                ImportField("Monto_Total", "Mto Pagar", False, ("monto total",)),
                ImportField("Monto_Cobrar", "Monto_Cobrar", True, ("monto a cobrar",)),
                ImportField("__facturado__", "Monto_Facturado", derived="No aplica en Colmena."),
                ImportField("__liquidado__", "Monto_Liquidado", derived="No aplica en Colmena."),
                ImportField("__pagado_parcial__", "Monto_Pagado_Parcial", derived="No aplica en Colmena."),
                ImportField("__condonado__", "Monto_Condonado", derived="No aplica en Colmena."),
                ImportField("__gestionado__", "Monto_Gestionado", derived="No aplica en Colmena."),
                ImportField("__cuota__", "Cuota_Acordada", derived="No aplica en Colmena."),
                ImportField("__pagos__", "Pagos", derived="Se calcula con los pagos registrados en la gestión."),
                ImportField("__saldo__", "Saldo Actual", derived="Monto_Cobrar menos los pagos registrados."),
                ImportField("__correo_deuda__", "Correo", derived="Usa el correo asociado en 'Datos del cliente'."),
            ),
            HINT_DEUDA,
        ),
        ImportSection(
            "Datos de la carga",
            (
                ImportField("Mandante", "Compañía", True, ("compania", "empresa")),
                ImportField("Estado_Caso", "Estado deudor", True, ("estado", "estado caso")),
                ImportField("Fecha_Emision", "Fecha emisión", True, ("fecha emision",)),
            ),
            HINT_SISTEMA,
        ),
    ),
)


IMPORT_LAYOUT: dict[str, tuple[ImportSheet, ...]] = {
    "consalud": (_CONSALUD_RESUMEN, _CONSALUD_DETALLE),
    "cart56": (_CART56,),
    "cruzblanca": (_CRUZ_BLANCA,),
    "colmena": (_COLMENA,),
}


def normalize_header(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def sheets_for_empresa(empresa: str) -> tuple[ImportSheet, ...]:
    return IMPORT_LAYOUT.get(normalize_header(empresa), IMPORT_LAYOUT["consalud"])


def assignable_fields(sheet: ImportSheet) -> tuple[ImportField, ...]:
    return tuple(
        field
        for section in sheet.sections
        for field in section.fields
        if not field.derived
    )


def fields_for_empresa(empresa: str) -> tuple[ImportField, ...]:
    return assignable_fields(sheets_for_empresa(empresa)[0])


COMMON_SUMMARY_FIELDS: tuple[ImportField, ...] = assignable_fields(_CONSALUD_RESUMEN)

IMPORT_FIELDS: dict[str, tuple[ImportField, ...]] = {
    "Consalud": COMMON_SUMMARY_FIELDS,
    "Cart-56": assignable_fields(_CART56),
    "Cruz Blanca": assignable_fields(_CRUZ_BLANCA),
    "Colmena": assignable_fields(_COLMENA),
}


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


def detail_mapping_payload(payload: dict | None) -> dict | None:
    """Devuelve la asociación de la hoja de detalle en el formato de apply_column_mapping."""
    if not payload:
        return None
    columns = payload.get("detail_columns")
    if not isinstance(columns, dict) or not columns:
        return None
    return {"columns": columns}


class ImportColumnMappingDialog(QDialog):
    def __init__(self, excel_path: str, empresa: str, parent=None):
        super().__init__(parent)
        self.excel_path = excel_path
        self.empresa = empresa
        self.sheets = sheets_for_empresa(empresa)
        self.fields = assignable_fields(self.sheets[0])
        self._headers_by_sheet = self._read_headers()
        self._combos: dict[str, dict[str, QComboBox]] = {}
        self._sheet_combos: dict[str, QComboBox] = {}
        self._bodies: dict[str, QVBoxLayout] = {}

        self.setWindowTitle("Asociar columnas del archivo Excel")
        self.setMinimumSize(860, 660)
        root = QVBoxLayout(self)

        intro = QLabel(
            f"Asocia los títulos de la primera fila del archivo con los datos que {empresa} "
            "muestra en «Detalle del deudor». Las coincidencias conocidas se seleccionaron "
            "automáticamente y puedes cambiarlas."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        note = QLabel(
            "* Campo obligatorio. Los campos opcionales sin asociación se importarán como N/A. "
            "El texto en gris es el nombre interno del dato, el que aparece en los mensajes del sistema."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5f6b7a;")
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._container_layout = QVBoxLayout(container)
        self._container_layout.setSpacing(12)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        for sheet in self.sheets:
            self._container_layout.addWidget(self._build_sheet_group(sheet))
        self._container_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continuar con la vista previa")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------
    #  Lectura del archivo
    # ------------------------------------------------------------

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

    def _best_sheet(self, sheet: ImportSheet) -> str:
        # Las hojas opcionales no reutilizan una hoja ya elegida para otro bloque.
        ocupadas = {
            str(combo.currentData() or "")
            for combo in self._sheet_combos.values()
        } if sheet.optional else set()

        for preferred in sheet.preferred_sheets:
            for name in self._headers_by_sheet:
                if name not in ocupadas and normalize_header(name) == normalize_header(preferred):
                    return name

        required = [field for field in assignable_fields(sheet) if field.required]
        best_name = ""
        best_score = -1
        for name, headers in self._headers_by_sheet.items():
            if name in ocupadas:
                continue
            score = sum(bool(self._match_header(field, headers)) for field in required)
            if score > best_score:
                best_name, best_score = name, score

        # En una hoja opcional solo proponemos la asociación si calzan todos los
        # campos obligatorios; si no, el supervisor la elige a mano.
        if sheet.optional and best_score < len(required):
            return ""
        return best_name

    # ------------------------------------------------------------
    #  Construcción de la interfaz
    # ------------------------------------------------------------

    def _build_sheet_group(self, sheet: ImportSheet) -> QGroupBox:
        group = QGroupBox(sheet.title)
        layout = QVBoxLayout(group)

        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Hoja del archivo:"))
        combo = QComboBox()
        if sheet.optional:
            combo.addItem(SIN_HOJA_TEXT, "")
        for name in self._headers_by_sheet:
            combo.addItem(name, name)
        sheet_row.addWidget(combo, 1)
        layout.addLayout(sheet_row)

        body = QVBoxLayout()
        body.setSpacing(6)
        layout.addLayout(body)

        self._sheet_combos[sheet.key] = combo
        self._bodies[sheet.key] = body
        self._combos[sheet.key] = {}

        best = self._best_sheet(sheet)
        index = combo.findData(best) if best else (0 if sheet.optional else -1)
        combo.setCurrentIndex(max(index, 0))
        combo.currentIndexChanged.connect(lambda _index, s=sheet: self._build_rows(s))
        self._build_rows(sheet)
        return group

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                continue
            child = item.layout()
            if child is not None:
                self._clear_layout(child)
                child.setParent(None)

    def _build_rows(self, sheet: ImportSheet) -> None:
        body = self._bodies[sheet.key]
        self._clear_layout(body)
        self._combos[sheet.key] = {}

        sheet_name = str(self._sheet_combos[sheet.key].currentData() or "")
        if not sheet_name:
            aviso = QLabel(
                "No se asociará ninguna hoja de detalle: el detalle del deudor quedará "
                "solo con los datos del resumen."
            )
            aviso.setWordWrap(True)
            aviso.setStyleSheet("color: #9a5b00;")
            body.addWidget(aviso)
            return

        headers = self._headers_by_sheet.get(sheet_name, [])
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        body.addLayout(form)

        for section in sheet.sections:
            form.addRow(self._build_section_title(section))
            for field in section.fields:
                label = QLabel(self._field_label_html(field))
                label.setTextFormat(Qt.TextFormat.RichText)
                if field.derived:
                    valor = QLabel(f"Calculado por la aplicación — {field.derived}")
                    valor.setWordWrap(True)
                    valor.setStyleSheet("color: #5f6b7a; font-style: italic;")
                    form.addRow(label, valor)
                    continue

                combo = QComboBox()
                combo.addItem(NA_TEXT, "")
                for header in headers:
                    combo.addItem(header, header)
                match = self._match_header(field, headers)
                if match:
                    combo.setCurrentIndex(combo.findData(match))
                combo.currentIndexChanged.connect(lambda _index, c=combo: self._update_combo_style(c))
                self._update_combo_style(combo)
                form.addRow(label, combo)
                self._combos[sheet.key][field.key] = combo
            body.addLayout(form)

    @staticmethod
    def _field_label_html(field: ImportField) -> str:
        """Etiqueta visible + nombre interno de la columna.

        El servidor y los mensajes de error hablan en nombres internos
        (Rut_Afiliado, Monto_Cobrar…), así que se muestran junto a la etiqueta
        para poder relacionar un error con su desplegable.
        """
        partes = [escape(field.label)]
        if not field.derived and normalize_header(field.key) != normalize_header(field.label):
            partes.append(f'<span style="color:#5f6b7a;">— {escape(field.key)}</span>')
        if field.required:
            partes.append('<b>*</b>')
        return " ".join(partes)

    @staticmethod
    def _build_section_title(section: ImportSection) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(2)

        titulo = QLabel(section.title)
        titulo.setStyleSheet("font-weight: bold;")
        layout.addWidget(titulo)

        if section.hint:
            hint = QLabel(section.hint)
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #5f6b7a;")
            layout.addWidget(hint)

        separador = QFrame()
        separador.setFrameShape(QFrame.Shape.HLine)
        separador.setStyleSheet("color: #e2e8f0;")
        layout.addWidget(separador)
        return holder

    @staticmethod
    def _update_combo_style(combo: QComboBox) -> None:
        if combo.currentData():
            combo.setStyleSheet("")
        else:
            combo.setStyleSheet("QComboBox { color: #9a5b00; background: #fff4d6; }")

    # ------------------------------------------------------------
    #  Validación y resultado
    # ------------------------------------------------------------

    def _validate_and_accept(self) -> None:
        faltantes: list[str] = []
        for sheet in self.sheets:
            if not str(self._sheet_combos[sheet.key].currentData() or ""):
                continue
            combos = self._combos.get(sheet.key, {})
            for field in assignable_fields(sheet):
                if not field.required:
                    continue
                combo = combos.get(field.key)
                if combo is None or not combo.currentData():
                    faltantes.append(f"{sheet.title} → {field.label} ({field.key})")

        if faltantes:
            QMessageBox.warning(
                self,
                "Faltan asociaciones obligatorias",
                "Debes asociar estas columnas antes de continuar:\n\n• " + "\n• ".join(faltantes),
            )
            return
        self.accept()

    def _columns_payload(self, sheet_key: str) -> dict[str, str]:
        return {
            key: str(combo.currentData() or "")
            for key, combo in self._combos.get(sheet_key, {}).items()
        }

    def mapping_payload(self) -> dict:
        payload = {
            "sheet_name": str(self._sheet_combos[HOJA_PRINCIPAL].currentData() or ""),
            "columns": self._columns_payload(HOJA_PRINCIPAL),
        }
        if HOJA_DETALLE_KEY in self._sheet_combos:
            payload["detail_sheet_name"] = str(self._sheet_combos[HOJA_DETALLE_KEY].currentData() or "")
            payload["detail_columns"] = self._columns_payload(HOJA_DETALLE_KEY)
        return payload
