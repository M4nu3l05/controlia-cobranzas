import hashlib
import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from app.api.deudores import list_deudores as list_deudores_endpoint
from app.db.session import Base
from app.models.debtor_assignment import (
    DebtorAssignmentAlias,
    DebtorAssignmentAudit,
    DebtorUserAssignment,
)
from app.models.deudor import DeudorResumen
from app.models.gestion import DeudorGestion
from app.models.user import User
from app.services.debtor_assignment_service import (
    apply_debtor_assignments_service,
    normalize_assignment_name,
    preview_debtor_assignments_service,
)
from app.services.deudor_service import get_dashboard_summary_service, list_deudores_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            DeudorResumen.__table__,
            DeudorGestion.__table__,
            DebtorUserAssignment.__table__,
            DebtorAssignmentAlias.__table__,
            DebtorAssignmentAudit.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _user(username: str, *, role: str = "ejecutivo") -> User:
    slug = normalize_assignment_name(username).replace(" ", ".")
    return User(
        email=f"{slug}@example.test",
        username=username,
        password_hash="test",
        salt="test",
        role=role,
        is_active=True,
    )


def _resumen(rut: str, nombre: str, *, estado: str = "Sin Gestión") -> DeudorResumen:
    return DeudorResumen(
        empresa="Consalud",
        rut_afiliado=rut,
        dv="1",
        rut_completo=f"{rut}-1",
        nombre_afiliado=nombre,
        estado_deudor=estado,
        periodo_carga="202609",
        copago=100,
        total_pagos=10,
        saldo_actual=90,
    )


def _workbook(rows: list[dict]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="DETALLE", index=False)
    return output.getvalue()


def test_assignment_preview_apply_is_case_accent_and_camel_case_insensitive(db):
    admin = _user("Admin Prueba", role="admin")
    executive_one = _user("Ejecutiva Uno")
    executive_two = _user("Ejecutiva N 2")
    db.add_all([
        admin,
        executive_one,
        executive_two,
        _resumen("11111111", "Persona A"),
        _resumen("22222222", "Persona B", estado="Contactado"),
        _resumen("33333333", "Persona C"),
        DeudorGestion(
            empresa="Consalud",
            rut_afiliado="11111111",
            nombre_afiliado="Persona A",
            tipo_gestion="Llamada",
            estado="Contactado",
            fecha_gestion="18/09/2026",
            fecha_gestion_iso="2026-09-18",
            observacion="Gestión previa que debe conservarse",
        ),
    ])
    db.commit()

    content = _workbook([
        {"Rut_Afiliado": "11111111", "Ejecutiva": "EJECUTIVA UNO"},
        {"Rut_Afiliado": "11111111", "Ejecutiva": "Ejecutiva Uno"},
        {"Rut_Afiliado": "22222222", "Ejecutiva": "EJECUTIVA N° 2"},
        {"Rut_Afiliado": "33333333", "Ejecutiva": "EJECUTIVA UNO"},
        {"Rut_Afiliado": "99999999", "Ejecutiva": "EJECUTIVA UNO"},
    ])

    preview = preview_debtor_assignments_service(
        db,
        empresa="Consalud",
        content=content,
        source_file="nomina_prueba.xlsx",
    )
    assert preview["total_rows"] == 5
    assert preview["unique_debtors"] == 4
    assert preview["existing_debtors"] == 3
    assert preview["missing_debtors"] == 1
    assert preview["unresolved_labels"] == 0
    assert preview["conflicting_debtors"] == 0

    result = apply_debtor_assignments_service(
        db,
        empresa="Consalud",
        content=content,
        source_file="nomina_prueba.xlsx",
        executor=admin,
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
    )
    assert result["assigned_debtors"] == 3
    assert result["missing_debtors"] == 1
    assert db.query(DebtorUserAssignment).count() == 3
    assert db.query(DebtorAssignmentAudit).count() == 3
    assert db.query(DeudorGestion).one().observacion == "Gestión previa que debe conservarse"

    visible_one = list_deudores_service(db, assigned_user_id=executive_one.id)
    visible_two = list_deudores_service(db, assigned_user_id=executive_two.id)
    dashboard_one = get_dashboard_summary_service(db, assigned_user_id=executive_one.id)
    assert {item.rut_afiliado for item in visible_one.items} == {"11111111", "33333333"}
    assert [item.rut_afiliado for item in visible_two.items] == ["22222222"]
    assert dashboard_one.total_deudores == 2

    filtered_endpoint = list_deudores_endpoint(
        q="",
        empresa="",
        periodo_carga="",
        limit=500,
        offset=0,
        include_contact=False,
        assigned_user_id=int(executive_two.id),
        db=db,
        current_user=admin,
    )
    assert filtered_endpoint.total == 1
    assert filtered_endpoint.items[0].rut_afiliado == "22222222"
    with pytest.raises(HTTPException) as forbidden:
        list_deudores_endpoint(
            q="",
            empresa="",
            periodo_carga="",
            limit=500,
            offset=0,
            include_contact=False,
            assigned_user_id=int(executive_two.id),
            db=db,
            current_user=executive_one,
        )
    assert forbidden.value.status_code == 403

    repeated = apply_debtor_assignments_service(
        db,
        empresa="Consalud",
        content=content,
        source_file="nomina_prueba.xlsx",
        executor=admin,
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
    )
    assert repeated["assigned_debtors"] == 0
    assert repeated["reassigned_debtors"] == 0
    assert repeated["unchanged_debtors"] == 3
    assert db.query(DebtorAssignmentAudit).count() == 3


def test_assignment_rejects_conflicting_or_unresolved_names(db):
    admin = _user("Admin Prueba", role="admin")
    db.add_all([admin, _user("Ejecutiva Uno"), _resumen("11111111", "Persona A")])
    db.commit()

    conflicting = _workbook([
        {"Rut_Afiliado": "11111111", "Ejecutiva": "EJECUTIVA UNO"},
        {"Rut_Afiliado": "11111111", "Ejecutiva": "OTRA EJECUTIVA"},
    ])
    preview = preview_debtor_assignments_service(
        db, empresa="Consalud", content=conflicting, source_file="conflicto.xlsx"
    )
    assert preview["conflicting_debtors"] == 1
    assert preview["unresolved_labels"] == 1
    with pytest.raises(ValueError, match="más de una ejecutiva"):
        apply_debtor_assignments_service(
            db,
            empresa="Consalud",
            content=conflicting,
            source_file="conflicto.xlsx",
            executor=admin,
            expected_file_sha256=hashlib.sha256(conflicting).hexdigest(),
        )
    assert db.query(DebtorUserAssignment).count() == 0
    assert db.query(func.count(DebtorAssignmentAudit.id)).scalar() == 0
