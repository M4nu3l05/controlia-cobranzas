from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.deudores import list_template_contexts
from app.db.session import Base
from app.models.debtor_assignment import DebtorUserAssignment
from app.models.deudor import DeudorDetalle
from app.models.user import User
from app.schemas.deudor import TemplateContextBatchRequest, TemplateContextRequestItem
from app.schemas.template import EmailTemplateCreateRequest
from app.services.template_service import create_email_template_service
from envios.plantillas import (
    VARIABLES_DISPONIBLES,
    formatear_detalle_deudas,
    variables_no_soportadas,
)


def _user(email: str, role: str) -> User:
    return User(
        email=email,
        username=email.split("@", 1)[0],
        password_hash="test",
        salt="test",
        role=role,
        is_active=True,
    )


def _debt(empresa: str, rut: str, expediente: str, saldo: float) -> DeudorDetalle:
    return DeudorDetalle(
        empresa=empresa,
        rut_afiliado=rut,
        dv="1",
        rut_completo=f"{rut}-1",
        nombre_afiliado="Persona Prueba",
        nro_expediente=expediente,
        id_deuda=f"D-{expediente}",
        fecha_emision="2026-10-01",
        fecha_vencimiento="15/11/2026",
        prestador="Prestador Ficticio",
        monto_total=saldo,
        saldo_actual=saldo,
        is_active=True,
    )


def test_debt_detail_renders_one_block_per_debt_and_rejects_retired_aliases():
    text = formatear_detalle_deudas([
        {
            "id_deuda": "D-1",
            "fecha_emision": "2026-10-01",
            "prestador": "Prestador Uno",
            "saldo_actual": 1234.5,
        },
        {
            "nro_expediente": "EXP-2",
            "fecha_vencimiento": "2026-11-20",
            "monto_cobrar": 90000,
            "prestador": "",
        },
    ])

    assert "Deuda 1" in text and "Deuda 2" in text
    assert "01/10/2026" in text and "20/11/2026" in text
    assert "$ 1.234" in text and "$ 90.000" in text
    assert "Prestador: Prestador Uno" in text
    assert "Prestador: \n" not in text
    assert "{detalle_deudas}" in VARIABLES_DISPONIBLES
    assert variables_no_soportadas({"asunto": "{No_Licencia}", "cuerpo": "{fecha_pago}"}) == [
        "{No_Licencia}",
        "{fecha_pago}",
    ]


def test_backend_rejects_unknown_template_variables_on_save():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(ValueError, match="no soportadas"):
            create_email_template_service(
                db,
                payload=EmailTemplateCreateRequest(
                    nombre="Histórica",
                    asunto="Licencia {No_Licencia}",
                    cuerpo="Hola {nombre}",
                ),
            )


def test_template_context_batch_permissions_and_multiple_debts():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = _user("admin@example.test", "admin")
        supervisor = _user("supervisor@example.test", "supervisor")
        assigned = _user("assigned@example.test", "ejecutivo")
        other = _user("other@example.test", "ejecutivo")
        db.add_all([admin, supervisor, assigned, other])
        db.flush()
        db.add_all([
            _debt("Colmena", "11111111", "EXP-1", 1000),
            _debt("Colmena", "11111111", "EXP-2", 2000),
            _debt("Cruz Blanca", "22222222", "EXP-3", 3000),
        ])
        db.add(DebtorUserAssignment(
            empresa="Colmena",
            rut_afiliado="11111111",
            user_id=assigned.id,
            assigned_by_user_id=admin.id,
        ))
        db.commit()

        colmena = TemplateContextBatchRequest(items=[
            TemplateContextRequestItem(empresa="Colmena", rut="11.111.111-1")
        ])
        both = TemplateContextBatchRequest(items=[
            TemplateContextRequestItem(empresa="Colmena", rut="11111111"),
            TemplateContextRequestItem(empresa="Cruz Blanca", rut="22222222"),
        ])

        for privileged in (admin, supervisor):
            rows = list_template_contexts(colmena, db, privileged)
            assert len(rows) == 1
            assert [debt.nro_expediente for debt in rows[0].deudas] == ["EXP-1", "EXP-2"]

        rows = list_template_contexts(colmena, db, assigned)
        assert len(rows[0].deudas) == 2
        with pytest.raises(HTTPException) as denied:
            list_template_contexts(both, db, assigned)
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException):
            list_template_contexts(colmena, db, other)
