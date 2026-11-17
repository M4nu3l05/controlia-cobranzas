from datetime import date, datetime

import pandas as pd
import pytest

from core.date_format import fmt_fecha, fmt_fecha_hora, fmt_periodo, parse_fecha


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2025-03-05", "05/03/2025"),
        ("2025/03/05", "05/03/2025"),
        ("2025-03-05 00:00:00", "05/03/2025"),
        ("2025-03-05T14:30:12.123456", "05/03/2025"),
        ("05/03/2025", "05/03/2025"),
        ("05-03-2025", "05/03/2025"),
        (date(2025, 3, 5), "05/03/2025"),
        (datetime(2025, 3, 5, 9, 0), "05/03/2025"),
        (pd.Timestamp("2025-03-05"), "05/03/2025"),
    ],
)
def test_fmt_fecha(value, expected):
    assert fmt_fecha(value) == expected


def test_dia_primero_nunca_se_invierte():
    ts = parse_fecha("05/03/2025")
    assert (ts.day, ts.month) == (5, 3)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-11-16T10:20:30.123456", "16/11/2026 10:20"),
        ("2026-11-16 10:20:30", "16/11/2026 10:20"),
        ("16/11/2026 08:05:00", "16/11/2026 08:05"),
        ("2026-11-16 00:00:00", "16/11/2026"),
        ("2026-11-16T10:20:30+00:00", "16/11/2026 10:20"),
    ],
)
def test_fmt_fecha_hora(value, expected):
    assert fmt_fecha_hora(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("202501", "01/2025"), (202512, "12/2025"), ("202501.0", "01/2025"), ("01/2025", "01/2025")],
)
def test_fmt_periodo(value, expected):
    assert fmt_periodo(value) == expected


@pytest.mark.parametrize("value", [None, "", "nan", "NaT", "None", float("nan")])
def test_vacios(value):
    assert fmt_fecha(value) == ""
    assert fmt_fecha(value, vacio="—") == "—"
    assert fmt_fecha_hora(value) == ""
    assert fmt_periodo(value) == ""


def test_texto_no_reconocido_se_conserva():
    assert fmt_fecha("sin fecha") == "sin fecha"
    assert fmt_fecha("2025-13-45") == "2025-13-45"
    assert fmt_periodo("Todos") == "Todos"
