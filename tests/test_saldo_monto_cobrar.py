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

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401
from app.db.session import Base
from app.models.debtor_assignment import DebtorUserAssignment  # noqa: F401
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion  # noqa: F401
from app.models.operations import DebtorBirladoTransition, DebtorImportBatch  # noqa: F401
from app.models.payment import PaymentAllocation, PaymentTransaction  # noqa: F401
from app.models.user import User
from app.services.deudor_import_service import (
    import_deudores_excel_service,
    reparar_saldos_desincronizados,
)
from app.services.deudor_service import _recalcular_resumen_desde_detalle


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def _user(db: Session) -> User:
    user = User(
        username="supervisora_saldos",
        email="supervisora.saldos@example.test",
        password_hash="x",
        salt="x",
        role="supervisor",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _colmena(rut: str, folio: str, monto: int) -> dict:
    return {
        "Mandante": "Colmena", "RUT_Deudor": rut, "Nombre_Deudor": "Persona Ficticia",
        "Estado_Caso": "SIN PAGO", "ID_Deuda": folio, "Fecha_Emision": "2026-01-10",
        "Fecha_Prestacion": "2026-01-05", "Monto_Cobrar": monto,
        "Ejecutiva": "supervisora_saldos",
    }


def _importar(db: Session, user: User, rows: list[dict], nombre: str) -> dict:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Hoja1", index=False)
    content = output.getvalue()
    return import_deudores_excel_service(
        db,
        empresa="Colmena",
        content=content,
        source_file=nombre,
        executor=user,
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
        confirm_birlados=False,
    )


def _detalle(db: Session, folio: str) -> DeudorDetalle:
    return db.query(DeudorDetalle).filter(DeudorDetalle.id_deuda == folio).one()


def _resumen(db: Session, rut: str = "11111111") -> DeudorResumen:
    return db.query(DeudorResumen).filter(DeudorResumen.rut_afiliado == rut).one()


def _abonar(db: Session, detalle: DeudorDetalle, monto: float) -> None:
    detalle.total_pagos = float(detalle.total_pagos or 0) + monto
    detalle.saldo_actual = float(detalle.saldo_actual or 0) - monto
    db.commit()


def _retirar(db: Session, detalle: DeudorDetalle) -> None:
    detalle.is_active = False
    detalle.estado_deudor = "Birlado"
    db.commit()


@pytest.mark.parametrize(
    ("monto_nuevo", "pago", "saldo_esperado"),
    [
        (1_200_000, 100_000, 1_100_000),  # caso reportado
        (1_200_000, 0, 1_200_000),        # sin pagos: saldo = monto
        (50_000, 100_000, 0),             # pagos superan el monto nuevo
    ],
)
def test_reactivacion_con_monto_distinto_recalcula_saldo(monto_nuevo, pago, saldo_esperado):
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, [_colmena("11.111.111-1", "F-1", 1_400_000)], "colmena_202609.xlsx")
        detalle = _detalle(db, "F-1")
        if pago:
            _abonar(db, detalle, pago)
        _retirar(db, detalle)

        _importar(db, user, [_colmena("11.111.111-1", "F-1", monto_nuevo)], "colmena_202610.xlsx")

        detalle = _detalle(db, "F-1")
        assert detalle.is_active
        assert detalle.monto_cobrar == monto_nuevo
        assert detalle.copago == monto_nuevo
        assert detalle.total_pagos == pago
        assert detalle.saldo_actual == saldo_esperado
        resumen = _resumen(db)
        assert resumen.copago == monto_nuevo
        assert resumen.saldo_actual == saldo_esperado


def test_saldo_resumen_es_suma_de_deudas():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, [
            _colmena("11.111.111-1", "F-1", 1_000_000),
            _colmena("11.111.111-1", "F-2", 500_000),
        ], "colmena_202609.xlsx")
        _abonar(db, _detalle(db, "F-1"), 200_000)

        _recalcular_resumen_desde_detalle(db, empresa="Colmena", rut_norm="11111111")

        resumen = _resumen(db)
        assert resumen.copago == 1_500_000
        assert resumen.total_pagos == 200_000
        assert resumen.saldo_actual == 1_300_000


def test_reparacion_corrige_detalle_desincronizado_y_es_idempotente():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, [_colmena("11.111.111-1", "F-1", 1_400_000)], "colmena_202609.xlsx")
        detalle = _detalle(db, "F-1")
        # Estado previo a la correccion: monto actualizado, copago y saldo con el monto anterior.
        detalle.monto_cobrar = 1_200_000
        _abonar(db, detalle, 100_000)
        _recalcular_resumen_desde_detalle(db, empresa="Colmena", rut_norm="11111111")
        db.commit()
        assert _resumen(db).saldo_actual == 1_300_000

        assert reparar_saldos_desincronizados(db) == 1
        assert reparar_saldos_desincronizados(db) == 0

        detalle = _detalle(db, "F-1")
        assert (detalle.copago, detalle.total_pagos, detalle.saldo_actual) == (1_200_000, 100_000, 1_100_000)
        resumen = _resumen(db)
        assert (resumen.copago, resumen.total_pagos, resumen.saldo_actual) == (1_200_000, 100_000, 1_100_000)


def test_resumen_tras_pago_ignora_deudas_retiradas():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, [
            _colmena("11.111.111-1", "F-1", 1_000_000),
            _colmena("11.111.111-1", "F-2", 500_000),
        ], "colmena_202609.xlsx")
        _retirar(db, _detalle(db, "F-2"))
        _abonar(db, _detalle(db, "F-1"), 100_000)

        _recalcular_resumen_desde_detalle(db, empresa="Colmena", rut_norm="11111111")

        resumen = _resumen(db)
        assert resumen.copago == 1_000_000
        assert resumen.saldo_actual == 900_000
