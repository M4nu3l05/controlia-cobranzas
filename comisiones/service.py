"""Comisiones por cartera.

El supervisor define un porcentaje por cartera y cada pago registrado por una
ejecutiva acumula ese porcentaje sobre el monto pagado. En modo backend el
acumulado se deriva del libro de pagos del CRM; en modo local se registra un
evento propio, porque la base local de gestiones no guarda la autoria del pago.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from auth.auth_service import (
    backend_get_comisiones_resumen,
    backend_list_comision_tasas,
    backend_reset_comisiones,
    backend_save_comision_tasas,
)
from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir

DB_NAME = "db_comisiones.sqlite"


def _db_path() -> str:
    return os.path.join(str(get_data_dir()), DB_NAME)


def _migration_create_tables(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS comision_tasas (
            empresa TEXT PRIMARY KEY,
            porcentaje REAL NOT NULL DEFAULT 0,
            updated_at TEXT,
            updated_by TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS comision_eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            empresa TEXT NOT NULL DEFAULT '',
            monto_pagado REAL NOT NULL DEFAULT 0,
            porcentaje REAL NOT NULL DEFAULT 0,
            comision REAL NOT NULL DEFAULT 0,
            registrado_en TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS comision_cortes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            corte_en TEXT NOT NULL,
            creado_por TEXT NOT NULL DEFAULT ''
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_comision_eventos_user ON comision_eventos(user_id)")


MIGRATIONS = [Migration(1, "Crear tablas de comisiones", _migration_create_tables)]


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    apply_migrations(con, MIGRATIONS)
    return con


def _usa_backend(session) -> bool:
    return bool(
        session is not None
        and getattr(session, "auth_source", "") == "backend"
        and getattr(session, "access_token", "")
    )


def _empresa_key(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _ahora() -> str:
    # Con microsegundos, para que un pago registrado en el mismo segundo que un
    # corte quede correctamente después de él.
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def es_supervisor(session) -> bool:
    return bool(session is not None and getattr(session, "role", "") in {"admin", "supervisor"})


# ============================================================
# Porcentajes por cartera
# ============================================================


def obtener_tasas(session) -> tuple[dict[str, float], str]:
    """Devuelve {empresa: porcentaje} y un mensaje de error si lo hubo."""
    if _usa_backend(session):
        rows, err = backend_list_comision_tasas(session)
        if err:
            return {}, err
        return {
            str(row.get("empresa", "")).strip(): float(row.get("percent", 0) or 0)
            for row in rows
            if str(row.get("empresa", "")).strip()
        }, ""

    try:
        with _con() as con:
            rows = con.execute("SELECT empresa, porcentaje FROM comision_tasas").fetchall()
        return {str(empresa).strip(): float(porcentaje or 0) for empresa, porcentaje in rows}, ""
    except Exception as exc:
        return {}, str(exc)


def guardar_tasas(session, tasas: dict[str, float]) -> str:
    """Guarda los porcentajes por cartera. Devuelve '' si todo salió bien."""
    normalizadas = {
        str(empresa).strip(): float(porcentaje or 0)
        for empresa, porcentaje in (tasas or {}).items()
        if str(empresa).strip()
    }
    for empresa, porcentaje in normalizadas.items():
        if porcentaje < 0 or porcentaje > 100:
            return f"El porcentaje de {empresa} debe estar entre 0 y 100."

    if _usa_backend(session):
        rates = [{"empresa": empresa, "percent": porcentaje} for empresa, porcentaje in normalizadas.items()]
        _, err = backend_save_comision_tasas(session, rates=rates)
        return err

    try:
        updated_by = str(getattr(session, "username", "") or "Sistema")
        with _con() as con:
            for empresa, porcentaje in normalizadas.items():
                con.execute(
                    """
                    INSERT INTO comision_tasas (empresa, porcentaje, updated_at, updated_by)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(empresa) DO UPDATE SET
                        porcentaje=excluded.porcentaje,
                        updated_at=excluded.updated_at,
                        updated_by=excluded.updated_by
                    """,
                    (empresa, porcentaje, _ahora(), updated_by),
                )
            con.commit()
        return ""
    except Exception as exc:
        return str(exc)


def obtener_tasa_empresa(session, empresa: str) -> float:
    tasas, _ = obtener_tasas(session)
    objetivo = _empresa_key(empresa)
    for nombre, porcentaje in tasas.items():
        if _empresa_key(nombre) == objetivo:
            return float(porcentaje or 0)
    return 0.0


# ============================================================
# Acumulado por ejecutiva
# ============================================================


def registrar_pago_local(session, *, empresa: str, monto: float) -> None:
    """Acumula la comisión de un pago en modo local.

    En modo backend no hace nada: el acumulado se deriva del libro de pagos.
    """
    if _usa_backend(session) or session is None:
        return
    user_id = int(getattr(session, "user_id", 0) or 0)
    if not user_id:
        return

    monto_num = float(monto or 0)
    if monto_num <= 0:
        return

    porcentaje = obtener_tasa_empresa(session, empresa)
    try:
        with _con() as con:
            con.execute(
                """
                INSERT INTO comision_eventos (
                    user_id, username, email, empresa, monto_pagado, porcentaje, comision, registrado_en
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    str(getattr(session, "username", "") or ""),
                    str(getattr(session, "email", "") or ""),
                    str(empresa or "").strip(),
                    monto_num,
                    porcentaje,
                    round(monto_num * porcentaje / 100.0),
                    _ahora(),
                ),
            )
            con.commit()
    except Exception:
        # La comisión es un indicador motivacional: nunca debe romper el pago.
        pass


def _ejecutivas_activas_locales() -> list[dict]:
    try:
        from auth.auth_db import get_all_users

        return [
            usuario
            for usuario in get_all_users()
            if str(usuario.get("role", "")).strip() == "ejecutivo" and bool(usuario.get("is_active", 0))
        ]
    except Exception:
        return []


def _resumen_local(session) -> list[dict]:
    user_id = int(getattr(session, "user_id", 0) or 0)
    try:
        with _con() as con:
            cortes = con.execute("SELECT user_id, corte_en FROM comision_cortes").fetchall()
            eventos = con.execute(
                """
                SELECT user_id, username, email, empresa, monto_pagado, comision, registrado_en
                FROM comision_eventos
                """
            ).fetchall()
    except Exception:
        return []

    corte_global = ""
    corte_usuario: dict[int, str] = {}
    for scope_user_id, corte_en in cortes:
        corte = str(corte_en or "")
        if scope_user_id is None:
            corte_global = max(corte_global, corte)
        else:
            clave = int(scope_user_id)
            corte_usuario[clave] = max(corte_usuario.get(clave, ""), corte)

    def _fila_vacia(clave: int, username: str, email: str) -> dict:
        return {
            "user_id": clave,
            "username": str(username or ""),
            "email": str(email or ""),
            "pagos": 0,
            "monto_pagado_clp": 0,
            "comision_clp": 0,
            "desde": max(corte_global, corte_usuario.get(clave, "")),
        }

    acumulado: dict[int, dict] = {}
    if es_supervisor(session):
        # El supervisor ve una tarjeta por ejecutiva activa, aunque esté en $0.
        for usuario in _ejecutivas_activas_locales():
            clave = int(usuario.get("id", 0) or 0)
            if clave:
                acumulado[clave] = _fila_vacia(
                    clave, usuario.get("username", ""), usuario.get("email", "")
                )

    for evento_user_id, username, email, _empresa, monto, comision, registrado_en in eventos:
        clave = int(evento_user_id)
        if not es_supervisor(session) and clave != user_id:
            continue
        corte = max(corte_global, corte_usuario.get(clave, ""))
        if corte and str(registrado_en or "") <= corte:
            continue
        fila = acumulado.setdefault(clave, _fila_vacia(clave, username, email))
        if not fila["username"]:
            fila["username"] = str(username or "")
        fila["pagos"] += 1
        fila["monto_pagado_clp"] += int(round(float(monto or 0)))
        fila["comision_clp"] += int(round(float(comision or 0)))

    if not es_supervisor(session) and user_id and user_id not in acumulado:
        acumulado[user_id] = _fila_vacia(
            user_id,
            str(getattr(session, "username", "") or ""),
            str(getattr(session, "email", "") or ""),
        )

    salida = list(acumulado.values())
    salida.sort(key=lambda item: (-item["comision_clp"], str(item["username"]).lower()))
    return salida


def obtener_resumen(session) -> tuple[list[dict], str]:
    """Acumulado de comisiones visible para la sesión actual.

    Una ejecutiva sólo ve su propia fila; el supervisor ve una por ejecutiva.
    """
    if _usa_backend(session):
        rows, err = backend_get_comisiones_resumen(session)
        if err:
            return [], err
        return [
            {
                "user_id": int(row.get("user_id", 0) or 0),
                "username": str(row.get("username", "") or ""),
                "email": str(row.get("email", "") or ""),
                "pagos": int(row.get("pagos", 0) or 0),
                "monto_pagado_clp": int(row.get("monto_pagado_clp", 0) or 0),
                "comision_clp": int(row.get("comision_clp", 0) or 0),
                "desde": str(row.get("desde", "") or ""),
                "detalle": row.get("detalle", []) or [],
            }
            for row in rows
        ], ""

    return _resumen_local(session), ""


def obtener_comision_propia(session) -> tuple[dict, str]:
    resumen, err = obtener_resumen(session)
    if err:
        return {}, err
    user_id = int(getattr(session, "user_id", 0) or 0)
    for fila in resumen:
        if int(fila.get("user_id", 0) or 0) == user_id:
            return fila, ""
    return {}, ""


def reestablecer_comisiones(session, *, user_id: int | None = None) -> str:
    """Deja en $0 el acumulado. Sólo disponible para supervisor o admin."""
    if not es_supervisor(session):
        return "Solo un supervisor puede reestablecer las comisiones."

    if _usa_backend(session):
        _, err = backend_reset_comisiones(session, user_id=user_id)
        return err

    try:
        with _con() as con:
            con.execute(
                "INSERT INTO comision_cortes (user_id, corte_en, creado_por) VALUES (?, ?, ?)",
                (
                    int(user_id) if user_id is not None else None,
                    _ahora(),
                    str(getattr(session, "username", "") or "Sistema"),
                ),
            )
            con.commit()
        return ""
    except Exception as exc:
        return str(exc)
