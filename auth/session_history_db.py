from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Optional

import pandas as pd

from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir

TABLA = "session_history"


def _db_path() -> str:
    return os.path.join(str(get_data_dir()), "db_session_history.sqlite")


def _m1_create_table(con: sqlite3.Connection) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            login_at TEXT NOT NULL,
            logout_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_user ON {TABLA}(user_id)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_login ON {TABLA}(login_at)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_role ON {TABLA}(role)")


MIGRATIONS = [
    Migration(1, "Create session history table", _m1_create_table),
]


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.execute("PRAGMA foreign_keys = ON")
    apply_migrations(con, MIGRATIONS)
    _m1_create_table(con)
    con.commit()
    return con


def register_login(session) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        cur = con.execute(
            f"""
            INSERT INTO {TABLA}(user_id, email, username, role, login_at, logout_at, created_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                int(session.user_id),
                str(session.email),
                str(session.username),
                str(session.role),
                now,
                now,
            ),
        )
        con.commit()
        return int(cur.lastrowid)


def close_session(session_id: Optional[int] = None, user_id: Optional[int] = None) -> bool:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        if session_id:
            cur = con.execute(
                f"UPDATE {TABLA} SET logout_at=? WHERE id=? AND logout_at IS NULL",
                (now, int(session_id)),
            )
            con.commit()
            if cur.rowcount:
                return True

        if user_id is not None:
            row = con.execute(
                f"SELECT id FROM {TABLA} WHERE user_id=? AND logout_at IS NULL ORDER BY id DESC LIMIT 1",
                (int(user_id),),
            ).fetchone()
            if row:
                cur = con.execute(
                    f"UPDATE {TABLA} SET logout_at=? WHERE id=? AND logout_at IS NULL",
                    (now, int(row[0])),
                )
                con.commit()
                return bool(cur.rowcount)
    return False


def _query_df(where_sql: str = "", params: tuple = ()) -> pd.DataFrame:
    if not os.path.exists(_db_path()):
        return pd.DataFrame()
    with _con() as con:
        sql = f"SELECT id, user_id, email, username, role, login_at, logout_at, created_at FROM {TABLA}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        sql += " ORDER BY login_at DESC, id DESC"
        return pd.read_sql(sql, con, params=params).fillna("")


def obtener_conexiones_hoy(role: str = "ejecutivo") -> pd.DataFrame:
    hoy = datetime.now().strftime("%Y-%m-%d")
    return _query_df("substr(login_at,1,10)=? AND role=?", (hoy, role))


def obtener_conexiones_mes(year: int, month: int, role: str = "ejecutivo") -> pd.DataFrame:
    pref = f"{year:04d}-{month:02d}"
    return _query_df("substr(login_at,1,7)=? AND role=?", (pref, role))


def _formatear_duracion_hhmmss(inicio: pd.Timestamp, fin: pd.Timestamp) -> str:
    if pd.isna(inicio) or pd.isna(fin):
        return ""

    delta = fin - inicio
    total_segundos = int(delta.total_seconds())

    if total_segundos < 0:
        return ""

    horas = total_segundos // 3600
    minutos = (total_segundos % 3600) // 60
    segundos = total_segundos % 60

    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


def preparar_reporte_excel(df: pd.DataFrame) -> pd.DataFrame:
    columnas = [
        "Ejecutiva",
        "Fecha",
        "Hora de inicio",
        "Hora de termino",
        "Horas trabajadas",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columnas)

    out = df.copy()
    login_dt = pd.to_datetime(out["login_at"], errors="coerce")
    logout_dt = pd.to_datetime(out["logout_at"], errors="coerce")

    horas_trabajadas = [
        _formatear_duracion_hhmmss(inicio, fin)
        for inicio, fin in zip(login_dt, logout_dt)
    ]

    return pd.DataFrame(
        {
            "Ejecutiva": out["username"].astype(str),
            "Fecha": login_dt.dt.strftime("%d/%m/%Y").fillna(""),
            "Hora de inicio": login_dt.dt.strftime("%H:%M:%S").fillna(""),
            "Hora de termino": logout_dt.dt.strftime("%H:%M:%S").fillna(""),
            "Horas trabajadas": horas_trabajadas,
        }
    )
