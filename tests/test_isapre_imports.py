from __future__ import annotations

import hashlib
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401
from app.db.session import Base
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.user import User
from app.services.deudor_import_service import (
    _parse_import_content,
    import_deudores_excel_service,
)
from deudores.schema_detalle import extraer_detalle_deudor
from deudores.import_mapping_dialog import apply_column_mapping, normalize_header


def _xlsx(df: pd.DataFrame, sheet_name: str) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


def _supervisor(db: Session) -> User:
    user = User(
        username="supervisor_isapre",
        email="supervisor.isapre@example.test",
        password_hash="x",
        salt="x",
        role="supervisor",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def test_column_mapping_imports_renamed_cruz_blanca_headers_and_marks_unassigned_fields():
    df = pd.DataFrame([{
        "Entidad": "CruzBlanca",
        "Identificador persona": "12.345.678-5",
        "Razón social": "Persona Ficticia",
        "Situación": "SIN PAGO",
        "Código obligación": "CB-X1",
        "Emisión origen": "2026-01-10",
        "Vencimiento origen": "2026-02-10",
        "Importe": 3500,
    }])
    mapping = {
        "sheet_name": "Datos externos",
        "columns": {
            "Mandante": "Entidad",
            "RUT_Deudor": "Identificador persona",
            "Nombre_Deudor": "Razón social",
            "Estado_Gestion": "Situación",
            "ID_Deuda": "Código obligación",
            "Fecha_Emision_Deuda": "Emisión origen",
            "Fecha_Vencimiento_Deuda": "Vencimiento origen",
            "Monto_Cobrar": "Importe",
            "Email_Deudor": "",
        },
    }

    resumen, detalle, _ = _parse_import_content(
        empresa="Cruz Blanca",
        content=_xlsx(df, "Datos externos"),
        source_file="base_202602.xlsx",
        column_mapping=mapping,
    )

    assert resumen.iloc[0]["Rut_Afiliado"] == "12345678"
    assert resumen.iloc[0]["Nro_Expediente"] == "1"
    assert detalle.iloc[0]["Nro_Expediente"] == "CB-X1"
    assert detalle.iloc[0]["mail_afiliado"] == ""


def test_mapping_helpers_are_accent_insensitive_and_do_not_remove_original_columns():
    source = pd.DataFrame({"RUT externo": ["1-9"], "Dirección especial": ["Calle ficticia"]})
    mapped = apply_column_mapping(source, {
        "columns": {"RUT_Deudor": "RUT externo", "Direccion_Deudor": "", "Ciudad_Deudor": "No existe"}
    })

    assert normalize_header("Dirección_Deudor") == "direcciondeudor"
    assert mapped.iloc[0]["RUT_Deudor"] == "1-9"
    assert mapped.iloc[0]["Direccion_Deudor"] == ""
    assert mapped.iloc[0]["Ciudad_Deudor"] == ""
    assert "RUT externo" in mapped.columns


def test_cruz_blanca_groups_by_rut_and_counts_only_present_debt_ids():
    df = pd.DataFrame([
        {
            "Mandante": "CruzBlanca", "RUT_Deudor": "12.345.678-5",
            "Nombre_Deudor": "Persona Ejemplo", "Estado_Gestion": "SIN PAGO",
            "ID_Deuda": "CB-1", "Fecha_Emision_Deuda": "2025-01-10",
            "Fecha_Vencimiento_Deuda": "2026-02-16", "Fecha_Prestacion": "2025-01-10",
            "Fecha_Prestacion2": "2025-01-12", "Monto_Cobrar": 1000,
            "Monto_Total": 1200, "Prestador": "Prestador Uno", "Email_Deudor": "a@example.test",
            "Telefono3_Deudor": "999999999", "Direccion_Deudor": "Calle 1",
            "Comuna_Deudor": "Santiago", "Ciudad_Deudor": "Santiago",
        },
        {
            "Mandante": "CruzBlanca", "RUT_Deudor": "12.345.678-5",
            "Nombre_Deudor": "PERSONA EJEMPLO", "Estado_Gestion": 0.05,
            "ID_Deuda": "", "Fecha_Emision_Deuda": "2024-12-01",
            "Fecha_Vencimiento_Deuda": "", "Fecha_Prestacion": "2024-12-01",
            "Fecha_Prestacion2": "2024-12-02", "Monto_Cobrar": 500,
            "Monto_Total": 600, "Prestador": "Prestador Dos", "Email_Deudor": "a@example.test",
            "Telefono3_Deudor": "999999999", "Direccion_Deudor": "Calle 1",
            "Comuna_Deudor": "Santiago", "Ciudad_Deudor": "Santiago",
        },
    ])
    resumen, detalle, periodo = _parse_import_content(
        empresa="Cruz Blanca",
        content=_xlsx(df, "Hoja1"),
        source_file="Carga CB 072026.xlsx",
    )

    assert periodo == "202607"
    assert len(resumen) == 1
    assert resumen.iloc[0]["Nro_Expediente"] == "1"
    assert resumen.iloc[0]["Estado_deudor"] == "Estado mixto"
    assert resumen.iloc[0]["MAX_Emision_ok"] == "202602"
    assert resumen.iloc[0]["MIN_Emision_ok"] == "202412"
    assert len(detalle) == 2
    assert detalle.iloc[1]["ID_Deuda"] == ""
    assert str(detalle.iloc[1]["Nro_Expediente"]).startswith("SIN-ID-")
    assert detalle.iloc[1]["Estado_deudor"] == "SE ACOGE AL 5%"


def test_colmena_import_persists_company_detail_and_financial_totals():
    df = pd.DataFrame([
        {
            "Mandante": "Colmena", "RUT_Deudor": "9.876.543-K", "Nombre_Deudor": "Persona Colmena",
            "Estado_Caso": "Activo", "ID_Deuda": "COL-1", "Fecha_Emision": "2025-03-01",
            "Fecha_Prestacion": "2025-03-02", "Monto_Cobrar": 2000, "Monto_Total": 2500,
            "Prestador": "Prestador A", "Email_Deudor": "colmena@example.test",
            "Telefono1_Deudor": "22222222", "Telefono2_Deudor": "988888888",
            "Direccion_Deudor": "Avenida 2", "Comuna_Deudor": "Providencia", "Ciudad_Deudor": "Santiago",
        },
        {
            "Mandante": "Colmena", "RUT_Deudor": "9.876.543-K", "Nombre_Deudor": "Persona Colmena",
            "Estado_Caso": "Activo", "ID_Deuda": "COL-2", "Fecha_Emision": "2025-04-01",
            "Fecha_Prestacion": "2025-04-05", "Monto_Cobrar": 3000, "Monto_Total": 3600,
            "Prestador": "Prestador B", "Email_Deudor": "colmena@example.test",
            "Telefono1_Deudor": "22222222", "Telefono2_Deudor": "988888888",
            "Direccion_Deudor": "Avenida 2", "Comuna_Deudor": "Providencia", "Ciudad_Deudor": "Santiago",
        },
    ])
    content = _xlsx(df, "Cartera Transformada")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        result = import_deudores_excel_service(
            db,
            empresa="Colmena",
            content=content,
            source_file="Carga Colmena 072026.xlsx",
            executor=_supervisor(db),
            expected_file_sha256=hashlib.sha256(content).hexdigest(),
            confirm_birlados=True,
        )

        resumen = db.query(DeudorResumen).one()
        detalles = db.query(DeudorDetalle).order_by(DeudorDetalle.id_deuda).all()
        assert result["resumen_insertados"] == 1
        assert resumen.nro_expediente == "2"
        assert resumen.copago == 5000
        assert resumen.total_pagos == 0
        assert resumen.saldo_actual == 5000
        assert resumen.max_emision_ok == "202504"
        assert resumen.min_emision_ok == "202503"
        assert [row.id_deuda for row in detalles] == ["COL-1", "COL-2"]
        assert detalles[0].monto_total == 2500
        assert detalles[0].monto_cobrar == 2000
        assert detalles[0].direccion_deudor == "Avenida 2"
        assert detalles[0].fecha_prestacion == "01/03/2025"
        assert detalles[0].fecha_prestacion2 == "02/03/2025"


def test_colmena_detail_uses_company_layout_and_na_columns():
    df = pd.DataFrame([{
        "Mandante": "Colmena", "RUT_Deudor": "11.111.111-1", "Nombre_Deudor": "Persona Prueba",
        "Estado_Caso": "Fallecido", "ID_Deuda": "COL-9", "Fecha_Emision": "2025-05-01",
        "Fecha_Prestacion": "2025-05-03", "Monto_Cobrar": 800, "Monto_Total": 1000,
        "Prestador": "Prestador Prueba", "Email_Deudor": "persona@example.test",
        "Telefono1_Deudor": "22111111", "Telefono2_Deudor": "991111111",
        "Direccion_Deudor": "Calle Ficticia", "Comuna_Deudor": "Ñuñoa", "Ciudad_Deudor": "Santiago",
    }])
    _, detalle, _ = _parse_import_content(
        empresa="Colmena", content=_xlsx(df, "Cartera Transformada"), source_file="Colmena 072026.xlsx"
    )
    detalle["_empresa"] = "Colmena"
    info, deudas = extraer_detalle_deudor(detalle, "11111111")

    assert info["Dirección"] == "Calle Ficticia"
    assert info["Comuna"] == "Ñuñoa"
    assert deudas[0]["No Licencia"] == "COL-9"
    assert deudas[0]["Mto Pagar"] == "$ 1.000"
    assert deudas[0]["Monto_Cobrar"] == "$ 800"
    assert deudas[0]["Monto_Facturado"] == "N/A"
    assert deudas[0]["_expediente_pago"] == "COL-9"
