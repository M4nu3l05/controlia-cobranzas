from __future__ import annotations

import hashlib
import sys
from datetime import date
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
from app.models.debtor_assignment import DebtorUserAssignment
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion
from app.models.operations import DebtorBirladoTransition, DebtorImportBatch
from app.models.payment import PaymentAllocation, PaymentTransaction
from app.models.user import User
from app.services.deudor_import_service import (
    import_deudores_excel_service,
    preview_deudores_excel_service,
    remove_import_missing_cases_service,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def _user(db: Session) -> User:
    user = User(
        username="supervisora_politicas",
        email="supervisora.politicas@example.test",
        password_hash="x",
        salt="x",
        role="supervisor",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _xlsx(rows: list[dict]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Hoja1", index=False)
    return output.getvalue()


def _cb(rut: str, folio: str, monto: int) -> dict:
    return {
        "Mandante": "CruzBlanca", "RUT_Deudor": rut, "Nombre_Deudor": "Persona Ficticia",
        "Estado_Gestion": "SIN PAGO", "ID_Deuda": folio, "Fecha_Emision_Deuda": "2026-01-10",
        "Fecha_Vencimiento_Deuda": "2026-02-10", "Monto_Cobrar": monto,
        "Ejecutiva": "supervisora_politicas",
    }


def _colmena(rut: str, folio: str, monto: int) -> dict:
    return {
        "Mandante": "Colmena", "RUT_Deudor": rut, "Nombre_Deudor": "Persona Ficticia",
        "Estado_Caso": "SIN PAGO", "ID_Deuda": folio, "Fecha_Emision": "2026-01-10",
        "Fecha_Prestacion": "2026-01-05", "Monto_Cobrar": monto,
        "Ejecutiva": "supervisora_politicas",
    }


def _importar(db: Session, user: User, empresa: str, rows: list[dict], nombre: str) -> dict:
    content = _xlsx(rows)
    return import_deudores_excel_service(
        db,
        empresa=empresa,
        content=content,
        source_file=nombre,
        executor=user,
        expected_file_sha256=hashlib.sha256(content).hexdigest(),
        confirm_birlados=False,
    )


def _detalles(db: Session, empresa: str, folio: str) -> list[DeudorDetalle]:
    return (
        db.query(DeudorDetalle)
        .filter(DeudorDetalle.empresa == empresa, DeudorDetalle.id_deuda == folio)
        .order_by(DeudorDetalle.id)
        .all()
    )


def _pagar(db: Session, user: User, detalle: DeudorDetalle, key: str) -> None:
    transaction = PaymentTransaction(
        public_id=f"00000000-0000-4000-8000-{key.rjust(12, '0')}",
        idempotency_key=f"pago-{key}",
        empresa=detalle.empresa,
        rut_afiliado=detalle.rut_afiliado,
        payment_type="Pago",
        amount_clp=10,
        effective_date=date(2026, 10, 1),
        registered_by_user_id=user.id,
        registered_by_username=user.username,
    )
    db.add(transaction)
    db.flush()
    db.add(PaymentAllocation(
        transaction_id=transaction.id,
        deudor_detalle_id=detalle.id,
        expediente=detalle.nro_expediente,
        amount_clp=10,
        balance_before_clp=int(detalle.saldo_actual),
        balance_after_clp=int(detalle.saldo_actual),
    ))
    db.commit()


def test_cruz_blanca_es_solo_flujo_y_actualiza_monto_por_folio():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, "Cruz Blanca", [
            _cb("11.111.111-1", "CB-1", 1000),
            _cb("11.111.111-1", "CB-2", 2000),
            _cb("22.222.222-2", "CB-3", 3000),
        ], "cb_202609.xlsx")

        result = _importar(db, user, "Cruz Blanca", [
            _cb("11.111.111-1", "CB-1", 1000),
            _cb("11.111.111-1", "CB-2", 2500),
            _cb("33.333.333-3", "CB-4", 4000),
        ], "cb_202610.xlsx")

        assert result["politica_ausentes"] == "keep"
        assert result["detalle_nuevos"] == 1
        assert result["montos_actualizados"] == 1
        assert result["detalle_omitidos"] == 1
        assert result["detalle_birlados"] == 0
        assert result["no_informados"] == []
        assert result["diferencias_monto"][0]["monto_anterior"] == 2000
        assert result["diferencias_monto"][0]["aplicado"] is True

        ausente = _detalles(db, "Cruz Blanca", "CB-3")
        assert len(ausente) == 1 and ausente[0].is_active
        assert ausente[0].estado_deudor != "Birlado"
        assert db.query(DebtorBirladoTransition).count() == 0

        actualizado = _detalles(db, "Cruz Blanca", "CB-2")
        assert len(actualizado) == 1
        assert actualizado[0].monto_cobrar == 2500
        assert actualizado[0].saldo_actual == 2500

        resumen = db.query(DeudorResumen).filter_by(empresa="Cruz Blanca", rut_afiliado="11111111").one()
        assert resumen.saldo_actual == 3500
        ruts_resumen = {row.rut_afiliado for row in db.query(DeudorResumen).filter_by(empresa="Cruz Blanca")}
        assert ruts_resumen == {"11111111", "22222222", "33333333"}


def test_monto_distinto_con_pagos_no_se_actualiza():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, "Cruz Blanca", [_cb("11.111.111-1", "CB-1", 1000)], "cb_202609.xlsx")
        _pagar(db, user, _detalles(db, "Cruz Blanca", "CB-1")[0], "1")

        result = _importar(db, user, "Cruz Blanca", [_cb("11.111.111-1", "CB-1", 800)], "cb_202610.xlsx")

        assert result["montos_actualizados"] == 0
        assert result["montos_no_actualizados_por_pagos"] == 1
        assert result["diferencias_monto"][0]["aplicado"] is False
        assert _detalles(db, "Cruz Blanca", "CB-1")[0].monto_cobrar == 1000


def test_colmena_informa_no_informados_y_los_elimina_al_confirmar():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, "Colmena", [
            _colmena("11.111.111-1", "F-1", 1000),
            _colmena("11.111.111-1", "F-2", 2000),
            _colmena("22.222.222-2", "F-3", 3000),
            _colmena("33.333.333-3", "F-4", 4000),
        ], "colmena_202609.xlsx")
        _pagar(db, user, _detalles(db, "Colmena", "F-4")[0], "4")
        db.add(DeudorGestion(empresa="Colmena", rut_afiliado="22222222", estado="Contactado"))
        db.commit()

        segunda = [_colmena("11.111.111-1", "F-1", 1000), _colmena("44.444.444-4", "F-5", 5000)]
        content = _xlsx(segunda)
        preview = preview_deudores_excel_service(
            db, empresa="Colmena", content=content, source_file="colmena_202610.xlsx"
        )
        assert preview["politica_ausentes"] == "remove_after_confirm"
        assert preview["no_informados_estimados"] == 3
        assert preview["birlados"] == []

        result = _importar(db, user, "Colmena", segunda, "colmena_202610.xlsx")
        no_informados = {row["folio"]: row for row in result["no_informados"]}
        assert set(no_informados) == {"F-2", "F-3", "F-4"}
        assert no_informados["F-4"]["tiene_pagos"] is True
        assert all(row.is_active for folio in ("F-2", "F-3", "F-4") for row in _detalles(db, "Colmena", folio))

        removal = remove_import_missing_cases_service(
            db,
            batch_id=result["import_batch_id"],
            detalle_ids=[row["detalle_id"] for row in result["no_informados"]],
        )

        assert removal["eliminados"] == 2
        assert removal["archivados_por_pagos"] == 1
        assert _detalles(db, "Colmena", "F-2") == []
        assert _detalles(db, "Colmena", "F-3") == []
        archivado = _detalles(db, "Colmena", "F-4")[0]
        assert not archivado.is_active and archivado.estado_deudor == "Base eliminada"
        assert _detalles(db, "Colmena", "F-1")[0].is_active

        ruts_resumen = {row.rut_afiliado for row in db.query(DeudorResumen).filter_by(empresa="Colmena")}
        assert ruts_resumen == {"11111111", "44444444"}
        asignaciones = {row.rut_afiliado for row in db.query(DebtorUserAssignment).filter_by(empresa="Colmena")}
        assert asignaciones == {"11111111", "44444444"}
        assert db.query(DeudorGestion).filter_by(rut_afiliado="22222222").count() == 1
        assert db.get(DebtorImportBatch, result["import_batch_id"]).removed_count == 3


def test_eliminacion_rechaza_casos_informados_cartera_sin_politica_y_carga_antigua():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        _importar(db, user, "Colmena", [
            _colmena("11.111.111-1", "F-1", 1000),
            _colmena("22.222.222-2", "F-2", 2000),
        ], "colmena_202609.xlsx")
        result = _importar(db, user, "Colmena", [_colmena("11.111.111-1", "F-1", 1500)], "colmena_202610.xlsx")
        informado_id = _detalles(db, "Colmena", "F-1")[0].id

        with pytest.raises(ValueError, match="ya no corresponden"):
            remove_import_missing_cases_service(db, batch_id=result["import_batch_id"], detalle_ids=[informado_id])

        cb = _importar(db, user, "Cruz Blanca", [_cb("11.111.111-1", "CB-1", 1000)], "cb_202610.xlsx")
        with pytest.raises(ValueError, match="no aplica"):
            remove_import_missing_cases_service(db, batch_id=cb["import_batch_id"], detalle_ids=[informado_id])

        _importar(db, user, "Colmena", [
            _colmena("11.111.111-1", "F-1", 1500),
            _colmena("55.555.555-5", "F-6", 6000),
        ], "colmena_202611.xlsx")
        with pytest.raises(ValueError, match="más reciente"):
            remove_import_missing_cases_service(
                db,
                batch_id=result["import_batch_id"],
                detalle_ids=[row["detalle_id"] for row in result["no_informados"]],
            )
        assert _detalles(db, "Colmena", "F-2")[0].is_active


def test_folios_duplicados_historicos_no_se_duplican_ni_se_informan_ausentes():
    with Session(_engine(), autoflush=False) as db:
        user = _user(db)
        for monto in (1000, 1200):
            db.add(DeudorDetalle(
                empresa="Colmena", rut_afiliado="11111111", dv="1", rut_completo="11111111-1",
                nombre_afiliado="Persona Ficticia", nro_expediente="F-9", id_deuda="F-9",
                copago=monto, saldo_actual=monto, monto_cobrar=monto, source_file="historica.xlsx",
            ))
        # Sin resumen, la reparacion de estado inconsistente descartaria los detalles.
        db.add(DeudorResumen(
            empresa="Colmena", rut_afiliado="11111111", dv="1", rut_completo="11111111-1",
            nombre_afiliado="Persona Ficticia", source_file="historica.xlsx",
        ))
        db.commit()

        result = _importar(db, user, "Colmena", [
            _colmena("11.111.111-1", "F-9", 1300),
            _colmena("22.222.222-2", "F-10", 500),
        ], "colmena_202610.xlsx")

        filas = _detalles(db, "Colmena", "F-9")
        assert len(filas) == 2
        assert [fila.monto_cobrar for fila in filas] == [1000, 1300]
        assert result["no_informados"] == []


def test_reporte_de_no_informados(tmp_path):
    pytest.importorskip("PyQt6")
    from admin_carteras.data_operations import _no_informados_report_frame
    from core.excel_export import write_excel_report

    frame = _no_informados_report_frame([{
        "detalle_id": 7, "rut_afiliado": "11111111", "rut_completo": "11111111-1",
        "nombre_afiliado": "Persona Ficticia", "folio": "F-1", "fecha_emision": "10/01/2026",
        "monto_cobrar": 1000.0, "saldo_actual": 1000.0, "estado_deudor": "Sin Gestión",
        "tiene_pagos": True,
    }])

    assert list(frame.columns) == [
        "RUT", "Nombre", "Folio cuenta", "Fecha emisión", "Monto a cobrar",
        "Saldo actual", "Estado", "Tiene pagos",
    ]
    assert frame.iloc[0]["Tiene pagos"] == "Sí"

    path = tmp_path / "no_informados.xlsx"
    write_excel_report(str(path), {"No informados": frame})
    leido = pd.read_excel(path, sheet_name="No informados", dtype=str)
    assert leido.iloc[0]["Folio cuenta"] == "F-1"
