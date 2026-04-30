import sys
from pathlib import Path

import pandas as pd
import pytest

from deudores.database import _build_merge_key_detalle

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_cart56_local_detail_key_includes_mto_pagar():
    df = pd.DataFrame(
        {
            "Rut_Afiliado": ["76066341", "76066341"],
            "Nro_Expediente": ["3-127378643", "3-127378643"],
            "Fecha_Emision": ["06/02/2026", "06/02/2026"],
            "Copago": ["264.059", "349.614"],
            "Cart56_Mto_Pagar": ["264.059", "349.614"],
        }
    )

    keys = _build_merge_key_detalle(df)

    assert keys.nunique() == 2


def test_cart56_local_detail_key_uses_copago_as_legacy_fallback():
    df = pd.DataFrame(
        {
            "Rut_Afiliado": ["76066341", "76066341"],
            "Nro_Expediente": ["3-127378643", "3-127378643"],
            "Fecha_Emision": ["06/02/2026", "06/02/2026"],
            "Copago": ["264.059", "349.614"],
            "Cart56_Mto_Pagar": ["", ""],
        }
    )

    keys = _build_merge_key_detalle(df)

    assert keys.tolist() == [
        "76066341||3-127378643||264059",
        "76066341||3-127378643||349614",
    ]


def test_backend_cart56_identity_key_includes_mto_pagar():
    pytest.importorskip("sqlalchemy")
    from app.models.deudor import DeudorDetalle
    from app.services.deudor_import_service import _detalle_identity_key

    base = {
        "empresa": "Cart-56",
        "rut_afiliado": "76066341",
        "dv": "7",
        "rut_completo": "76066341-7",
        "nombre_afiliado": "Empresa",
        "nro_expediente": "3-127378643",
        "fecha_emision": "06/02/2026",
    }
    row_a = DeudorDetalle(**base, copago=264059, saldo_actual=264059, cart56_mto_pagar=264059)
    row_b = DeudorDetalle(**base, copago=349614, saldo_actual=349614, cart56_mto_pagar=349614)

    assert _detalle_identity_key(row_a) != _detalle_identity_key(row_b)


def test_backend_cart56_identity_key_uses_copago_as_legacy_fallback():
    pytest.importorskip("sqlalchemy")
    from app.models.deudor import DeudorDetalle
    from app.services.deudor_import_service import _detalle_identity_key

    base = {
        "empresa": "Cart-56",
        "rut_afiliado": "76066341",
        "dv": "7",
        "rut_completo": "76066341-7",
        "nombre_afiliado": "Empresa",
        "nro_expediente": "3-127378643",
        "fecha_emision": "06/02/2026",
        "cart56_mto_pagar": 0,
    }
    row_a = DeudorDetalle(**base, copago=264059, saldo_actual=264059)
    row_b = DeudorDetalle(**base, copago=349614, saldo_actual=349614)

    assert _detalle_identity_key(row_a) != _detalle_identity_key(row_b)
