import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.db.base  # noqa: F401
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.services.deudor_import_service import (
    _build_detalle_objects,
    _build_resumen_objects,
)


def _column_length(model, name: str) -> int:
    return int(model.__table__.columns[name].type.length)


def test_textos_largos_se_recortan_al_largo_de_columna():
    row = {
        "Rut_Afiliado": "11111111",
        "Dv": "1",
        "Nombre_Afiliado": "N" * 400,
        "Prestador": "P" * 600,
        "Comuna_Deudor": "C" * 300,
        "telefono_movil_afiliado": "9" * 150,
        "Nro_Expediente": "EXP-" + "1" * 200,
        "Copago": "1000",
    }
    df = pd.DataFrame([row])

    detalle = _build_detalle_objects(df, "Consalud", "base_ficticia.xlsx", "202610")[0]
    resumen = _build_resumen_objects(df, "Consalud", "base_ficticia.xlsx", "202610")[0]

    assert len(detalle.prestador) == _column_length(DeudorDetalle, "prestador")
    assert len(detalle.comuna_deudor) == _column_length(DeudorDetalle, "comuna_deudor")
    assert len(detalle.telefono_movil_afiliado) == _column_length(DeudorDetalle, "telefono_movil_afiliado")
    assert len(detalle.nro_expediente) == _column_length(DeudorDetalle, "nro_expediente")
    assert len(resumen.nombre_afiliado) == _column_length(DeudorResumen, "nombre_afiliado")
    assert len(resumen.nro_expediente) == _column_length(DeudorResumen, "nro_expediente")
    # Los textos dentro del límite y las columnas Text no se alteran.
    assert detalle.rut_afiliado == "11111111"
    assert detalle.source_file == "base_ficticia.xlsx"


def test_error_500_muestra_detalle_del_backend():
    from auth.auth_service import _friendly_http_status_error

    msg = _friendly_http_status_error(500, "No se pudo importar la base de deudores: ValueError: X")
    assert "No se pudo importar la base de deudores" in msg

    assert "no respondió" in _friendly_http_status_error(502)
    assert "error interno" in _friendly_http_status_error(500)
