from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from deudores.import_mapping_dialog import (
    apply_column_mapping,
    assignable_fields,
    detail_mapping_payload,
    sheets_for_empresa,
)
from deudores.schema import (
    normalizar_rut_detalle,
    transformar_cart56_raw,
    transformar_isapre_raw,
)
from deudores.schema_detalle import (
    CAMPOS_CLIENTE_BASE,
    COLUMNAS_DETALLE_DEUDA_BASE,
    extraer_detalle_deudor,
)


def _labels(empresa: str) -> set[str]:
    return {
        field.label
        for sheet in sheets_for_empresa(empresa)
        for section in sheet.sections
        for field in section.fields
    }


@pytest.mark.parametrize("empresa", ["Consalud", "Cart-56", "Cruz Blanca", "Colmena"])
def test_cada_empresa_expone_los_campos_del_detalle_del_deudor(empresa: str):
    labels = _labels(empresa)
    for etiqueta in ("RUT", "Nombre", "Correo", "Correo (Excel)", "Teléfono Fijo", "Teléfono Móvil"):
        assert etiqueta in labels, f"{empresa} no ofrece asociar '{etiqueta}'"


def test_consalud_cubre_todas_las_columnas_visibles_del_detalle():
    labels = _labels("Consalud")
    esperadas = {etiqueta for etiqueta, _ in CAMPOS_CLIENTE_BASE}
    esperadas |= {etiqueta for etiqueta, _ in COLUMNAS_DETALLE_DEUDA_BASE if etiqueta != "Correo"}
    assert esperadas <= labels


def test_los_campos_calculados_no_se_envian_en_el_mapeo():
    for empresa in ("Cart-56", "Cruz Blanca", "Colmena"):
        for sheet in sheets_for_empresa(empresa):
            keys = {field.key for field in assignable_fields(sheet)}
            assert not any(key.startswith("__") for key in keys)


def test_hoja_de_detalle_asociada_alimenta_el_detalle_del_deudor():
    detalle_raw = pd.DataFrame([{
        "Rut del deudor": "12.345.678-5",
        "Folio interno": "E-1",
        "Correo particular": "persona@example.test",
        "Fono celular": "912345678",
        "Deuda vigente": "4500",
    }])
    payload = {
        "sheet_name": "Resumen mensual",
        "columns": {},
        "detail_sheet_name": "Deudas",
        "detail_columns": {
            "Rut_Afiliado": "Rut del deudor",
            "Nro_Expediente": "Folio interno",
            "mail_afiliado": "Correo particular",
            "telefono_movil_afiliado": "Fono celular",
            "Saldo_Actual": "Deuda vigente",
            "BN": "",
        },
    }

    mapeado = normalizar_rut_detalle(apply_column_mapping(detalle_raw, detail_mapping_payload(payload)))
    assert mapeado.iloc[0]["Rut_Afiliado"] == "12345678"
    assert mapeado.iloc[0]["Dv"] == "5"

    info_cliente, filas_deuda = extraer_detalle_deudor(mapeado, "12345678-5")
    assert info_cliente["Correo"] == "persona@example.test"
    assert info_cliente["Teléfono Móvil"] == "912345678"
    assert info_cliente["Correo (Excel)"] == "persona@example.test"
    assert filas_deuda[0]["N° Expediente"] == "E-1"
    assert filas_deuda[0]["Saldo Actual ($)"] == "$ 4.500"


def test_sin_hoja_de_detalle_no_se_aplica_mapeo():
    payload = {"sheet_name": "Hoja1", "columns": {}, "detail_sheet_name": "", "detail_columns": {}}
    assert detail_mapping_payload(payload) is None


def test_correo_excel_se_puede_asociar_por_separado_en_cart56():
    raw = pd.DataFrame([{
        "Identificador": "76.543.210-1",
        "Razon social": "Empresa Ficticia",
        "Mail contacto": "contacto@example.test",
        "Mail respaldo": "respaldo@example.test",
        "Folio LIQ": "L-1",
        "Mto Pagar": "5000",
    }])
    mapeado = apply_column_mapping(raw, {"columns": {
        "RUT Emp": "Identificador",
        "Empresa": "Razon social",
        "mail_afiliado": "Mail contacto",
        "BN": "Mail respaldo",
        "No Licencia": "Folio LIQ",
        "Mto Pagar": "Mto Pagar",
    }})

    _, detalle = transformar_cart56_raw(mapeado)
    assert detalle.iloc[0]["mail_afiliado"] == "contacto@example.test"
    assert detalle.iloc[0]["BN"] == "respaldo@example.test"


def test_correo_excel_sin_asociar_reutiliza_el_correo_en_isapres():
    raw = pd.DataFrame([{
        "Mandante": "CruzBlanca", "RUT_Deudor": "11.111.111-1", "Nombre_Deudor": "Persona",
        "Estado_Gestion": "SIN PAGO", "Fecha_Emision_Deuda": "2026-01-10",
        "Fecha_Vencimiento_Deuda": "2026-02-10", "Monto_Cobrar": "900",
        "Email_Deudor": "cb@example.test", "BN": "",
    }])
    _, detalle = transformar_isapre_raw(raw, "Cruz Blanca")
    assert detalle.iloc[0]["BN"] == "cb@example.test"

    raw["BN"] = "excel@example.test"
    _, detalle = transformar_isapre_raw(raw, "Cruz Blanca")
    assert detalle.iloc[0]["BN"] == "excel@example.test"


def test_backend_lee_la_hoja_de_detalle_asociada():
    pytest.importorskip("sqlalchemy")
    from app.services.deudor_import_service import _read_general_excel

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([{
            "Rut_Afiliado": "12345678", "Dv": "5", "Nombre_Afiliado": "Persona",
        }]).to_excel(writer, sheet_name="Resumen mensual", index=False)
        pd.DataFrame([{
            "Rut del deudor": "12.345.678-5", "Folio interno": "E-1",
            "Correo particular": "persona@example.test",
        }]).to_excel(writer, sheet_name="Deudas", index=False)

    _, df_detalle = _read_general_excel(output.getvalue(), {
        "sheet_name": "Resumen mensual",
        "columns": {},
        "detail_sheet_name": "Deudas",
        "detail_columns": {
            "Rut_Afiliado": "Rut del deudor",
            "Nro_Expediente": "Folio interno",
            "mail_afiliado": "Correo particular",
        },
    })

    assert df_detalle.iloc[0]["Rut_Afiliado"] == "12345678"
    assert df_detalle.iloc[0]["Dv"] == "5"
    assert df_detalle.iloc[0]["Nro_Expediente"] == "E-1"
    assert df_detalle.iloc[0]["mail_afiliado"] == "persona@example.test"
