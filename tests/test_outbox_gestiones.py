import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deudores import outbox


@pytest.fixture(autouse=True)
def db_temporal(tmp_path, monkeypatch):
    """Aisla la cola en un archivo desechable por test."""
    destino = tmp_path / "db_outbox.sqlite"
    monkeypatch.setattr(outbox, "_db_path", lambda: str(destino))
    yield destino


def _encolar(user_id: int = 7, rut: str = "11111111", **extra) -> int:
    datos = dict(
        user_id=user_id,
        rut=rut,
        empresa="Colmena",
        nombre_afiliado="Afiliado Prueba",
        tipo_gestion="Llamada",
        estado="Sin Respuesta",
        fecha_gestion="08/08/2026",
        observacion="Llamada sin contacto",
    )
    datos.update(extra)
    return outbox.encolar_gestion(**datos)


def test_gestion_encolada_queda_pendiente():
    _encolar()
    assert outbox.contar_pendientes(7) == 1

    pendientes = outbox.listar_pendientes(7)
    assert len(pendientes) == 1
    assert pendientes[0].rut == "11111111"
    assert pendientes[0].observacion == "Llamada sin contacto"
    assert pendientes[0].intentos == 0


def test_la_cola_sobrevive_al_cierre_de_la_aplicacion():
    """El dato debe estar en disco, no en memoria: es todo el punto de la cola."""
    _encolar()
    # Cada llamada abre y cierra su propia conexion, igual que tras reiniciar.
    assert outbox.contar_pendientes(7) == 1
    assert outbox.contar_pendientes(7) == 1


def test_sincronizar_elimina_de_la_cola():
    pendiente_id = _encolar()
    outbox.marcar_sincronizada(pendiente_id)
    assert outbox.contar_pendientes(7) == 0
    assert outbox.listar_pendientes(7) == []


def test_cada_usuario_solo_ve_su_propia_cola():
    _encolar(user_id=7, rut="11111111")
    _encolar(user_id=8, rut="22222222")

    assert outbox.contar_pendientes(7) == 1
    assert outbox.contar_pendientes(8) == 1
    assert outbox.listar_pendientes(7)[0].rut == "11111111"
    assert outbox.listar_pendientes(8)[0].rut == "22222222"


def test_error_incrementa_intentos_sin_borrar_la_gestion():
    pendiente_id = _encolar()
    outbox.registrar_error(pendiente_id, "El servidor rechazo la gestion.")

    pendientes = outbox.listar_pendientes(7)
    assert len(pendientes) == 1
    assert pendientes[0].intentos == 1
    assert "rechazo" in pendientes[0].ultimo_error


def test_al_agotar_reintentos_sale_de_pendientes_pero_no_se_pierde():
    pendiente_id = _encolar()
    for _ in range(outbox.MAX_INTENTOS):
        outbox.registrar_error(pendiente_id, "fallo")

    assert outbox.contar_pendientes(7) == 0
    assert outbox.contar_agotadas(7) == 1
    # Sigue existiendo: nunca se descarta trabajo de la ejecutiva.
    assert len(outbox.listar_pendientes(7, incluir_agotadas=True)) == 1


def test_reiniciar_intentos_rehabilita_las_agotadas():
    pendiente_id = _encolar()
    for _ in range(outbox.MAX_INTENTOS):
        outbox.registrar_error(pendiente_id, "fallo")

    assert outbox.reiniciar_intentos(7) == 1
    assert outbox.contar_pendientes(7) == 1
    assert outbox.contar_agotadas(7) == 0


def test_observacion_larga_no_rompe_el_registro_de_error():
    pendiente_id = _encolar()
    outbox.registrar_error(pendiente_id, "x" * 5000)
    assert len(outbox.listar_pendientes(7)[0].ultimo_error) <= 500
