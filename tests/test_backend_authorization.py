import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationError,
    can_operate_company,
    require_company_operation,
    require_supervisor,
    resolve_derivation_target,
)
from app.api.deudores import registrar_pago
from app.api.gestiones import create_gestion
from app.db.session import Base
from app.models.gestion import DeudorGestion
from app.schemas.deudor import RegistrarPagoRequest
from app.schemas.gestion import GestionCreateRequest
from app.services.gestion_service import marcar_gestion_asignada_realizada_service
from fastapi import HTTPException


def _user(user_id: int, role: str):
    return SimpleNamespace(id=user_id, role=role)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as session:
        session.execute(
            text(
                """
                CREATE TABLE cartera_asignaciones (
                    empresa TEXT PRIMARY KEY,
                    user_id INTEGER NULL
                )
                """
            )
        )
        session.execute(
            text(
                """
                CREATE TABLE cartera_temporary_replacements (
                    id INTEGER PRIMARY KEY,
                    empresa TEXT NOT NULL,
                    replacement_user_id INTEGER NOT NULL,
                    starts_at DATETIME NOT NULL,
                    ends_at DATETIME NOT NULL,
                    is_active BOOLEAN NOT NULL
                )
                """
            )
        )
        session.execute(
            text("INSERT INTO cartera_asignaciones(empresa, user_id) VALUES (:empresa, :user_id)"),
            {"empresa": "Cart-56", "user_id": 10},
        )
        session.commit()
        yield session


def test_admin_y_supervisor_operan_todas_las_carteras(db):
    assert can_operate_company(db, _user(1, "admin"), "Cart-56")
    assert can_operate_company(db, _user(2, "supervisor"), "Otra cartera")


def test_ejecutiva_solo_opera_su_cartera(db):
    assert can_operate_company(db, _user(10, "ejecutivo"), "Cart-56")
    assert not can_operate_company(db, _user(11, "ejecutivo"), "Cart-56")

    with pytest.raises(AuthorizationError):
        require_company_operation(db, _user(11, "ejecutivo"), "Cart-56")


def test_reemplazo_temporal_vigente_permite_operar(db):
    db.execute(
        text(
            """
            INSERT INTO cartera_temporary_replacements(
                id, empresa, replacement_user_id, starts_at, ends_at, is_active
            ) VALUES (
                1, 'Cart-56', 11,
                DATETIME(CURRENT_TIMESTAMP, '-1 hour'),
                DATETIME(CURRENT_TIMESTAMP, '+1 day'),
                TRUE
            )
            """
        )
    )
    db.commit()
    assert can_operate_company(db, _user(11, "ejecutivo"), "Cart-56")


def test_derivacion_solo_puede_ir_a_responsable_de_cartera(db):
    assert resolve_derivation_target(
        db,
        company="Cart-56",
        requested_user_id=10,
    ) == 10

    with pytest.raises(AuthorizationError):
        resolve_derivation_target(
            db,
            company="Cart-56",
            requested_user_id=11,
        )


def test_solo_supervisor_puede_revertir_pago():
    require_supervisor(_user(2, "supervisor"), action="revertir un pago")

    with pytest.raises(AuthorizationError):
        require_supervisor(_user(1, "admin"), action="revertir un pago")
    with pytest.raises(AuthorizationError):
        require_supervisor(_user(10, "ejecutivo"), action="revertir un pago")


def test_api_bloquea_pago_y_gestion_normal_en_cartera_ajena(db):
    foreign_user = _user(11, "ejecutivo")

    with pytest.raises(HTTPException) as payment_error:
        registrar_pago(
            rut="11111111",
            payload=RegistrarPagoRequest(
                empresa="Cart-56",
                expediente="EXP-1",
                tipo_pago="Abono",
                monto=1000,
                idempotency_key="authorization-test-payment",
            ),
            db=db,
            current_user=foreign_user,
        )
    assert payment_error.value.status_code == 403

    with pytest.raises(HTTPException) as management_error:
        create_gestion(
            rut="11111111",
            payload=GestionCreateRequest(
                empresa="Cart-56",
                tipo_gestion="Llamada",
                estado="Contactado",
                fecha_gestion="01/01/2026",
            ),
            db=db,
            current_user=foreign_user,
        )
    assert management_error.value.status_code == 403


def test_solo_destinataria_puede_cerrar_derivacion():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        row = DeudorGestion(
            empresa="Cart-56",
            rut_afiliado="11111111",
            nombre_afiliado="Persona Demo",
            tipo_gestion="Manual",
            estado="Gestion asignada",
            fecha_gestion="01/01/2026",
            observacion="Contacto derivado",
            origen="manual",
            assigned_to_user_id=10,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        with pytest.raises(AuthorizationError):
            marcar_gestion_asignada_realizada_service(
                session,
                gestion_id=row.id,
                executor=_user(1, "admin"),
            )
        with pytest.raises(AuthorizationError):
            marcar_gestion_asignada_realizada_service(
                session,
                gestion_id=row.id,
                executor=_user(2, "supervisor"),
            )

        result = marcar_gestion_asignada_realizada_service(
            session,
            gestion_id=row.id,
            executor=_user(10, "ejecutivo"),
        )
        assert "realizada" in result.estado.lower()
