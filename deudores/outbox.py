# ================================================================
#  deudores/outbox.py
#  Cola local de gestiones pendientes de enviar al backend.
#  Protege el trabajo de la ejecutiva ante cortes de red o de luz.
#  Los datos personales quedan cifrados en reposo (ver core/secret_store).
# ================================================================

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir
from core.secret_store import desproteger, proteger

logger = logging.getLogger(__name__)

TABLA = "gestiones_pendientes"

# Tope de reintentos automaticos. Al superarlo la fila queda para revision
# manual en vez de reintentarse indefinidamente contra un backend que la
# rechaza por motivos de negocio (por ejemplo, permisos revocados).
MAX_INTENTOS = 5


@dataclass
class GestionPendiente:
    id: int
    user_id: int
    rut: str
    empresa: str
    nombre_afiliado: str
    tipo_gestion: str
    estado: str
    fecha_gestion: str
    observacion: str
    origen: str
    assigned_to_user_id: int | None
    creado_en: str
    intentos: int
    ultimo_error: str


def _db_path() -> str:
    # Base propia: no debe compartir archivo con la cache de deudores para que
    # una limpieza de datos no elimine trabajo que aun no llega al backend.
    return os.path.join(str(get_data_dir()), "db_outbox.sqlite")


def _migration_create(con: sqlite3.Connection) -> None:
    # rut, nombre_afiliado y observacion se guardan cifrados (BLOB).
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER NOT NULL,
            rut                 BLOB    NOT NULL,
            empresa             TEXT    NOT NULL DEFAULT '',
            nombre_afiliado     BLOB,
            tipo_gestion        TEXT    NOT NULL DEFAULT '',
            estado              TEXT    NOT NULL DEFAULT '',
            fecha_gestion       TEXT    NOT NULL DEFAULT '',
            observacion         BLOB,
            origen              TEXT    NOT NULL DEFAULT 'manual',
            assigned_to_user_id INTEGER NULL,
            creado_en           TEXT    NOT NULL,
            intentos            INTEGER NOT NULL DEFAULT 0,
            ultimo_intento_en   TEXT    NOT NULL DEFAULT '',
            ultimo_error        TEXT    NOT NULL DEFAULT ''
        )
        """
    )


def _migration_indexes(con: sqlite3.Connection) -> None:
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_user ON {TABLA}(user_id)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_intentos ON {TABLA}(intentos)")


MIGRATIONS = [
    Migration(1, "Create gestiones_pendientes table", _migration_create),
    Migration(2, "Create gestiones_pendientes indexes", _migration_indexes),
]


@contextmanager
def _con():
    """Abre la base, confirma la transaccion y cierra siempre la conexion.

    `with sqlite3.connect(...)` solo delimita la transaccion: no cierra el
    archivo. Como la app consulta la cola de forma periodica y permanece
    abierta toda la jornada, dejar la conexion viva filtraria descriptores.
    """
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        apply_migrations(con, MIGRATIONS)
        with con:
            yield con
    finally:
        con.close()


def _ahora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def encolar_gestion(
    *,
    user_id: int,
    rut: str,
    empresa: str,
    nombre_afiliado: str,
    tipo_gestion: str,
    estado: str,
    fecha_gestion: str,
    observacion: str = "",
    origen: str = "manual",
    assigned_to_user_id: int | None = None,
) -> int:
    """Guarda una gestion que no pudo enviarse al backend. Devuelve su id local."""
    with _con() as con:
        cur = con.execute(
            f"""
            INSERT INTO {TABLA} (
                user_id, rut, empresa, nombre_afiliado, tipo_gestion, estado,
                fecha_gestion, observacion, origen, assigned_to_user_id, creado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                proteger(str(rut).strip()),
                str(empresa).strip(),
                proteger(str(nombre_afiliado).strip()),
                str(tipo_gestion).strip(),
                str(estado).strip(),
                str(fecha_gestion).strip(),
                proteger(str(observacion).strip()),
                str(origen).strip() or "manual",
                int(assigned_to_user_id) if assigned_to_user_id is not None else None,
                _ahora(),
            ),
        )
        return int(cur.lastrowid)


def _fila_a_pendiente(r: sqlite3.Row) -> GestionPendiente:
    return GestionPendiente(
        id=int(r["id"]),
        user_id=int(r["user_id"]),
        rut=desproteger(r["rut"]),
        empresa=r["empresa"],
        nombre_afiliado=desproteger(r["nombre_afiliado"]),
        tipo_gestion=r["tipo_gestion"],
        estado=r["estado"],
        fecha_gestion=r["fecha_gestion"],
        observacion=desproteger(r["observacion"]),
        origen=r["origen"],
        assigned_to_user_id=r["assigned_to_user_id"],
        creado_en=r["creado_en"],
        intentos=int(r["intentos"]),
        ultimo_error=r["ultimo_error"],
    )


def listar_pendientes(user_id: int, *, incluir_agotadas: bool = False) -> list[GestionPendiente]:
    filtro = "" if incluir_agotadas else f"AND intentos < {MAX_INTENTOS}"
    with _con() as con:
        rows = con.execute(
            f"""
            SELECT * FROM {TABLA}
            WHERE user_id = ? {filtro}
            ORDER BY id ASC
            """,
            (int(user_id),),
        ).fetchall()
    return [_fila_a_pendiente(r) for r in rows]


def contar_pendientes(user_id: int) -> int:
    with _con() as con:
        row = con.execute(
            f"SELECT COUNT(*) FROM {TABLA} WHERE user_id = ? AND intentos < {MAX_INTENTOS}",
            (int(user_id),),
        ).fetchone()
    return int(row[0] or 0)


def contar_agotadas(user_id: int) -> int:
    """Gestiones que agotaron los reintentos y requieren revision manual."""
    with _con() as con:
        row = con.execute(
            f"SELECT COUNT(*) FROM {TABLA} WHERE user_id = ? AND intentos >= {MAX_INTENTOS}",
            (int(user_id),),
        ).fetchone()
    return int(row[0] or 0)


def marcar_sincronizada(pendiente_id: int) -> None:
    with _con() as con:
        con.execute(f"DELETE FROM {TABLA} WHERE id = ?", (int(pendiente_id),))


def registrar_error(pendiente_id: int, error: str) -> None:
    with _con() as con:
        con.execute(
            f"""
            UPDATE {TABLA}
            SET intentos = intentos + 1,
                ultimo_intento_en = ?,
                ultimo_error = ?
            WHERE id = ?
            """,
            (_ahora(), str(error or "")[:500], int(pendiente_id)),
        )


def reiniciar_intentos(user_id: int) -> int:
    """Vuelve a habilitar las gestiones agotadas para un nuevo intento manual."""
    with _con() as con:
        cur = con.execute(
            f"UPDATE {TABLA} SET intentos = 0, ultimo_error = '' WHERE user_id = ? AND intentos >= {MAX_INTENTOS}",
            (int(user_id),),
        )
        return int(cur.rowcount or 0)
