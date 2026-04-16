from __future__ import annotations

import datetime
import logging
import os
import sqlite3

import pandas as pd

from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir

logger = logging.getLogger(__name__)

TABLA = "email_history"


def _db_path() -> str:
    return os.path.join(str(get_data_dir()), "db_envios_historial.sqlite")


def _migration_create_history(con: sqlite3.Connection) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_evento TEXT NOT NULL,
            rut TEXT,
            nombre TEXT,
            email TEXT,
            asunto TEXT,
            plantilla TEXT,
            estado TEXT,
            detalle TEXT,
            origen TEXT
        )
        """
    )


def _migration_indexes(con: sqlite3.Connection) -> None:
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_rut ON {TABLA}(rut)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_email ON {TABLA}(email)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_fecha ON {TABLA}(fecha_evento)")


MIGRATIONS = [
    Migration(1, "Create email history table", _migration_create_history),
    Migration(2, "Create email history indexes", _migration_indexes),
]


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.execute("PRAGMA foreign_keys = ON")
    apply_migrations(con, MIGRATIONS)
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_evento TEXT NOT NULL,
            rut TEXT,
            nombre TEXT,
            email TEXT,
            asunto TEXT,
            plantilla TEXT,
            estado TEXT,
            detalle TEXT,
            origen TEXT
        )
        """
    )
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_rut ON {TABLA}(rut)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_email ON {TABLA}(email)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_fecha ON {TABLA}(fecha_evento)")
    con.commit()
    return con


def registrar_historial_envio(
    rut: str,
    nombre: str,
    email: str,
    asunto: str,
    plantilla: str,
    estado: str,
    detalle: str,
    origen: str = "detalle_deudor",
) -> int:
    fecha_evento = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        cur = con.execute(
            f"""
            INSERT INTO {TABLA}
            (fecha_evento, rut, nombre, email, asunto, plantilla, estado, detalle, origen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fecha_evento).strip(),
                str(rut).strip(),
                str(nombre).strip(),
                str(email).strip(),
                str(asunto).strip(),
                str(plantilla).strip(),
                str(estado).strip(),
                str(detalle).strip(),
                str(origen).strip(),
            ),
        )
        con.commit()
        return int(cur.lastrowid)


def cargar_historial_envios(limit: int = 200) -> pd.DataFrame:
    if not os.path.exists(_db_path()):
        return pd.DataFrame()

    try:
        with _con() as con:
            return pd.read_sql(
                f"""
                SELECT id, fecha_evento, rut, nombre, email, asunto, plantilla, estado, detalle, origen
                FROM {TABLA}
                ORDER BY fecha_evento DESC, id DESC
                LIMIT ?
                """,
                con,
                params=(limit,),
                dtype=str,
            ).fillna("")
    except Exception:
        logger.exception("No se pudo cargar el historial de envíos")
        return pd.DataFrame()