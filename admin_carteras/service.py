from __future__ import annotations

import os
import sqlite3
from typing import Iterable

from core.paths import get_data_dir
from auth.auth_service import backend_get_user_carteras

DB_NAME = 'db_admin_carteras.sqlite'


def _db_path() -> str:
    return os.path.join(str(get_data_dir()), DB_NAME)


def _normalizar_empresas(empresas: Iterable[str] | None) -> list[str]:
    if not empresas:
        return []
    salida: list[str] = []
    for emp in empresas:
        txt = str(emp or '').strip()
        if txt and txt not in salida:
            salida.append(txt)
    return salida


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return bool(row)


def obtener_empresas_asignadas_por_user_id(user_id: int | None) -> list[str]:
    if not user_id:
        return []
    path = _db_path()
    if not os.path.exists(path):
        return []
    try:
        with sqlite3.connect(path) as con:
            if not _table_exists(con, 'cartera_asignaciones'):
                return []
            rows = con.execute(
                'SELECT empresa FROM cartera_asignaciones WHERE user_id = ? ORDER BY empresa',
                (int(user_id),),
            ).fetchall()
        return _normalizar_empresas([r[0] for r in rows])
    except Exception:
        return []


def obtener_asignacion_por_empresa_local(empresa: str) -> dict:
    emp = str(empresa or "").strip()
    if not emp:
        return {}
    path = _db_path()
    if not os.path.exists(path):
        return {}
    try:
        with sqlite3.connect(path) as con:
            if not _table_exists(con, 'cartera_asignaciones'):
                return {}
            row = con.execute(
                """
                SELECT empresa, user_id, email, username, updated_at, updated_by
                FROM cartera_asignaciones
                WHERE empresa = ?
                """,
                (emp,),
            ).fetchone()
        if not row:
            return {}
        return {
            "empresa": str(row[0] or "").strip(),
            "user_id": int(row[1]) if row[1] is not None else None,
            "email": str(row[2] or "").strip(),
            "username": str(row[3] or "").strip(),
            "updated_at": str(row[4] or "").strip(),
            "updated_by": str(row[5] or "").strip(),
        }
    except Exception:
        return {}


def obtener_empresas_asignadas_para_session(session) -> list[str]:
    if session is None:
        return []
    if getattr(session, 'role', '') in ('admin', 'supervisor'):
        return []
    if getattr(session, 'auth_source', '') == 'backend':
        empresas, err = backend_get_user_carteras(
            session,
            user_id=getattr(session, 'user_id', None) or 0,
        )
        return _normalizar_empresas(empresas) if not err else []
    return obtener_empresas_asignadas_por_user_id(getattr(session, 'user_id', None))


def session_tiene_restriccion_por_cartera(session) -> bool:
    return bool(session is not None and getattr(session, 'role', '') == 'ejecutivo')


def empresa_permitida_para_session(session, empresa: str) -> bool:
    if not session_tiene_restriccion_por_cartera(session):
        return True
    return str(empresa or '').strip() in set(obtener_empresas_asignadas_para_session(session))

