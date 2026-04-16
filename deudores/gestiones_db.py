from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3

import pandas as pd

from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir

logger = logging.getLogger(__name__)

TABLA = "gestiones"
TIPO_POR_HOJA = {"SMS": "SMS", "Email": "Email", "Carta": "Carta"}
TIPO_COLORES = {
    "SMS": "#dbeafe",
    "Email": "#d1fae5",
    "Carta": "#fce7f3",
    "Manual": "#fef9c3",
    "Whatsapp": "#dcfce7",
    "Pago": "#fee2e2",
}
TIPOS_GESTION = ["SMS", "Email", "Carta", "Manual", "Llamada", "Visita", "Whatsapp", "Pago", "Otro"]

ESTADOS_GESTION = [
    "Enviado",
    "Entregado",
    "No Entregado",
    "Sin Respuesta",
    "Respondido",
    "Rechazado",
    "Birlado",
    "CIP Con intención de pago",
    "SIP Sin intención de pago",
    "Fallecido",
    "Acuerdo de pago",
    "Promesa de pago",
    "Pagado",
    "Cliente Sin deuda",
    "Otro",
]

ESTADO_DEUDOR_DEFAULT = "Sin Gestión"

MAPEO_ESTADO_GESTION_A_DEUDOR = {
    "enviado": "Gestionado",
    "entregado": "Gestionado",
    "no entregado": "Inubicable",
    "sin respuesta": "Gestionado",
    "respondido": "Contactado",
    "rechazado": "Gestionado",
    "birlado": "Birlado",
    "cip con intención de pago": "CIP Con intención de pago",
    "sip sin intención de pago": "SIP Sin intención de pago",
    "sip con intención de pago": "SIP Sin intención de pago",
    "fallecido": "Fallecido",
    "contactado": "Contactado",
    "gestionado": "Gestionado",
    "inubicable": "Inubicable",
    "pagado": "Gestionado",
    "cliente sin deuda": "Cliente Sin deuda",
}


def _db_path() -> str:
    return os.path.join(str(get_data_dir()), "db_gestiones.sqlite")


def _migration_create_gestiones(con: sqlite3.Connection) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Rut_Afiliado TEXT NOT NULL,
            Nombre_Afiliado TEXT,
            tipo_gestion TEXT,
            Estado TEXT,
            Fecha_gestion TEXT,
            Observacion TEXT,
            origen TEXT,
            _fecha_carga TEXT
        )
        """
    )


def _migration_indexes(con: sqlite3.Connection) -> None:
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_rut ON {TABLA}(Rut_Afiliado)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_fecha ON {TABLA}(Fecha_gestion)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_tipo ON {TABLA}(tipo_gestion)")


MIGRATIONS = [
    Migration(1, "Create gestiones table", _migration_create_gestiones),
    Migration(2, "Create gestiones indexes", _migration_indexes),
]


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.execute("PRAGMA foreign_keys = ON")
    apply_migrations(con, MIGRATIONS)
    con.execute(
        f"""CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Rut_Afiliado TEXT NOT NULL,
            Nombre_Afiliado TEXT,
            tipo_gestion TEXT,
            Estado TEXT,
            Fecha_gestion TEXT,
            Observacion TEXT,
            origen TEXT,
            _fecha_carga TEXT
        )"""
    )
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_rut ON {TABLA}(Rut_Afiliado)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_fecha ON {TABLA}(Fecha_gestion)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLA}_tipo ON {TABLA}(tipo_gestion)")
    con.commit()
    return con


def _normalizar_fecha(val: str) -> str:
    v = str(val).strip()
    if not v or v in ("nan", "None", ""):
        return ""
    ts = pd.to_datetime(v, errors="coerce", dayfirst=True)
    return ts.strftime("%d/%m/%Y") if not pd.isna(ts) else (v[:10] if len(v) >= 10 else v)


def _norm_rut(rut: str) -> str:
    return str(rut).strip().replace(".", "").replace("-", "").lstrip("0")


def _normalizar_estado_texto(estado: str) -> str:
    return " ".join(str(estado).strip().lower().split())


def mapear_estado_gestion_a_estado_deudor(estado_gestion: str) -> str:
    estado_norm = _normalizar_estado_texto(estado_gestion)
    return MAPEO_ESTADO_GESTION_A_DEUDOR.get(estado_norm, "Gestionado" if estado_norm else ESTADO_DEUDOR_DEFAULT)


def obtener_estados_deudor_por_rut() -> dict[str, str]:
    if not os.path.exists(_db_path()):
        return {}

    try:
        with _con() as con:
            df = pd.read_sql(
                f"SELECT id, Rut_Afiliado, Estado, Fecha_gestion FROM {TABLA}",
                con,
                dtype=str,
            ).fillna("")

        if df.empty:
            return {}

        df["_rut_norm"] = df["Rut_Afiliado"].apply(_norm_rut)
        df["_fecha_sort"] = pd.to_datetime(df["Fecha_gestion"], format="%d/%m/%Y", errors="coerce")
        df["_id_sort"] = pd.to_numeric(df["id"], errors="coerce").fillna(0)

        df = df.sort_values(
            by=["_rut_norm", "_fecha_sort", "_id_sort"],
            ascending=[True, False, False],
            na_position="last",
        )

        ultimas = df.drop_duplicates(subset=["_rut_norm"], keep="first").copy()
        ultimas["Estado_deudor"] = ultimas["Estado"].apply(mapear_estado_gestion_a_estado_deudor)

        return dict(zip(ultimas["_rut_norm"], ultimas["Estado_deudor"]))

    except Exception:
        logger.exception("No se pudo calcular el estado deudor por RUT")
        return {}


def cargar_desde_excel(excel_path: str) -> tuple[int, int, list[str]]:
    registros, errores = leer_gestiones_excel(excel_path)
    insertados = 0
    omitidos = 0
    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        for row in registros:
            rut = str(row.get("rut", "")).strip()
            tipo = str(row.get("tipo_gestion", "")).strip()
            estado = str(row.get("estado", "")).strip()
            fecha = str(row.get("fecha_gestion", "")).strip()
            obs = str(row.get("observacion", "")).strip()
            origen = str(row.get("origen", "")).strip()
            nombre = str(row.get("nombre_afiliado", "")).strip()

            cur = con.execute(
                f"""SELECT Fecha_gestion FROM {TABLA}
                    WHERE REPLACE(REPLACE(Rut_Afiliado,'.',''),'-','') = REPLACE(REPLACE(?,'.',''),'-','')
                      AND tipo_gestion = ? AND Estado = ? AND Observacion = ? AND origen = ?""",
                (rut, tipo, estado, obs, origen),
            )
            if fecha in {f[0] for f in cur.fetchall()}:
                omitidos += 1
                continue

            con.execute(
                f"""INSERT INTO {TABLA}
                (Rut_Afiliado, Nombre_Afiliado, tipo_gestion, Estado, Fecha_gestion, Observacion, origen, _fecha_carga)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (rut, nombre, tipo, estado, fecha, obs, origen, ahora),
            )
            insertados += 1
        con.commit()
    return insertados, omitidos, errores


def leer_gestiones_excel(excel_path: str) -> tuple[list[dict], list[str]]:
    xl = pd.ExcelFile(excel_path)
    registros: list[dict] = []
    errores: list[str] = []

    for hoja, tipo in TIPO_POR_HOJA.items():
        if hoja not in xl.sheet_names:
            errores.append(f"Hoja '{hoja}' no encontrada en el Excel.")
            continue
        try:
            df = pd.read_excel(excel_path, sheet_name=hoja, dtype=str).fillna("")
            if "Fecha_gestion" in df.columns:
                df["Fecha_gestion"] = df["Fecha_gestion"].apply(_normalizar_fecha)
            df = df.replace({"nan": "", "None": "", "NaN": ""})
            for _, row in df.iterrows():
                rut = str(row.get("Rut_Afiliado", "")).strip()
                if not rut:
                    continue
                registros.append(
                    {
                        "rut": rut,
                        "nombre_afiliado": str(row.get("Nombre_Afiliado", "")).strip(),
                        "tipo_gestion": tipo,
                        "estado": str(row.get("Estado", "")).strip(),
                        "fecha_gestion": str(row.get("Fecha_gestion", "")).strip(),
                        "observacion": str(row.get("Observacion", "")).strip(),
                        "origen": f"excel_{hoja}",
                    }
                )
        except Exception as e:
            logger.exception("Error cargando hoja %s", hoja)
            errores.append(f"Error en hoja '{hoja}': {e}")

    return registros, errores


def insertar_gestion_manual(rut: str, nombre: str, tipo_gestion: str, estado: str, fecha: str, observacion: str) -> int:
    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        cur = con.execute(
            f"""INSERT INTO {TABLA}
            (Rut_Afiliado, Nombre_Afiliado, tipo_gestion, Estado, Fecha_gestion, Observacion, origen, _fecha_carga)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rut.strip(), nombre.strip(), tipo_gestion, estado, fecha, observacion, "manual", ahora),
        )
        con.commit()
        return int(cur.lastrowid)


def insertar_gestion_pago(
    rut: str,
    nombre: str,
    estado: str,
    fecha: str,
    empresa: str,
    expediente: str,
    monto: float,
    tipo_pago: str,
    observaciones_usuario: str,
) -> int:
    payload = {
        "kind": "pago",
        "empresa": str(empresa).strip(),
        "expediente": str(expediente).strip(),
        "monto": float(monto),
        "tipo_pago": str(tipo_pago).strip(),
        "observaciones_usuario": str(observaciones_usuario or "").strip(),
    }
    observacion = json.dumps(payload, ensure_ascii=False)

    return insertar_gestion_manual(
        rut=rut,
        nombre=nombre,
        tipo_gestion="Pago",
        estado=estado,
        fecha=fecha,
        observacion=observacion,
    )


def parsear_observacion_pago(observacion: str) -> dict:
    txt = str(observacion or "").strip()
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def obtener_gestiones_rut(rut: str) -> pd.DataFrame:
    if not os.path.exists(_db_path()):
        return pd.DataFrame()
    try:
        with _con() as con:
            df = pd.read_sql(
                f"""SELECT tipo_gestion, Estado, Fecha_gestion, Observacion, origen, id
                    FROM {TABLA}
                    WHERE REPLACE(REPLACE(Rut_Afiliado, '.', ''), '-', '') = ?
                    ORDER BY Fecha_gestion DESC, id DESC""",
                con,
                params=(_norm_rut(rut),),
                dtype=str,
            ).fillna("")

        if df.empty:
            return df

        def _obs_visible(row) -> str:
            if str(row.get("tipo_gestion", "")).strip() != "Pago":
                return str(row.get("Observacion", "")).strip()

            data = parsear_observacion_pago(row.get("Observacion", ""))
            if not data:
                return str(row.get("Observacion", "")).strip()

            partes = []
            tipo_pago = str(data.get("tipo_pago", "")).strip()
            expediente = str(data.get("expediente", "")).strip()
            monto = float(data.get("monto", 0) or 0)
            obs_user = str(data.get("observaciones_usuario", "")).strip()

            if tipo_pago:
                partes.append(tipo_pago)
            if expediente:
                partes.append(f"Expediente {expediente}")
            if monto > 0:
                partes.append(f"$ {int(round(monto)):,}".replace(",", "."))
            if obs_user:
                partes.append(obs_user)

            return " | ".join(partes) if partes else "Pago"

        df["Observacion"] = df.apply(_obs_visible, axis=1)
        return df

    except Exception:
        logger.exception("No se pudieron obtener gestiones para el RUT %s", rut)
        return pd.DataFrame()


def obtener_gestion_por_id(gestion_id: int) -> dict | None:
    try:
        with _con() as con:
            row = con.execute(
                f"""SELECT id, Rut_Afiliado, Nombre_Afiliado, tipo_gestion, Estado, Fecha_gestion, Observacion, origen
                    FROM {TABLA}
                    WHERE id = ?""",
                (gestion_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "Rut_Afiliado": row[1],
            "Nombre_Afiliado": row[2],
            "tipo_gestion": row[3],
            "Estado": row[4],
            "Fecha_gestion": row[5],
            "Observacion": row[6],
            "origen": row[7],
        }
    except Exception:
        logger.exception("No se pudo obtener la gestión %s", gestion_id)
        return None


def eliminar_gestion(gestion_id: int) -> bool:
    try:
        with _con() as con:
            con.execute(f"DELETE FROM {TABLA} WHERE id = ? AND origen = 'manual'", (gestion_id,))
            con.commit()
        return True
    except Exception:
        logger.exception("No se pudo eliminar gestión %s", gestion_id)
        return False


def total_gestiones() -> dict:
    if not os.path.exists(_db_path()):
        return {}
    try:
        with _con() as con:
            df = pd.read_sql(f"SELECT tipo_gestion, COUNT(*) as n FROM {TABLA} GROUP BY tipo_gestion", con)
            return dict(zip(df["tipo_gestion"], df["n"]))
    except Exception:
        logger.exception("No se pudieron calcular estadísticas de gestiones")
        return {}


def limpiar_gestiones() -> bool:
    try:
        with _con() as con:
            con.execute(f"DELETE FROM {TABLA}")
            con.commit()
        return True
    except Exception:
        logger.exception("No se pudo limpiar la tabla de gestiones")
        return False


def limpiar_gestiones_por_ruts(ruts: list) -> int:
    if not ruts:
        return 0
    try:
        with _con() as con:
            cur = con.execute(f"SELECT id, Rut_Afiliado FROM {TABLA}")
            ruts_norm = {str(r).replace(".", "").replace("-", "").strip().lstrip("0") for r in ruts}
            ids_borrar = [row[0] for row in cur.fetchall() if str(row[1]).replace(".", "").replace("-", "").strip().lstrip("0") in ruts_norm]
            if ids_borrar:
                placeholders = ",".join("?" * len(ids_borrar))
                con.execute(f"DELETE FROM {TABLA} WHERE id IN ({placeholders})", ids_borrar)
                con.commit()
            return len(ids_borrar)
    except Exception:
        logger.exception("No se pudieron borrar gestiones por RUT")
        return 0
