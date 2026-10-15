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

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session

from app.api.deudores import list_deudores as list_deudores_endpoint
from app.core.authorization import can_operate_debtor
from app.db.session import Base
from app.models.debtor_assignment import (
    DebtorAssignmentAlias,
    DebtorAssignmentAudit,
    DebtorUserAssignment,
)
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion
from app.models.user import User
from app.services.debtor_assignment_service import (
    apply_debtor_assignments_service,
    normalize_assignment_name,
    preview_debtor_assignments_service,
)
from app.services.deudor_service import (
    get_dashboard_summary_service,
    list_destinatarios_service,
    list_deudores_service,
)
from app.services.deudor_import_service import import_deudores_excel_service
from app.models.operations import DebtorBirladoTransition, DebtorImportBatch


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            DeudorResumen.__table__,
            DeudorDetalle.__table__,
            DebtorImportBatch.__table__,
            DebtorBirladoTransition.__table__,
            DeudorGestion.__table__,
            DebtorUserAssignment.__table__,
            DebtorAssignmentAlias.__table__,
            DebtorAssignmentAudit.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _user(username: str, *, role: str = "supervisor") -> User:
    slug = normalize_assignment_name(username).replace(" ", ".")
    return User(
        email=f"{slug}@example.test",
        username=username,
        password_hash="test",
        salt="test",
        role=role,
        is_active=True,
    )


def _resumen(
    rut: str,
    nombre: str,
    *,
    estado: str = "Sin Gestión",
    empresa: str = "Consalud",
) -> DeudorResumen:
    return DeudorResumen(
        empresa=empresa,
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


def _import_workbook(rows: list[dict]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="RESUMEN", index=False)
    return output.getvalue()


def _create_scope_tables(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE cartera_asignaciones (
            empresa TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            is_primary BOOLEAN NOT NULL DEFAULT 0,
            PRIMARY KEY (empresa, user_id)
        )
    """))
    db.execute(text("""
        CREATE TABLE cartera_temporary_replacements (
            id INTEGER PRIMARY KEY,
            empresa TEXT NOT NULL,
            titular_user_id INTEGER NOT NULL,
            replacement_user_id INTEGER NOT NULL,
            starts_at DATETIME NOT NULL,
            ends_at DATETIME NOT NULL,
            is_active BOOLEAN NOT NULL
        )
    """))
    db.commit()


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
    filtered_by_supervisor = list_deudores_endpoint(
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
    assert [item.rut_afiliado for item in filtered_by_supervisor.items] == ["22222222"]

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


def test_supervisor_access_is_not_restricted_by_case_or_portfolio_assignments(db):
    supervisor = _user("Supervisor Prueba", role="supervisor")
    executive_one = _user("Ejecutiva Uno")
    executive_two = _user("Ejecutiva Dos")
    db.add_all([
        supervisor,
        executive_one,
        executive_two,
        _resumen("11111111", "Asignado Uno"),
        _resumen("22222222", "Asignado Dos"),
        _resumen("33333333", "Sin Asignar"),
        _resumen("44444444", "Cartera Completa", empresa="Cart-56"),
    ])
    db.flush()
    db.add_all([
        DebtorUserAssignment(
            empresa="Consalud",
            rut_afiliado="11111111",
            user_id=executive_one.id,
            assigned_by_user_id=supervisor.id,
        ),
        DebtorUserAssignment(
            empresa="Consalud",
            rut_afiliado="22222222",
            user_id=executive_two.id,
            assigned_by_user_id=supervisor.id,
        ),
    ])
    db.commit()
    _create_scope_tables(db)
    db.execute(
        text("INSERT INTO cartera_asignaciones(empresa, user_id) VALUES ('Cart-56', :user_id)"),
        {"user_id": executive_one.id},
    )
    db.commit()

    visible = list_deudores_endpoint(
        q="",
        empresa="",
        periodo_carga="",
        limit=500,
        offset=0,
        include_contact=False,
        assigned_user_id=None,
        db=db,
        current_user=executive_one,
    )
    dashboard = get_dashboard_summary_service(
        db,
        executive_user_id=executive_one.id,
    )
    recipients = list_destinatarios_service(
        db,
        executive_user_id=executive_one.id,
    )

    assert {item.rut_afiliado for item in visible.items} == {
        "11111111", "22222222", "33333333", "44444444"
    }
    assert dashboard.total_deudores == 2
    assert {item.rut_afiliado for item in recipients} == {"11111111", "44444444"}
    assert can_operate_debtor(db, executive_one, "Consalud", "11111111")
    assert can_operate_debtor(db, executive_one, "Consalud", "22222222")
    assert can_operate_debtor(db, executive_one, "Consalud", "33333333")


def test_replacement_is_organizational_and_supervisors_keep_full_access(db):
    supervisor = _user("Supervisor Prueba", role="supervisor")
    titular = _user("Ejecutiva Titular")
    replacement = _user("Ejecutiva Reemplazo")
    db.add_all([
        supervisor,
        titular,
        replacement,
        _resumen("11111111", "Caso Reemplazado"),
        _resumen("22222222", "Caso Sin Asignar"),
    ])
    db.flush()
    db.add(
        DebtorUserAssignment(
            empresa="Consalud",
            rut_afiliado="11111111",
            user_id=titular.id,
            assigned_by_user_id=supervisor.id,
        )
    )
    db.commit()
    _create_scope_tables(db)
    db.execute(
        text("""
            INSERT INTO cartera_temporary_replacements(
                id, empresa, titular_user_id, replacement_user_id,
                starts_at, ends_at, is_active
            ) VALUES (
                1, 'Consalud', :titular_user_id, :replacement_user_id,
                DATETIME(CURRENT_TIMESTAMP, '-1 hour'),
                DATETIME(CURRENT_TIMESTAMP, '+1 day'), 1
            )
        """),
        {
            "titular_user_id": titular.id,
            "replacement_user_id": replacement.id,
        },
    )
    db.commit()

    visible = list_deudores_endpoint(
        q="",
        empresa="",
        periodo_carga="",
        limit=500,
        offset=0,
        include_contact=False,
        assigned_user_id=None,
        db=db,
        current_user=replacement,
    )

    assert {item.rut_afiliado for item in visible.items} == {"11111111", "22222222"}
    assert can_operate_debtor(db, replacement, "Consalud", "11111111")
    assert can_operate_debtor(db, replacement, "Consalud", "22222222")


def test_assignment_rejects_conflicting_names(db):
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


def test_unknown_name_must_be_mapped_and_blank_uses_primary_supervisor(db):
    admin = _user("Admin Prueba", role="admin")
    executive = _user("Ejecutiva Uno")
    db.add_all([
        admin,
        executive,
        _resumen("11111111", "Persona A"),
        _resumen("22222222", "Persona B"),
        _resumen("33333333", "Persona C"),
    ])
    db.commit()
    _create_scope_tables(db)
    db.execute(
        text("""
            INSERT INTO cartera_asignaciones(empresa, user_id, is_primary)
            VALUES ('Consalud', :user_id, 1)
        """),
        {"user_id": executive.id},
    )
    db.commit()

    initial = _workbook([
        {"Rut_Afiliado": "11111111", "Ejecutiva": "Ejecutiva Uno"},
        {"Rut_Afiliado": "22222222", "Ejecutiva": "Ejecutiva Uno"},
    ])
    apply_debtor_assignments_service(
        db,
        empresa="Consalud",
        content=initial,
        source_file="inicial.xlsx",
        executor=admin,
        expected_file_sha256=hashlib.sha256(initial).hexdigest(),
    )
    assert db.query(DebtorUserAssignment).count() == 2

    updated = _workbook([
        {"Rut_Afiliado": "11111111", "Ejecutiva": "Usuario Por Crear"},
        {"Rut_Afiliado": "22222222", "Ejecutiva": ""},
        {"Rut_Afiliado": "33333333", "Ejecutiva": "Ejecutiva Uno"},
    ])
    preview = preview_debtor_assignments_service(
        db, empresa="Consalud", content=updated, source_file="actualizada.xlsx"
    )
    assert preview["unique_debtors"] == 3
    assert preview["existing_debtors"] == 3
    assert preview["unresolved_labels"] == 1
    assert preview["blank_assignments"] == 1

    result = apply_debtor_assignments_service(
        db,
        empresa="Consalud",
        content=updated,
        source_file="actualizada.xlsx",
        executor=admin,
        expected_file_sha256=hashlib.sha256(updated).hexdigest(),
        overrides={"usuario por crear": executive.id},
    )

    assert result["assigned_debtors"] == 1
    assert result["reassigned_debtors"] == 0
    assert result["unassigned_debtors"] == 0
    assignments = db.query(DebtorUserAssignment).all()
    assert {(row.rut_afiliado, row.user_id) for row in assignments} == {
        ("11111111", executive.id),
        ("22222222", executive.id),
        ("33333333", executive.id),
    }


def test_manual_assignment_rejects_an_invalid_user_id(db):
    admin = _user("Admin Prueba", role="admin")
    db.add_all([admin, _resumen("11111111", "Persona A")])
    db.commit()
    content = _workbook([
        {"Rut_Afiliado": "11111111", "Ejecutiva": "Usuario Externo"},
    ])

    with pytest.raises(ValueError, match="usuario inexistente"):
        apply_debtor_assignments_service(
            db,
            empresa="Consalud",
            content=content,
            source_file="asignacion_invalida.xlsx",
            executor=admin,
            expected_file_sha256=hashlib.sha256(content).hexdigest(),
            overrides={"usuario externo": 99999},
        )

    assert db.query(DebtorUserAssignment).count() == 0


def test_database_import_requires_and_applies_all_manual_relationships(db):
    supervisor = _user("Supervisor Prueba", role="supervisor")
    executive = _user("Ejecutiva Registrada")
    db.add_all([supervisor, executive])
    db.commit()

    content = _import_workbook([
        {
            "Rut_Afiliado": "11111111",
            "Nombre_Afiliado": "Persona A",
            "Ejecutiva": "Nombre Externo",
        },
        {
            "Rut_Afiliado": "22222222",
            "Nombre_Afiliado": "Persona B",
            "Ejecutiva": "Usuario Aún No Creado",
        },
    ])
    result = import_deudores_excel_service(
        db,
        empresa="Consalud",
        content=content,
        source_file="base_con_ejecutivas.xlsx",
        executor=supervisor,
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
        confirm_birlados=True,
        assignment_overrides={
            "nombre externo": executive.id,
            "usuario aun no creado": supervisor.id,
        },
    )

    assignments = db.query(DebtorUserAssignment).all()
    assert result["asignaciones_aplicadas"] == 2
    assert result["deudores_sin_asignar"] == 0
    assert {(row.rut_afiliado, row.user_id) for row in assignments} == {
        ("11111111", executive.id),
        ("22222222", supervisor.id),
    }


def test_saved_alias_resolves_ambiguous_duplicate_names_on_later_import(db):
    admin = _user("Admin Prueba", role="admin")
    executive_one = _user("María Pérez González")
    executive_two = _user("MARIA PEREZ GONZALEZ")
    executive_two.email = "otra.ejecutiva@example.com"
    db.add_all([admin, executive_one, executive_two])
    db.commit()

    seed = _workbook([
        {"Rut_Afiliado": "990000000001", "Ejecutiva": "María Pérez González"},
    ])
    seeded = apply_debtor_assignments_service(
        db,
        empresa="Consalud",
        content=seed,
        source_file="relaciones.xlsx",
        executor=admin,
        expected_file_sha256=hashlib.sha256(seed).hexdigest(),
        overrides={"maria perez gonzalez": executive_one.id},
    )
    assert seeded["aliases_saved"] == 1
    assert seeded["missing_debtors"] == 1

    db.add(_resumen("11111111", "Persona A"))
    db.commit()
    content = _workbook([
        {"Rut_Afiliado": "11111111", "Ejecutiva": "MARÍA PÉREZ GONZÁLEZ"},
    ])
    preview = preview_debtor_assignments_service(
        db,
        empresa="Consalud",
        content=content,
        source_file="base.xlsx",
    )
    assert preview["unresolved_labels"] == 0
    assert preview["matches"][0]["status"] == "matched_alias"
    assert preview["matches"][0]["user_id"] == executive_one.id
