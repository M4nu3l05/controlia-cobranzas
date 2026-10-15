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

from app.db.session import Base
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion
from app.services.gestion_import_service import (
    import_gestiones_excel_service,
    preview_gestiones_import_service,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[DeudorResumen.__table__, DeudorDetalle.__table__, DeudorGestion.__table__],
    )
    with Session(engine) as session:
        yield session


def _summary(company: str, rut: str, name: str) -> DeudorResumen:
    return DeudorResumen(
        empresa=company,
        rut_afiliado=rut,
        dv="1",
        rut_completo=f"{rut}-1",
        nombre_afiliado=name,
        estado_deudor="Sin Gestión",
        saldo_actual=100,
    )


def _detail(company: str, rut: str, name: str) -> DeudorDetalle:
    return DeudorDetalle(
        empresa=company,
        rut_afiliado=rut,
        dv="1",
        rut_completo=f"{rut}-1",
        nombre_afiliado=name,
        estado_deudor="Sin Gestión",
    )


def _workbook(*, sms: list[dict] | None = None, email: list[dict] | None = None) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if sms is not None:
            pd.DataFrame(sms).to_excel(writer, sheet_name="SMS", index=False)
        if email is not None:
            pd.DataFrame(email).to_excel(writer, sheet_name="Email", index=False)
    return output.getvalue()


def test_preview_detects_ambiguous_missing_explicit_company_and_duplicates(db):
    db.add_all([
        _summary("Consalud", "11111111", "Persona Ambigua"),
        _summary("Colmena", "11111111", "Persona Ambigua"),
        _summary("Consalud", "22222222", "Persona Única"),
        DeudorGestion(
            empresa="Consalud",
            rut_afiliado="22222222",
            nombre_afiliado="Persona Única",
            tipo_gestion="SMS",
            estado="Contactado",
            fecha_gestion="01/10/2026",
            fecha_gestion_iso="2026-10-01",
            observacion="Contacto previo",
            origen="excel_SMS",
        ),
    ])
    db.commit()

    content = _workbook(sms=[
        {
            "Rut_Afiliado": "11.111.111-1",
            "Nombre_Afiliado": "Persona Ambigua",
            "Estado": "Respondido",
            "Fecha_gestion": "02/10/2026",
            "Observacion": "Elegir cartera",
        },
        {
            "Rut_Afiliado": "22222222",
            "Empresa": "Consalud",
            "Estado": "Contactado",
            "Fecha_gestion": "01/10/2026",
            "Observacion": "Contacto previo",
        },
        {
            "Rut_Afiliado": "99999999",
            "Estado": "Enviado",
            "Fecha_gestion": "fecha no estándar",
        },
    ])

    preview = preview_gestiones_import_service(
        db,
        content=content,
        source_file="gestiones_prueba.xlsx",
    )

    assert preview["total_rows"] == 3
    assert preview["missing_debtors"] == 1
    assert preview["missing_ruts"] == ["99999999"]
    assert preview["duplicate_rows"] == 1
    assert preview["new_rows"] == 0
    assert preview["ambiguous_debtors"] == [{
        "rut": "11111111",
        "nombre": "Persona Ambigua",
        "companies": ["Colmena", "Consalud"],
    }]
    assert "Hoja 'Email' no encontrada en el Excel." in preview["warnings"]


def test_apply_uses_selected_company_and_updates_state_atomically(db):
    db.add_all([
        _summary("Consalud", "11111111", "Persona Ambigua"),
        _summary("Colmena", "11111111", "Persona Ambigua"),
        _detail("Consalud", "11111111", "Persona Ambigua"),
        _detail("Colmena", "11111111", "Persona Ambigua"),
    ])
    db.commit()
    content = _workbook(sms=[{
        "Rut_Afiliado": "11.111.111-1",
        "Estado": "Respondido",
        "Fecha_gestion": "15/10/2026",
        "Observacion": "Contacto masivo",
    }])

    result = import_gestiones_excel_service(
        db,
        content=content,
        source_file="gestiones_prueba.xlsx",
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
        company_overrides={"11111111": "Consalud"},
    )

    assert result["insertados"] == 1
    assert result["deudores_actualizados"] == 1
    assert db.query(DeudorGestion).one().empresa == "Consalud"
    assert db.query(DeudorResumen).filter_by(empresa="Consalud").one().estado_deudor == "Contactado"
    assert db.query(DeudorDetalle).filter_by(empresa="Consalud").one().estado_deudor == "Contactado"
    assert db.query(DeudorResumen).filter_by(empresa="Colmena").one().estado_deudor == "Sin Gestión"

    repeated = import_gestiones_excel_service(
        db,
        content=content,
        source_file="gestiones_prueba.xlsx",
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
        company_overrides={"11111111": "Consalud"},
    )
    assert repeated["insertados"] == 0
    assert repeated["omitidos_duplicados"] == 1


def test_apply_rejects_changed_file_and_unresolved_ambiguity_without_writes(db):
    db.add_all([
        _summary("Consalud", "11111111", "Persona Ambigua"),
        _summary("Colmena", "11111111", "Persona Ambigua"),
    ])
    db.commit()
    content = _workbook(sms=[{"Rut_Afiliado": "11111111", "Estado": "Enviado"}])

    with pytest.raises(ValueError, match="archivo cambió"):
        import_gestiones_excel_service(
            db,
            content=content,
            source_file="gestiones_prueba.xlsx",
            expected_file_sha256="hash-incorrecto",
        )
    assert db.query(DeudorGestion).count() == 0

    with pytest.raises(ValueError, match="seleccionar una cartera"):
        import_gestiones_excel_service(
            db,
            content=content,
            source_file="gestiones_prueba.xlsx",
            expected_file_sha256=hashlib.sha256(content).hexdigest(),
        )
    db.rollback()
    assert db.query(DeudorGestion).count() == 0


def test_apply_preserves_nonstandard_date_without_breaking_import(db):
    db.add(_summary("Consalud", "33333333", "Persona Fecha"))
    db.commit()
    content = _workbook(email=[{
        "Rut_Afiliado": "33333333",
        "Estado": "Entregado",
        "Fecha_gestion": "fecha informada por proveedor",
    }])

    result = import_gestiones_excel_service(
        db,
        content=content,
        source_file="gestiones_fecha.xlsx",
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
    )

    row = db.query(DeudorGestion).one()
    assert result["insertados"] == 1
    assert row.fecha_gestion == "fecha informada por"
    assert row.fecha_gestion_iso is None
    assert db.query(DeudorResumen).one().estado_deudor == "Gestionado"
