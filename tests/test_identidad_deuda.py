import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.deudor_import_service import _detalle_identity_key


def _fila(empresa: str, **campos):
    base = dict(
        empresa=empresa,
        rut_afiliado="12345678",
        nro_expediente="ID-1",
        fecha_emision="01/07/2026",
        monto_cobrar=0.0,
        monto_total=0.0,
        prestador="",
        fecha_prestacion2="",
        copago=0.0,
        cart56_mto_pagar=0.0,
    )
    base.update(campos)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("empresa", ["Consalud", "Cruz Blanca", "Colmena"])
def test_mismo_expediente_con_monto_distinto_es_una_deuda_nueva(empresa):
    """Regla de negocio: misma deuda con monto distinto debe crear otra fila."""
    mes_1 = _detalle_identity_key(_fila(empresa, monto_cobrar=100_000.0))
    mes_2 = _detalle_identity_key(_fila(empresa, monto_cobrar=50_000.0))
    assert mes_1 != mes_2


@pytest.mark.parametrize("empresa", ["Consalud", "Cruz Blanca", "Colmena"])
def test_mismo_expediente_con_mismo_monto_se_mantiene(empresa):
    mes_1 = _detalle_identity_key(_fila(empresa, monto_cobrar=100_000.0))
    mes_2 = _detalle_identity_key(_fila(empresa, monto_cobrar=100_000.0))
    assert mes_1 == mes_2


def test_expediente_distinto_siempre_es_deuda_nueva():
    uno = _detalle_identity_key(_fila("Consalud", nro_expediente="ID-1"))
    dos = _detalle_identity_key(_fila("Consalud", nro_expediente="ID-2"))
    assert uno != dos


def test_cart56_discrimina_por_su_propio_monto():
    uno = _detalle_identity_key(_fila("Cart-56", cart56_mto_pagar=90_000.0))
    dos = _detalle_identity_key(_fila("Cart-56", cart56_mto_pagar=45_000.0))
    assert uno != dos


def test_cart56_usa_copago_cuando_no_hay_monto_a_pagar():
    con_copago = _detalle_identity_key(_fila("Cart-56", cart56_mto_pagar=0.0, copago=70_000.0))
    otro_copago = _detalle_identity_key(_fila("Cart-56", cart56_mto_pagar=0.0, copago=30_000.0))
    assert con_copago != otro_copago


def test_una_cartera_nueva_hereda_la_regla_por_defecto():
    """Una cartera futura no debe quedar sin discriminador por olvido."""
    uno = _detalle_identity_key(_fila("Isapre Nueva", monto_cobrar=100_000.0))
    dos = _detalle_identity_key(_fila("Isapre Nueva", monto_cobrar=80_000.0))
    assert uno != dos
