import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.deudores import list_destinatarios
from app.db.session import Base
from app.models.deudor import DeudorDetalle, DeudorResumen


def _user(user_id: int, role: str):
    return SimpleNamespace(id=user_id, role=role)


def _alta_deudor(db: Session, *, empresa: str, rut: str, correo: str) -> None:
    db.add(
        DeudorResumen(
            empresa=empresa,
            rut_afiliado=rut,
            dv="1",
            rut_completo=f"{rut}-1",
            nombre_afiliado=f"Afiliado {rut}",
            periodo_carga="202608",
        )
    )
    db.add(
        DeudorDetalle(
            empresa=empresa,
            rut_afiliado=rut,
            dv="1",
            rut_completo=f"{rut}-1",
            nombre_afiliado=f"Afiliado {rut}",
            mail_afiliado=correo,
            nro_expediente="EXP-1",
            periodo_carga="202608",
        )
    )
    db.commit()


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[DeudorResumen.__table__, DeudorDetalle.__table__],
    )
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
            text("INSERT INTO cartera_asignaciones (empresa, user_id) VALUES ('Colmena', 10)")
        )
        session.execute(
            text("INSERT INTO cartera_asignaciones (empresa, user_id) VALUES ('Consalud', 20)")
        )
        session.commit()

        _alta_deudor(session, empresa="Colmena", rut="11111111", correo="colmena@test.cl")
        _alta_deudor(session, empresa="Consalud", rut="22222222", correo="consalud@test.cl")

        yield session


def _correos(items) -> set[str]:
    return {item.mail_afiliado for item in items}


def test_ejecutivo_sin_empresa_solo_recibe_su_cartera(db):
    items = list_destinatarios(
        empresa="",
        periodo_carga="",
        limit=5000,
        db=db,
        current_user=_user(10, "ejecutivo"),
    )
    assert _correos(items) == {"colmena@test.cl"}


def test_ejecutivo_no_puede_pedir_cartera_ajena(db):
    with pytest.raises(HTTPException) as exc:
        list_destinatarios(
            empresa="Consalud",
            periodo_carga="",
            limit=5000,
            db=db,
            current_user=_user(10, "ejecutivo"),
        )
    assert exc.value.status_code == 403


def test_ejecutivo_sin_carteras_no_recibe_nada(db):
    """Una lista de carteras vacia nunca debe interpretarse como 'todas'."""
    items = list_destinatarios(
        empresa="",
        periodo_carga="",
        limit=5000,
        db=db,
        current_user=_user(99, "ejecutivo"),
    )
    assert items == []


def test_supervisor_recibe_todas_las_carteras(db):
    items = list_destinatarios(
        empresa="",
        periodo_carga="",
        limit=5000,
        db=db,
        current_user=_user(1, "supervisor"),
    )
    assert _correos(items) == {"colmena@test.cl", "consalud@test.cl"}


def test_reemplazo_temporal_vigente_habilita_la_cartera(db):
    ahora = datetime.now()
    db.execute(
        text(
            """
            INSERT INTO cartera_temporary_replacements
                (id, empresa, replacement_user_id, starts_at, ends_at, is_active)
            VALUES (1, 'Consalud', 10, :desde, :hasta, 1)
            """
        ),
        {"desde": ahora - timedelta(days=1), "hasta": ahora + timedelta(days=1)},
    )
    db.commit()

    items = list_destinatarios(
        empresa="",
        periodo_carga="",
        limit=5000,
        db=db,
        current_user=_user(10, "ejecutivo"),
    )
    assert _correos(items) == {"colmena@test.cl", "consalud@test.cl"}
