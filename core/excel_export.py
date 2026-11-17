from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from core.date_format import (
    EXCEL_FMT_FECHA,
    EXCEL_FMT_FECHA_HORA,
    fmt_periodo,
    parse_fecha,
    parse_periodo,
    tiene_hora,
)


HEADER_FILL = PatternFill(fill_type="solid", fgColor="1D4ED8")
HEADER_FONT = Font(color="FFFFFF", bold=True)
SHEET_FREEZE = "A2"
DEFAULT_DATE_FORMAT = EXCEL_FMT_FECHA
DEFAULT_DATETIME_FORMAT = EXCEL_FMT_FECHA_HORA
DEFAULT_CURRENCY_FORMAT = '"$"#,##0'

# Nombres tecnicos que pueden llegar desde la API y se muestran traducidos.
HEADER_ALIASES = {
    "derivation_due_at": "Fecha vencimiento derivación",
    "derivation_completed_at": "Fecha cierre derivación",
}

_DATE_NAME_KEYS = ("fecha", "vence", "vencimiento", "inicio", "término", "termino")
_PERIOD_NAME_KEYS = ("periodo", "período", "emision", "emisión")
_SNIFF_SAMPLE = 50
_SNIFF_RATIO = 0.8


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if value is pd.NaT:
        return True
    return isinstance(value, str) and not value.strip()


def _sample(values: pd.Series) -> list:
    out = []
    for v in values:
        if _is_blank(v):
            continue
        out.append(v)
        if len(out) >= _SNIFF_SAMPLE:
            break
    return out


def _ratio(sample: list, parser) -> float:
    if not sample:
        return 0.0
    return sum(1 for v in sample if not pd.isna(parser(v))) / len(sample)


def _looks_like_date_column(name: str, values: pd.Series | None = None) -> bool:
    txt = str(name or "").strip().lower()
    if values is not None and pd.api.types.is_datetime64_any_dtype(values):
        return True
    by_name = any(k in txt for k in _DATE_NAME_KEYS) or txt.endswith("_at")
    if values is None:
        return by_name
    sample = _sample(values)
    if not sample:
        return by_name
    # Con nombre de fecha basta la mayoria; sin el, los valores deben ser casi todos fechas
    # (cubre columnas de archivos externos como "Emision" leidas como texto ISO).
    return _ratio(sample, _parse_date_value) >= (0.5 if by_name else _SNIFF_RATIO)


def _looks_like_period_column(name: str, values: pd.Series) -> bool:
    txt = str(name or "").strip().lower()
    if not any(k in txt for k in _PERIOD_NAME_KEYS):
        return False
    return _ratio(_sample(values), parse_periodo) >= _SNIFF_RATIO


def _looks_like_currency_column(name: str) -> bool:
    txt = str(name or "").strip().lower()
    keys = ("monto", "saldo", "copago", "pago", "total pagos")
    return any(k in txt for k in keys)


def _parse_currency_value(value):
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    txt = str(value).strip().replace("$", "").replace(" ", "")
    if not txt:
        return None

    # Evita tratar fechas como moneda (ej: 17-11-2025).
    if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", txt):
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?", txt):
        return None

    try:
        if re.fullmatch(r"-?\d+", txt):
            return float(txt)

        if "," in txt and "." in txt:
            if txt.rfind(",") > txt.rfind("."):
                txt = txt.replace(".", "").replace(",", ".")
            else:
                txt = txt.replace(",", "")
            return float(txt)

        if txt.count(".") > 1:
            return float(txt.replace(".", ""))

        if txt.count(".") == 1:
            left, right = txt.split(".", 1)
            if len(right) == 3 and left.replace("-", "").isdigit():
                return float(f"{left}{right}")
            return float(txt)

        if txt.count(",") == 1:
            left, right = txt.split(",", 1)
            if len(right) == 3 and left.replace("-", "").isdigit():
                return float(f"{left}{right}")
            return float(txt.replace(",", "."))

        return float(txt)
    except Exception:
        return None


def _parse_date_value(value):
    if value is None or isinstance(value, bool):
        return pd.NaT
    return parse_fecha(value)


def _to_excel_date(value):
    """Fecha como Timestamp; si no se reconoce se conserva el valor original."""
    if _is_blank(value):
        return None
    ts = _parse_date_value(value)
    return value if pd.isna(ts) else ts


def _to_excel_currency(value):
    """Monto como numero; textos como "Sí"/"No" se conservan en vez de vaciarse."""
    if _is_blank(value):
        return None
    parsed = _parse_currency_value(value)
    return value if parsed is None else parsed


def _classify_columns(df: pd.DataFrame) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for col_name in df.columns:
        values = df[col_name]
        if _looks_like_date_column(col_name, values):
            kinds[col_name] = "date"
        elif _looks_like_period_column(col_name, values):
            kinds[col_name] = "period"
        elif _looks_like_currency_column(col_name):
            kinds[col_name] = "currency"
    return kinds


def _normalize_excel_df(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    out = df.copy() if df is not None else pd.DataFrame()
    out = out.rename(columns={k: v for k, v in HEADER_ALIASES.items() if k in out.columns})
    kinds = _classify_columns(out)

    for col_name, kind in list(kinds.items()):
        if kind == "date":
            converted = out[col_name].apply(_to_excel_date).astype(object)
            with_time = any(isinstance(v, pd.Timestamp) and tiene_hora(v) for v in converted)
            out[col_name] = converted
            kinds[col_name] = "datetime" if with_time else "date"
        elif kind == "period":
            out[col_name] = out[col_name].apply(fmt_periodo)
        elif kind == "currency":
            out[col_name] = out[col_name].apply(_to_excel_currency).astype(object)

    return out, kinds


def _autosize_worksheet(ws) -> None:
    for column_cells in ws.columns:
        max_length = 0
        col_idx = column_cells[0].column
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_length + 2, 12), 40)


_NUMBER_FORMATS = {
    "date": DEFAULT_DATE_FORMAT,
    "datetime": DEFAULT_DATETIME_FORMAT,
    "currency": DEFAULT_CURRENCY_FORMAT,
}


def _style_worksheet(ws, df: pd.DataFrame, kinds: dict[str, str] | None = None) -> None:
    ws.freeze_panes = SHEET_FREEZE
    ws.auto_filter.ref = ws.dimensions

    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    if kinds is None:
        kinds = _classify_columns(df)
    for idx, col_name in enumerate(df.columns, start=1):
        number_format = _NUMBER_FORMATS.get(kinds.get(col_name, ""))
        if not number_format:
            continue
        for row in range(2, ws.max_row + 1):
            ws.cell(row=row, column=idx).number_format = number_format

    _autosize_worksheet(ws)


def write_excel_report(path: str, sheets: dict[str, pd.DataFrame]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_df, kinds = _normalize_excel_df(df)
            safe_df.to_excel(writer, sheet_name=sheet_name, index=False)
            _style_worksheet(writer.book[sheet_name], safe_df, kinds)
