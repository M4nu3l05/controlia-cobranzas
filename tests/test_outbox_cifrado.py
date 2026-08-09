import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import secret_store
from deudores import outbox

WINDOWS = sys.platform == "win32"


@pytest.fixture(autouse=True)
def db_temporal(tmp_path, monkeypatch):
    destino = tmp_path / "db_outbox.sqlite"
    monkeypatch.setattr(outbox, "_db_path", lambda: str(destino))
    yield destino


def test_ida_y_vuelta_conserva_el_texto():
    original = "Deudor con acentuación y ñ, RUT 12.345.678-9"
    assert secret_store.desproteger(secret_store.proteger(original)) == original


def test_texto_vacio_no_rompe():
    assert secret_store.desproteger(secret_store.proteger("")) == ""
    assert secret_store.desproteger(None) == ""


def test_valor_previo_sin_cifrar_sigue_siendo_legible():
    """Registros escritos antes del cifrado no deben perderse."""
    assert secret_store.desproteger(b"gestion antigua") == "gestion antigua"


@pytest.mark.skipif(not WINDOWS, reason="DPAPI solo existe en Windows")
def test_en_windows_el_cifrado_esta_disponible():
    assert secret_store.cifrado_disponible() is True


@pytest.mark.skipif(not WINDOWS, reason="DPAPI solo existe en Windows")
def test_el_rut_no_queda_en_texto_plano_en_el_archivo(db_temporal):
    """La prueba central: abrir el archivo en crudo no debe revelar al deudor."""
    outbox.encolar_gestion(
        user_id=3,
        rut="18765432",
        empresa="Colmena",
        nombre_afiliado="Juana Perez Soto",
        tipo_gestion="Llamada",
        estado="Sin Respuesta",
        fecha_gestion="08/08/2026",
        observacion="Deudora indica que pagara el viernes",
    )

    crudo = Path(db_temporal).read_bytes()

    assert b"18765432" not in crudo
    assert "Juana Perez Soto".encode("utf-8") not in crudo
    assert "pagara el viernes".encode("utf-8") not in crudo
    # La app si debe poder leerlo de vuelta.
    assert outbox.listar_pendientes(3)[0].rut == "18765432"
    assert outbox.listar_pendientes(3)[0].observacion == "Deudora indica que pagara el viernes"


@pytest.mark.skipif(not WINDOWS, reason="DPAPI solo existe en Windows")
def test_dato_cifrado_por_otra_entropia_no_se_puede_leer(monkeypatch):
    """El blob queda atado a esta aplicacion, no solo al usuario de Windows."""
    protegido = secret_store.proteger("dato sensible")
    monkeypatch.setattr(secret_store, "_ENTROPIA", b"otra-aplicacion")
    assert secret_store.desproteger(protegido) == ""
