import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.debtor_assignment import DebtorUserAssignment
from app.models.deudor import DeudorResumen
from app.models.gestion import DeudorGestion
from app.models.user import User
from app.schemas.gestion import GestionCreateRequest
from app.services.deudor_service import list_deudores_service
from app.services.gestion_service import create_gestion_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(email: str, username: str, role: str = "supervisor") -> User:
    return User(
        email=email,
        username=username,
        role=role,
        is_active=True,
        must_change_password=False,
        password_hash="test",
        salt="test",
    )


def _debtor(empresa: str, rut: str, nombre: str, amount: float, executive: str = ""):
    return DeudorResumen(
        empresa=empresa,
        rut_afiliado=rut,
        dv="K",
        rut_completo=f"{rut}-K",
        nombre_afiliado=nombre,
        estado_deudor="Contactado",
        ejecutivo_asignado=executive,
        nro_expediente="EXP-2026-77",
        max_emision_ok="16/10/2026",
        min_emision_ok="01/10/2026",
        copago=amount,
        total_pagos=1000,
        saldo_actual=amount - 1000,
        source_file="nomina_octubre.xlsx",
        periodo_carga="202610",
    )


def test_universal_search_matches_visible_and_assigned_executive_fields_without_duplicates(db):
    admin = _user("admin@example.test", "Administradora", "admin")
    executive = _user("cobranza@example.test", "Ejecutiva Norte")
    first = _debtor("Consalud", "12345678", "Persona Uno", 2500000)
    second = _debtor("Colmena", "87654321", "Persona Dos", 3000, "Responsable heredada")
    db.add_all([admin, executive, first, second])
    db.flush()
    db.add(
        DebtorUserAssignment(
            empresa="Consalud",
            rut_afiliado="12345678",
            user_id=executive.id,
            assigned_by_user_id=admin.id,
            source_label="Ejecutiva Norte",
            normalized_label="ejecutiva norte",
        )
    )
    db.commit()

    queries = {
        "12.345.678-K": "12345678",
        "Persona Uno": "12345678",
        "Consalud": "12345678",
        "Ejecutiva Norte": "12345678",
        "cobranza@example.test": "12345678",
        "Contactado": None,
        "EXP-2026-77": None,
        "202610": None,
        "16/10/2026": None,
        "$2.500.000": "12345678",
        "Responsable heredada": "87654321",
    }
    for query, expected_rut in queries.items():
        response = list_deudores_service(db, q=query, limit=20, offset=0)
        assert response.total == len(response.items)
        assert len({item.rut_afiliado for item in response.items}) == response.total
        if expected_rut:
            assert [item.rut_afiliado for item in response.items] == [expected_rut]


def test_manual_management_retry_with_same_operation_id_is_idempotent(db):
    executor = _user("supervisor@example.test", "Supervisora")
    db.add(executor)
    db.add(_debtor("Consalud", "12345678", "Persona Uno", 5000))
    db.commit()
    request = GestionCreateRequest(
        empresa="Consalud",
        nombre_afiliado="Persona Uno",
        tipo_gestion="Llamada",
        estado="Contactado",
        fecha_gestion="16/10/2026",
        observacion="Prueba idempotente",
        origen="manual",
        client_operation_id="8f30234b-4630-4f04-9a69-1ea87046c3cc",
    )

    first = create_gestion_service(db, rut="12345678", payload=request, executor=executor)
    repeated = create_gestion_service(db, rut="12.345.678-K", payload=request, executor=executor)

    assert first.id == repeated.id
    assert db.query(DeudorGestion).count() == 1
