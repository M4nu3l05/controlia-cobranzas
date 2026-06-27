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
from app.models.operations import DebtorBirladoTransition, DebtorImportBatch
from app.models.user import User
from app.services.deudor_import_service import (
    import_deudores_excel_service,
    preview_deudores_excel_service,
)


def _excel_cart56() -> bytes:
    df = pd.DataFrame([
        {"RUT Emp": "12.345.678-5", "No Licencia": "LIC-1", "Mto Pagar": "10000"},
    ])
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()


def test_preview_is_read_only_and_confirm_marks_missing_as_birlado():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    content = _excel_cart56()

    with Session(engine) as db:
        supervisor = User(
            username="supervisor_prueba", email="supervisor@example.test",
            password_hash="x", salt="x", role="supervisor", is_active=True,
        )
        db.add(supervisor)
        db.flush()
        db.add_all([
            DeudorDetalle(
                empresa="Cart-56", rut_afiliado="12345678", dv="5",
                rut_completo="12345678-5", nombre_afiliado="Empresa Uno",
                nro_expediente="LIC-1", copago=10000, saldo_actual=10000,
                cart56_mto_pagar=10000, is_active=True,
            ),
            DeudorDetalle(
                empresa="Cart-56", rut_afiliado="9999999", dv="9",
                rut_completo="9999999-9", nombre_afiliado="Empresa Retirada",
                nro_expediente="LIC-2", copago=20000, saldo_actual=15000,
                cart56_mto_pagar=20000, estado_deudor="Contactado", is_active=True,
            ),
            DeudorResumen(
                empresa="Cart-56", rut_afiliado="12345678", dv="5",
                rut_completo="12345678-5", nombre_afiliado="Empresa Uno",
                estado_deudor="Sin Gestión", copago=10000, saldo_actual=10000,
            ),
            DeudorResumen(
                empresa="Cart-56", rut_afiliado="9999999", dv="9",
                rut_completo="9999999-9", nombre_afiliado="Empresa Retirada",
                estado_deudor="Contactado", copago=20000, saldo_actual=15000,
            ),
        ])
        db.commit()

        preview = preview_deudores_excel_service(
            db, empresa="Cart-56", content=content, source_file="junio_2026.xlsx"
        )
        assert len(preview["birlados"]) == 1
        assert preview["birlados"][0]["nro_expediente"] == "LIC-2"
        assert db.query(DeudorDetalle).filter(DeudorDetalle.is_active.is_(True)).count() == 2

        result = import_deudores_excel_service(
            db,
            empresa="Cart-56",
            content=content,
            source_file="junio_2026.xlsx",
            executor=supervisor,
            expected_file_sha256=hashlib.sha256(content).hexdigest(),
            confirm_birlados=True,
        )

        retired = db.query(DeudorDetalle).filter(DeudorDetalle.nro_expediente == "LIC-2").one()
        assert retired.is_active is False
        assert retired.estado_deudor == "Birlado"
        assert result["detalle_birlados"] == 1
        assert db.query(DebtorImportBatch).count() == 1
        assert db.query(DebtorBirladoTransition).count() == 1
        resumen = db.query(DeudorResumen).filter(DeudorResumen.rut_afiliado == "9999999").one()
        assert resumen.estado_deudor == "Birlado"


def test_confirmation_rejects_a_file_different_from_preview():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    content = _excel_cart56()
    with Session(engine) as db:
        supervisor = User(
            username="supervisor_prueba", email="supervisor@example.test",
            password_hash="x", salt="x", role="supervisor", is_active=True,
        )
        db.add(supervisor)
        db.commit()
        with pytest.raises(ValueError, match="cambió después de la vista previa"):
            import_deudores_excel_service(
                db, empresa="Cart-56", content=content, source_file="junio_2026.xlsx",
                executor=supervisor, expected_file_sha256="0" * 64, confirm_birlados=True,
            )
