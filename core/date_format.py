"""Formato de fechas para presentacion (pantallas, reportes y correos).

El almacenamiento interno (SQLite, API) sigue en ISO / AAAAMM; estas funciones
solo convierten al formato visible DD/MM/AAAA, DD/MM/AAAA HH:MM y MM/AAAA.
"""
from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

FMT_FECHA = "%d/%m/%Y"
FMT_FECHA_HORA = "%d/%m/%Y %H:%M"
FMT_PERIODO = "%m/%Y"

EXCEL_FMT_FECHA = "DD/MM/YYYY"
EXCEL_FMT_FECHA_HORA = "DD/MM/YYYY HH:MM"

_VACIOS = {"", "nan", "nat", "none", "null", "—", "-"}

_RE_ISO = re.compile(
    r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?$"
)
_RE_DMY = re.compile(
    r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$"
)
_RE_PERIODO = re.compile(r"^(\d{4})(\d{2})(?:\.0+)?$")
_RE_PERIODO_MY = re.compile(r"^(\d{1,2})/(\d{4})$")


def _es_vacio(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in _VACIOS


def _build(y, m, d, hh=None, mi=None, ss=None) -> pd.Timestamp:
    try:
        return pd.Timestamp(
            int(y), int(m), int(d), int(hh or 0), int(mi or 0), int(ss or 0)
        )
    except (ValueError, OverflowError):
        return pd.NaT


def parse_fecha(value: object) -> pd.Timestamp:
    """Interpreta una fecha en cualquiera de los formatos usados por la app.

    Acepta datetime/date/Timestamp, ISO (con o sin 'T', microsegundos o zona),
    AAAA/MM/DD, DD/MM/AAAA y DD-MM-AAAA (con hora opcional). Nunca interpreta
    05/03/2025 como 3 de mayo. Devuelve NaT si no se puede interpretar.
    """
    if _es_vacio(value):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value.tz_localize(None) if value.tzinfo else value
    if isinstance(value, datetime):
        return pd.Timestamp(value.replace(tzinfo=None))
    if isinstance(value, date):
        return pd.Timestamp(value.year, value.month, value.day)

    texto = str(value).strip()
    m = _RE_ISO.match(texto)
    if m:
        return _build(*m.groups())
    m = _RE_DMY.match(texto)
    if m:
        d, mo, y, hh, mi, ss = m.groups()
        return _build(y, mo, d, hh, mi, ss)
    return pd.NaT


def parse_periodo(value: object) -> pd.Timestamp:
    """Interpreta un periodo AAAAMM o MM/AAAA (devuelve el dia 1 del mes)."""
    if _es_vacio(value):
        return pd.NaT
    texto = str(value).strip()
    m = _RE_PERIODO.match(texto)
    if m:
        return _build(m.group(1), m.group(2), 1)
    m = _RE_PERIODO_MY.match(texto)
    if m:
        return _build(m.group(2), m.group(1), 1)
    return pd.NaT


def tiene_hora(ts: pd.Timestamp) -> bool:
    return not pd.isna(ts) and (ts.hour, ts.minute, ts.second) != (0, 0, 0)


def fmt_fecha(value: object, vacio: str = "") -> str:
    """DD/MM/AAAA. Si no se reconoce la fecha devuelve el texto original."""
    if _es_vacio(value):
        return vacio
    ts = parse_fecha(value)
    if pd.isna(ts):
        return str(value).strip()
    return ts.strftime(FMT_FECHA)


def fmt_fecha_hora(value: object, vacio: str = "") -> str:
    """DD/MM/AAAA HH:MM (o solo DD/MM/AAAA si la hora es 00:00)."""
    if _es_vacio(value):
        return vacio
    ts = parse_fecha(value)
    if pd.isna(ts):
        return str(value).strip()
    return ts.strftime(FMT_FECHA_HORA if tiene_hora(ts) else FMT_FECHA)


def fmt_periodo(value: object, vacio: str = "") -> str:
    """AAAAMM -> MM/AAAA. Si no es un periodo devuelve el texto original."""
    if _es_vacio(value):
        return vacio
    ts = parse_periodo(value)
    if pd.isna(ts):
        return str(value).strip()
    return ts.strftime(FMT_PERIODO)
