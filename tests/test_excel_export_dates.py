from datetime import datetime

import pandas as pd
import pytest
from openpyxl import load_workbook

from core.excel_export import write_excel_report


def _sheet(tmp_path, frame):
    path = tmp_path / "reporte.xlsx"
    write_excel_report(str(path), {"Datos": frame})
    ws = load_workbook(path)["Datos"]
    headers = [c.value for c in ws[1]]
    return ws, headers


def _col(ws, headers, name):
    idx = headers.index(name) + 1
    return [ws.cell(row=r, column=idx) for r in range(2, ws.max_row + 1)]


def test_fechas_por_valor_periodos_y_textos(tmp_path):
    frame = pd.DataFrame(
        {
            # Columna de un archivo externo leida como texto (dtype=str), sin "fecha" en el nombre.
            "Emision": ["2025-03-05 00:00:00", "2025-04-10 00:00:00"],
            "derivation_due_at": ["2026-11-16T10:20:30.123456", ""],
            "Fecha_gestion": ["05/03/2025", "01/04/2025"],
            "Periodo": ["202501", "202412"],
            "Tiene pagos": ["Sí", "No"],
            "Saldo actual": ["1.500", "2000"],
            "Folio": ["F-1", "F-2"],
        }
    )
    ws, headers = _sheet(tmp_path, frame)

    emision = _col(ws, headers, "Emision")
    assert emision[0].value == datetime(2025, 3, 5)
    assert emision[0].number_format == "DD/MM/YYYY"

    assert "derivation_due_at" not in headers
    vence = _col(ws, headers, "Fecha vencimiento derivación")
    assert vence[0].value == datetime(2026, 11, 16, 10, 20, 30)
    assert vence[0].number_format == "DD/MM/YYYY HH:MM"
    assert vence[1].value is None

    gestion = _col(ws, headers, "Fecha_gestion")
    assert gestion[0].value == datetime(2025, 3, 5)  # dia primero, nunca 3 de mayo

    assert [c.value for c in _col(ws, headers, "Periodo")] == ["01/2025", "12/2024"]
    assert [c.value for c in _col(ws, headers, "Tiene pagos")] == ["Sí", "No"]
    assert [c.value for c in _col(ws, headers, "Saldo actual")] == [1500, 2000]
    assert [c.value for c in _col(ws, headers, "Folio")] == ["F-1", "F-2"]


def test_columna_fecha_con_texto_no_reconocido_se_conserva(tmp_path):
    frame = pd.DataFrame({"Fecha": ["05/03/2025", "pendiente", "06/03/2025"]})
    ws, headers = _sheet(tmp_path, frame)
    valores = [c.value for c in _col(ws, headers, "Fecha")]
    assert valores == [datetime(2025, 3, 5), "pendiente", datetime(2025, 3, 6)]


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("1.500", 1500.0),
        ("$ 1.500", 1500.0),
        ("-1.500", -1500.0),
        ("1.500.000", 1500000.0),
        ("2000", 2000.0),
        ("1500.5", 1500.5),
        ("1500.25", 1500.25),
        ("1.500,50", 1500.5),
        ("1,500.50", 1500.5),
        ("1,500", 1500.0),
        ("12,5", 12.5),
    ],
)
def test_montos_con_separador_de_miles(texto, esperado):
    from core.excel_export import _parse_currency_value

    assert _parse_currency_value(texto) == esperado
