from __future__ import annotations

import datetime
import logging
import os
import re
import sqlite3
import unicodedata

import pandas as pd

from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir

logger = logging.getLogger(__name__)

EMPRESAS = ["Colmena", "Consalud", "Cruz Blanca", "Cart-56"]
TABLA = "deudores"
TABLA_CONTACTOS = "contactos"
TABLA_DETALLE = "detalle"
COL_EMPRESA = "_empresa"
COL_FECHA_CARGA = "_fecha_carga"

COL_CREATED_AT = "_created_at"
COL_UPDATED_AT = "_updated_at"
COL_FIRST_SEEN_AT = "_first_seen_at"
COL_LAST_SEEN_AT = "_last_seen_at"
COL_SOURCE_FILE = "_source_file"

ESTADO_DEUDOR_DEFAULT = "Sin Gestión"

COLS_CONTACTO = [
    "Rut_Afiliado",
    "Nombre_Afiliado",
    "mail_afiliado",
    "telefono_fijo_afiliado",
    "telefono_movil_afiliado",
]

COLS_DETALLE = [
    "Rut_Afiliado",
    "Dv",
    "Nombre_Afiliado",
    "Nombre Afil",
    "RUT Afil",
    "Fecha Pago",
    "mail_afiliado",
    "BN",
    "telefono_fijo_afiliado",
    "telefono_movil_afiliado",
    "Nro_Expediente",
    "Fecha_Emision",
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
    "Cart56_Fecha_Recep",
    "Cart56_Fecha_Recep_ISA",
    "Cart56_Dias_Pagar",
    "Cart56_Mto_Pagar",
    "_RUT_COMPLETO",
    "Mail Emp",
    "Telefono Empleador",
    "Estado_deudor",
]

METADATA_COLS = [
    COL_EMPRESA,
    COL_FECHA_CARGA,
    COL_CREATED_AT,
    COL_UPDATED_AT,
    COL_FIRST_SEEN_AT,
    COL_LAST_SEEN_AT,
    COL_SOURCE_FILE,
]


def _db_dir() -> str:
    return str(get_data_dir())


def _slug_empresa(empresa: str) -> str:
    texto = str(empresa or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto or "empresa"


def _db_path(empresa: str) -> str:
    return os.path.join(_db_dir(), f"db_{_slug_empresa(empresa)}.sqlite")


def _migration_create_placeholder_tables(con: sqlite3.Connection) -> None:
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLA} (Rut_Afiliado TEXT, {COL_EMPRESA} TEXT, {COL_FECHA_CARGA} TEXT)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLA_CONTACTOS} (Rut_Afiliado TEXT, mail_afiliado TEXT, {COL_EMPRESA} TEXT, {COL_FECHA_CARGA} TEXT)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLA_DETALLE} (Rut_Afiliado TEXT, Nombre_Afiliado TEXT, {COL_EMPRESA} TEXT, {COL_FECHA_CARGA} TEXT)"
    )


def _migration_indexes(con: sqlite3.Connection) -> None:
    for table in (TABLA, TABLA_CONTACTOS, TABLA_DETALLE):
        cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if "Rut_Afiliado" in cols:
            con.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_rut ON "{table}"("Rut_Afiliado")')
        if COL_EMPRESA in cols:
            con.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_empresa ON "{table}"("{COL_EMPRESA}")')
        if COL_FECHA_CARGA in cols:
            con.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_fecha_carga ON "{table}"("{COL_FECHA_CARGA}")')


MIGRATIONS = [
    Migration(1, "Create placeholder tables for deudores module", _migration_create_placeholder_tables),
    Migration(2, "Create indexes for deudores tables", _migration_indexes),
]


def _conexion(empresa: str) -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(empresa))
    con.execute("PRAGMA foreign_keys = ON")
    apply_migrations(con, MIGRATIONS)

    con.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLA} (Rut_Afiliado TEXT, {COL_EMPRESA} TEXT, {COL_FECHA_CARGA} TEXT)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLA_CONTACTOS} (Rut_Afiliado TEXT, mail_afiliado TEXT, {COL_EMPRESA} TEXT, {COL_FECHA_CARGA} TEXT)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLA_DETALLE} (Rut_Afiliado TEXT, Nombre_Afiliado TEXT, {COL_EMPRESA} TEXT, {COL_FECHA_CARGA} TEXT)"
    )
    con.commit()
    return con


def _post_write_indexes(con: sqlite3.Connection, table: str) -> None:
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if "Rut_Afiliado" in cols:
        con.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_rut ON "{table}"("Rut_Afiliado")')
    if COL_EMPRESA in cols:
        con.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_empresa ON "{table}"("{COL_EMPRESA}")')
    if COL_FECHA_CARGA in cols:
        con.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_fecha_carga ON "{table}"("{COL_FECHA_CARGA}")')


def _normalizar_rut(valor: str) -> str:
    return str(valor).strip().replace(".", "").replace("-", "").lstrip("0")


def _parse_num(val: str) -> float:
    try:
        texto = str(val).strip()
        if not texto:
            return 0.0
        texto = texto.replace("$", "").replace(" ", "")
        if "." in texto and "," not in texto:
            texto = texto.replace(".", "")
        elif "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        return float(texto)
    except (ValueError, TypeError):
        return 0.0


def _fmt_monto_txt(val: float) -> str:
    try:
        return str(int(round(float(val))))
    except Exception:
        return "0"


def _tabla_cols(con: sqlite3.Connection, tabla: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({tabla})").fetchall()}


def _ensure_column(con: sqlite3.Connection, tabla: str, columna: str, tipo_sql: str = "TEXT") -> None:
    cols = _tabla_cols(con, tabla)
    if columna not in cols:
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{columna}" {tipo_sql}')


def _ensure_columns(con: sqlite3.Connection, tabla: str, columnas: list[str], tipo_sql: str = "TEXT") -> None:
    for col in columnas:
        _ensure_column(con, tabla, col, tipo_sql)


def _sanitize_incoming_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().fillna("")
    out = out.rename(columns={c: str(c).strip() for c in out.columns})

    colmap_norm = {
        re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", str(c).strip().lower()).encode("ascii", "ignore").decode("ascii")): str(c)
        for c in out.columns
    }
    alias_map = {
        "Nombre Afil": ["Nombre Afiliado", "Nom Afil"],
        "RUT Afil": ["Rut Afil", "RUT Afiliado", "Rut Afiliado"],
        "Fecha Pago": ["Fecha de Pago", "Fec Pago"],
    }
    for canon, aliases in alias_map.items():
        if canon in out.columns:
            continue
        for cand in [canon] + aliases:
            key = re.sub(
                r"[^a-z0-9]+",
                "",
                unicodedata.normalize("NFKD", str(cand).strip().lower()).encode("ascii", "ignore").decode("ascii"),
            )
            real = colmap_norm.get(key, "")
            if real:
                out[canon] = out[real]
                break

    if "Rut_Afiliado" in out.columns:
        rut_series = out["Rut_Afiliado"].astype(str)
        dv_series = out["Dv"].astype(str) if "Dv" in out.columns else pd.Series([""] * len(out), index=out.index)
        rut_full_series = out["_RUT_COMPLETO"].astype(str) if "_RUT_COMPLETO" in out.columns else pd.Series([""] * len(out), index=out.index)

        rut_vals: list[str] = []
        dv_vals: list[str] = []
        rut_full_vals: list[str] = []

        for rut_val, dv_val, rut_full_val in zip(rut_series.tolist(), dv_series.tolist(), rut_full_series.tolist()):
            source = str(rut_full_val or rut_val).strip().replace(".", "")
            dv_txt = str(dv_val or "").strip().upper()

            if "-" in source:
                base, dv_from_source = source.rsplit("-", 1)
                rut_txt = base.strip().replace("-", "").lstrip("0")
                dv_txt = dv_txt or dv_from_source.strip().upper()
            else:
                rut_txt = source.replace("-", "").strip().lstrip("0")

            rut_vals.append(rut_txt)
            dv_vals.append(dv_txt)
            rut_full_vals.append(f"{rut_txt}-{dv_txt}" if rut_txt and dv_txt else rut_txt)

        out["Rut_Afiliado"] = rut_vals
        out["Dv"] = dv_vals
        out["_RUT_COMPLETO"] = rut_full_vals
    return out


def _value_or_old(new_val, old_val):
    txt = str(new_val).strip() if new_val is not None else ""
    return txt if txt not in ("", "nan", "None", "NaN", "nat", "NaT") else old_val


def _build_merge_key_rut(df: pd.DataFrame) -> pd.Series:
    if "Rut_Afiliado" not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype=str)
    return (
        df["Rut_Afiliado"]
        .astype(str)
        .str.replace(".", "", regex=False)
        .str.replace("-", "", regex=False)
        .str.strip()
        .str.lstrip("0")
    )


def _build_merge_key_detalle(df: pd.DataFrame) -> pd.Series:
    rut = _build_merge_key_rut(df)
    expediente = df.get("Nro_Expediente", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip()
    fecha = df.get("Fecha_Emision", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip()
    copago = df.get("Copago", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip()
    fallback = fecha + "|" + copago
    expediente_final = expediente.where(expediente != "", fallback)
    return rut + "||" + expediente_final


def _dedup_by_key(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    df2 = df.copy()
    df2 = df2[df2[key_col].astype(str).str.strip() != ""].copy()
    if df2.empty:
        return df2
    return df2.drop_duplicates(subset=[key_col], keep="last").reset_index(drop=True)


def _read_table(con: sqlite3.Connection, table: str) -> pd.DataFrame:
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not row:
            return pd.DataFrame()
        return pd.read_sql(f'SELECT * FROM "{table}"', con, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()


def _recompute_operational_fields(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.copy()

    if "Total_Pagos" not in out.columns:
        out["Total_Pagos"] = "0"
    if "Saldo_Actual" not in out.columns:
        out["Saldo_Actual"] = "0"
    if "Estado_deudor" not in out.columns:
        out["Estado_deudor"] = ESTADO_DEUDOR_DEFAULT

    if "Copago" in out.columns:
        total_pagos_num = out["Total_Pagos"].apply(_parse_num)
        copago_num = out["Copago"].apply(_parse_num)
        saldo_num = (copago_num - total_pagos_num).clip(lower=0)

        out["Total_Pagos"] = total_pagos_num.apply(_fmt_monto_txt)
        out["Saldo_Actual"] = saldo_num.apply(_fmt_monto_txt)

        estados = out["Estado_deudor"].astype(str).str.strip()
        estados = estados.replace({"": ESTADO_DEUDOR_DEFAULT, "nan": ESTADO_DEUDOR_DEFAULT, "None": ESTADO_DEUDOR_DEFAULT})

        out["Estado_deudor"] = estados
        out.loc[saldo_num <= 0, "Estado_deudor"] = "Cliente Sin deuda"

    return out


def _merge_rows(existing_row: dict, incoming_row: dict, now_txt: str, source_file: str) -> dict:
    merged = dict(existing_row)

    for col, val in incoming_row.items():
        if col == "__merge_key__":
            continue
        merged[col] = _value_or_old(val, merged.get(col, ""))

    merged[COL_UPDATED_AT] = now_txt
    merged[COL_LAST_SEEN_AT] = now_txt
    merged[COL_SOURCE_FILE] = source_file or merged.get(COL_SOURCE_FILE, "")
    merged[COL_FECHA_CARGA] = now_txt
    merged[COL_CREATED_AT] = merged.get(COL_CREATED_AT, now_txt) or now_txt
    merged[COL_FIRST_SEEN_AT] = merged.get(COL_FIRST_SEEN_AT, now_txt) or now_txt
    return merged


def _insert_row(incoming_row: dict, empresa: str, now_txt: str, source_file: str) -> dict:
    row = dict(incoming_row)
    row[COL_EMPRESA] = empresa
    row[COL_FECHA_CARGA] = now_txt
    row[COL_CREATED_AT] = now_txt
    row[COL_UPDATED_AT] = now_txt
    row[COL_FIRST_SEEN_AT] = now_txt
    row[COL_LAST_SEEN_AT] = now_txt
    row[COL_SOURCE_FILE] = source_file
    return row


def _merge_table_by_key(
    con: sqlite3.Connection,
    table: str,
    incoming_df: pd.DataFrame,
    empresa: str,
    source_file: str,
    key_builder,
    postprocess=None,
) -> int:
    now_txt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    incoming = _sanitize_incoming_dataframe(incoming_df)
    incoming[COL_EMPRESA] = empresa
    incoming["__merge_key__"] = key_builder(incoming)
    incoming = _dedup_by_key(incoming, "__merge_key__")

    existing = _read_table(con, table)
    if existing.empty:
        merged = incoming.copy()
        for col in METADATA_COLS:
            if col not in merged.columns:
                merged[col] = ""
        merged[COL_EMPRESA] = empresa
        merged[COL_FECHA_CARGA] = now_txt
        merged[COL_CREATED_AT] = now_txt
        merged[COL_UPDATED_AT] = now_txt
        merged[COL_FIRST_SEEN_AT] = now_txt
        merged[COL_LAST_SEEN_AT] = now_txt
        merged[COL_SOURCE_FILE] = source_file
    else:
        existing = existing.fillna("").copy()
        existing["__merge_key__"] = key_builder(existing)
        existing = _dedup_by_key(existing, "__merge_key__")

        existing_map = {
            str(row["__merge_key__"]): row.to_dict()
            for _, row in existing.iterrows()
            if str(row.get("__merge_key__", "")).strip()
        }

        incoming_keys = set()
        merged_rows: list[dict] = []

        for _, row in incoming.iterrows():
            row_dict = row.to_dict()
            key = str(row_dict.get("__merge_key__", "")).strip()
            if not key:
                continue

            incoming_keys.add(key)
            if key in existing_map:
                merged_rows.append(_merge_rows(existing_map[key], row_dict, now_txt, source_file))
            else:
                merged_rows.append(_insert_row(row_dict, empresa, now_txt, source_file))

        for key, row_dict in existing_map.items():
            if key not in incoming_keys:
                merged_rows.append(row_dict)

        merged = pd.DataFrame(merged_rows).fillna("")

    if merged.empty:
        return 0

    if postprocess is not None:
        merged = postprocess(merged)

    if "__merge_key__" in merged.columns:
        merged = merged.drop(columns=["__merge_key__"])

    _ensure_columns(con, table, [c for c in merged.columns if c not in _tabla_cols(con, table)])
    merged.to_sql(table, con, if_exists="replace", index=False)
    _post_write_indexes(con, table)
    return len(incoming)


def _postprocess_resumen(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = _recompute_operational_fields(out)
    return out


def _postprocess_detalle(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = _recompute_operational_fields(out)
    return out


def _postprocess_contactos(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().fillna("")
    if "mail_afiliado" in out.columns:
        out["mail_afiliado"] = out["mail_afiliado"].astype(str).str.strip()
    if "telefono_fijo_afiliado" in out.columns:
        out["telefono_fijo_afiliado"] = out["telefono_fijo_afiliado"].astype(str).str.strip()
    if "telefono_movil_afiliado" in out.columns:
        out["telefono_movil_afiliado"] = out["telefono_movil_afiliado"].astype(str).str.strip()
    return out


def _obtener_filas_detalle_por_rut_y_expediente(
    con: sqlite3.Connection,
    rut_norm: str,
    expediente: str,
) -> pd.DataFrame:
    df_det = pd.read_sql(f'SELECT rowid AS _rid_, * FROM "{TABLA_DETALLE}"', con, dtype=str).fillna("")
    if df_det.empty:
        return pd.DataFrame()

    rut_mask = (
        df_det["Rut_Afiliado"].astype(str)
        .str.replace(".", "", regex=False)
        .str.replace("-", "", regex=False)
        .str.strip()
        .str.lstrip("0")
        .eq(rut_norm)
    )
    expediente_mask = df_det["Nro_Expediente"].astype(str).str.strip().eq(str(expediente).strip())
    return df_det.loc[rut_mask & expediente_mask].copy()


def _recalcular_resumen_desde_detalle(con: sqlite3.Connection, rut_norm: str) -> dict:
    _ensure_column(con, TABLA, "Total_Pagos", "TEXT")
    _ensure_column(con, TABLA, "Saldo_Actual", "TEXT")
    _ensure_column(con, TABLA, "Estado_deudor", "TEXT")
    _ensure_column(con, TABLA, COL_FECHA_CARGA, "TEXT")

    df_det = pd.read_sql(f'SELECT rowid AS _rid_, * FROM "{TABLA_DETALLE}"', con, dtype=str).fillna("")
    if df_det.empty:
        raise ValueError("No existe detalle para recalcular el resumen.")

    mask = (
        df_det["Rut_Afiliado"].astype(str)
        .str.replace(".", "", regex=False)
        .str.replace("-", "", regex=False)
        .str.strip()
        .str.lstrip("0")
        .eq(rut_norm)
    )
    filas = df_det.loc[mask].copy()

    if filas.empty:
        raise ValueError("No se encontraron filas de detalle para el RUT.")

    copago_total = float(sum(_parse_num(v) for v in filas.get("Copago", pd.Series(dtype=str))))
    pagos_total = float(sum(_parse_num(v) for v in filas.get("Total_Pagos", pd.Series(dtype=str))))
    saldo_total = max(copago_total - pagos_total, 0.0)

    estado = "Cliente Sin deuda" if round(saldo_total, 2) == 0 else "Gestionado"

    if "Estado_deudor" in filas.columns and round(saldo_total, 2) > 0:
        estados = [
            str(v).strip()
            for v in filas["Estado_deudor"].tolist()
            if str(v).strip() and str(v).strip() != "Cliente Sin deuda"
        ]
        if estados:
            estado = estados[0]

    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    con.execute(
        f"""
        UPDATE "{TABLA}"
        SET Total_Pagos = ?, Saldo_Actual = ?, Estado_deudor = ?, {COL_FECHA_CARGA} = ?
        WHERE REPLACE(REPLACE(TRIM(Rut_Afiliado), '.', ''), '-', '') = ?
        """,
        (
            _fmt_monto_txt(pagos_total),
            _fmt_monto_txt(saldo_total),
            estado,
            ahora,
            rut_norm,
        ),
    )

    return {
        "copago": copago_total,
        "total_pagos": pagos_total,
        "saldo_actual": saldo_total,
        "estado_deudor": estado,
    }


def guardar_registros(df: pd.DataFrame, empresa: str, source_file: str = "") -> int:
    df_save = df.copy()
    df_save = df_save[[c for c in df_save.columns if not (c.startswith("_") and c != COL_EMPRESA)]]
    with _conexion(empresa) as con:
        return _merge_table_by_key(
            con=con,
            table=TABLA,
            incoming_df=df_save,
            empresa=empresa,
            source_file=source_file,
            key_builder=_build_merge_key_rut,
            postprocess=_postprocess_resumen,
        )


def guardar_contactos(df_detalle: pd.DataFrame, empresa: str, source_file: str = "") -> int:
    if df_detalle is None or df_detalle.empty:
        return 0

    cols = [c for c in COLS_CONTACTO if c in df_detalle.columns]
    if "Rut_Afiliado" not in cols:
        return 0

    df_c = df_detalle[cols].copy().fillna("")
    for col in cols:
        df_c[col] = (
            df_c[col]
            .astype(str)
            .str.strip()
            .replace({"N": "", "nan": "", "None": "", "NaN": ""})
        )

    if "mail_afiliado" in df_c.columns:
        df_c["_tiene_email"] = df_c["mail_afiliado"].str.contains("@", na=False)
        df_c = (
            df_c.sort_values("_tiene_email", ascending=False)
            .drop_duplicates(subset="Rut_Afiliado", keep="first")
            .drop(columns=["_tiene_email"])
        )

    with _conexion(empresa) as con:
        return _merge_table_by_key(
            con=con,
            table=TABLA_CONTACTOS,
            incoming_df=df_c,
            empresa=empresa,
            source_file=source_file,
            key_builder=_build_merge_key_rut,
            postprocess=_postprocess_contactos,
        )


def guardar_detalle(df_detalle: pd.DataFrame, empresa: str, source_file: str = "") -> int:
    if df_detalle is None or df_detalle.empty:
        return 0

    cols = [c for c in COLS_DETALLE if c in df_detalle.columns]
    if "Rut_Afiliado" not in cols:
        return 0

    df_d = df_detalle[cols].copy().fillna("").astype(str)

    with _conexion(empresa) as con:
        return _merge_table_by_key(
            con=con,
            table=TABLA_DETALLE,
            incoming_df=df_d,
            empresa=empresa,
            source_file=source_file,
            key_builder=_build_merge_key_detalle,
            postprocess=_postprocess_detalle,
        )


def base_deudores_ya_cargada(empresa: str, source_file: str) -> bool:
    source_txt = str(source_file or "").strip()
    if not source_txt:
        return False

    source_name = os.path.basename(source_txt).strip().lower()
    if not source_name:
        return False

    with _conexion(empresa) as con:
        requiere_enriquecimiento = False
        if str(empresa or "").strip().lower() == "cart-56":
            try:
                df_det = _read_table(con, TABLA_DETALLE)
                if not df_det.empty:
                    for col in ("Nombre Afil", "RUT Afil", "Fecha Pago"):
                        if col not in df_det.columns:
                            requiere_enriquecimiento = True
                            break
                    if not requiere_enriquecimiento:
                        for col in ("Nombre Afil", "RUT Afil", "Fecha Pago"):
                            if (
                                df_det[col].astype(str).str.strip().replace({"nan": "", "None": ""}).eq("").any()
                            ):
                                requiere_enriquecimiento = True
                                break
            except Exception:
                requiere_enriquecimiento = False

        for table in (TABLA_DETALLE, TABLA):
            df = _read_table(con, table)
            if df.empty or COL_SOURCE_FILE not in df.columns:
                continue

            loaded_names = (
                df[COL_SOURCE_FILE]
                .astype(str)
                .map(lambda value: os.path.basename(str(value).strip()).lower())
            )
            if loaded_names.eq(source_name).any():
                if requiere_enriquecimiento:
                    return False
                return True

    return False


def _read_table_if_exists(empresa: str, table: str) -> pd.DataFrame:
    path = _db_path(empresa)
    if not os.path.exists(path):
        return pd.DataFrame()

    try:
        with _conexion(empresa) as con:
            row = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not row:
                return pd.DataFrame()

            return pd.read_sql(f'SELECT * FROM "{table}"', con, dtype=str).fillna("")
    except Exception:
        logger.exception("Error leyendo tabla %s de %s", table, empresa)
        return pd.DataFrame()


def cargar_detalle_empresa(empresa: str) -> pd.DataFrame:
    return _read_table_if_exists(empresa, TABLA_DETALLE)


def cargar_detalle_todas() -> pd.DataFrame:
    frames = [cargar_detalle_empresa(e) for e in EMPRESAS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def cargar_empresa(empresa: str) -> pd.DataFrame:
    return _read_table_if_exists(empresa, TABLA)


def cargar_todas() -> pd.DataFrame:
    frames = [cargar_empresa(e) for e in EMPRESAS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def cargar_contactos_empresa(empresa: str) -> pd.DataFrame:
    return _read_table_if_exists(empresa, TABLA_CONTACTOS)


def cargar_empresas(empresas: list[str]) -> pd.DataFrame:
    empresas_norm = [str(e).strip() for e in (empresas or []) if str(e).strip()]
    if not empresas_norm:
        return pd.DataFrame()
    frames = [cargar_empresa(e) for e in empresas_norm]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def cargar_detalle_empresas(empresas: list[str]) -> pd.DataFrame:
    empresas_norm = [str(e).strip() for e in (empresas or []) if str(e).strip()]
    if not empresas_norm:
        return pd.DataFrame()
    frames = [cargar_detalle_empresa(e) for e in empresas_norm]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def hay_datos_empresas(empresas: list[str]) -> bool:
    empresas_norm = [str(e).strip() for e in (empresas or []) if str(e).strip()]
    if not empresas_norm:
        return False
    return any(not cargar_empresa(e).empty for e in empresas_norm)


def cargar_contactos_todas() -> pd.DataFrame:
    frames = [cargar_contactos_empresa(e) for e in EMPRESAS]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def cargar_para_envio(empresa: str = "") -> pd.DataFrame:
    df_deu = cargar_empresa(empresa) if empresa else cargar_todas()
    df_con = cargar_contactos_empresa(empresa) if empresa else cargar_contactos_todas()

    if df_deu.empty:
        return pd.DataFrame()
    if df_con.empty:
        return df_deu

    def _norm_rut(s: pd.Series) -> pd.Series:
        return (
            s.astype(str)
            .str.replace(".", "", regex=False)
            .str.replace("-", "", regex=False)
            .str.strip()
            .str.lstrip("0")
        )

    df_deu = df_deu.copy()
    df_con = df_con.copy()
    df_deu["_rut_norm"] = _norm_rut(df_deu["Rut_Afiliado"])
    df_con["_rut_norm"] = _norm_rut(df_con["Rut_Afiliado"])

    cols_merge = ["_rut_norm", "mail_afiliado"] + [
        c for c in ("telefono_fijo_afiliado", "telefono_movil_afiliado") if c in df_con.columns
    ]

    merged = (
        df_deu.merge(
            df_con[cols_merge].drop_duplicates("_rut_norm"),
            on="_rut_norm",
            how="left",
        )
        .drop(columns=["_rut_norm"])
    )

    merged["mail_afiliado"] = merged.get("mail_afiliado", pd.Series(dtype=str)).fillna("")
    return merged


def stats_por_empresa() -> dict:
    cols_num = {"copago": "Copago", "pagos": "Total_Pagos", "saldo": "Saldo_Actual"}
    resultado = {}
    totales = {"deudores": 0, "copago": 0.0, "pagos": 0.0, "saldo": 0.0}
    ultima_fecha = "—"

    for emp in EMPRESAS:
        df = cargar_empresa(emp)
        if df.empty:
            resultado[emp] = {
                "deudores": 0,
                "copago": 0.0,
                "pagos": 0.0,
                "saldo": 0.0,
                "fecha": "Sin datos",
            }
            continue

        fecha = df[COL_FECHA_CARGA].iloc[-1] if COL_FECHA_CARGA in df.columns else "—"
        ultima_fecha = fecha
        fila = {"deudores": len(df), "fecha": fecha}

        for key, col in cols_num.items():
            fila[key] = sum(_parse_num(v) for v in df[col]) if col in df.columns else 0.0

        resultado[emp] = fila

        for key in ("deudores", "copago", "pagos", "saldo"):
            totales[key] += fila[key]

    resultado["_total"] = totales
    resultado["_fecha"] = ultima_fecha
    return resultado


def stats_por_empresas(empresas: list[str]) -> dict:
    cols_num = {"copago": "Copago", "pagos": "Total_Pagos", "saldo": "Saldo_Actual"}

    empresas_norm = [str(e).strip() for e in (empresas or []) if str(e).strip()]
    resultado: dict = {}

    totales = {
        "deudores": 0,
        "copago": 0.0,
        "pagos": 0.0,
        "saldo": 0.0,
    }
    ultima_fecha = "—"

    for emp in empresas_norm:
        df = cargar_empresa(emp)

        if df.empty:
            resultado[emp] = {
                "deudores": 0,
                "copago": 0.0,
                "pagos": 0.0,
                "saldo": 0.0,
                "fecha": "Sin datos",
            }
            continue

        fecha = df[COL_FECHA_CARGA].iloc[-1] if COL_FECHA_CARGA in df.columns else "—"
        ultima_fecha = fecha

        fila = {
            "deudores": len(df),
            "fecha": fecha,
        }

        for key, col in cols_num.items():
            fila[key] = sum(_parse_num(v) for v in df[col]) if col in df.columns else 0.0

        resultado[emp] = fila

        totales["deudores"] += fila["deudores"]
        totales["copago"] += fila["copago"]
        totales["pagos"] += fila["pagos"]
        totales["saldo"] += fila["saldo"]

    resultado["_total"] = totales
    resultado["_fecha"] = ultima_fecha
    return resultado


def hay_datos() -> bool:
    return any(not cargar_empresa(e).empty for e in EMPRESAS)


def limpiar_empresa(empresa: str) -> bool:
    path = _db_path(empresa)
    if not os.path.exists(path):
        return False

    try:
        with _conexion(empresa) as con:
            for tabla in (TABLA, TABLA_CONTACTOS, TABLA_DETALLE):
                tabla_existe = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (tabla,),
                ).fetchone()
                if tabla_existe:
                    con.execute(f'DELETE FROM "{tabla}"')
            con.commit()
        return True
    except Exception:
        logger.exception("No se pudo limpiar %s", empresa)
        return False


def limpiar_todas() -> list[str]:
    return [e for e in EMPRESAS if limpiar_empresa(e)]


def actualizar_cliente_por_rut(empresa: str, rut_original: str, datos_actualizados: dict) -> bool:
    if not empresa or not str(empresa).strip():
        raise ValueError("No se pudo determinar la empresa del deudor.")

    rut_original_norm = _normalizar_rut(rut_original)
    if not rut_original_norm:
        raise ValueError("El RUT original no es válido.")

    datos_limpios = {
        k: ("" if v is None else str(v).strip())
        for k, v in (datos_actualizados or {}).items()
    }

    columnas_permitidas = {
        "Rut_Afiliado",
        "Nombre_Afiliado",
        "mail_afiliado",
        "BN",
        "telefono_fijo_afiliado",
        "telefono_movil_afiliado",
    }

    datos_limpios = {k: v for k, v in datos_limpios.items() if k in columnas_permitidas}

    if not datos_limpios:
        raise ValueError("No se recibieron campos válidos para actualizar.")

    tablas_objetivo = [TABLA, TABLA_CONTACTOS, TABLA_DETALLE]

    with _conexion(empresa) as con:
        total_updates = 0

        for tabla in tablas_objetivo:
            cols_tabla = {row[1] for row in con.execute(f"PRAGMA table_info({tabla})").fetchall()}

            cols_update = [c for c in datos_limpios.keys() if c in cols_tabla]
            if not cols_update or "Rut_Afiliado" not in cols_tabla:
                continue

            set_clause = ", ".join([f'"{col}"=?' for col in cols_update])
            valores = [datos_limpios[col] for col in cols_update]

            sql = f"""
                UPDATE "{tabla}"
                SET {set_clause}
                WHERE REPLACE(REPLACE(TRIM(Rut_Afiliado), '.', ''), '-', '') = ?
            """

            cur = con.execute(sql, valores + [rut_original_norm])
            total_updates += cur.rowcount

        con.commit()

    return total_updates > 0


def registrar_pago_por_rut(empresa: str, rut: str, tipo_pago: str, monto: float, expediente: str) -> dict:
    empresa = str(empresa or "").strip()
    rut_norm = _normalizar_rut(rut)
    expediente = str(expediente or "").strip()

    if not empresa:
        raise ValueError("No se pudo determinar la empresa del deudor.")
    if not rut_norm:
        raise ValueError("RUT inválido.")
    if not expediente:
        raise ValueError("Debes seleccionar un expediente.")
    if float(monto) <= 0:
        raise ValueError("El monto debe ser mayor a 0.")

    with _conexion(empresa) as con:
        _ensure_column(con, TABLA, "Total_Pagos", "TEXT")
        _ensure_column(con, TABLA, "Saldo_Actual", "TEXT")
        _ensure_column(con, TABLA, "Estado_deudor", "TEXT")
        _ensure_column(con, TABLA, COL_FECHA_CARGA, "TEXT")
        _ensure_column(con, TABLA_DETALLE, "Total_Pagos", "TEXT")
        _ensure_column(con, TABLA_DETALLE, "Saldo_Actual", "TEXT")
        _ensure_column(con, TABLA_DETALLE, "Estado_deudor", "TEXT")
        _ensure_column(con, TABLA_DETALLE, COL_FECHA_CARGA, "TEXT")

        filas = _obtener_filas_detalle_por_rut_y_expediente(con, rut_norm, expediente)

        if filas.empty:
            raise ValueError("No se encontró el expediente seleccionado para este deudor.")

        fila = filas.iloc[0]
        copago = _parse_num(fila.get("Copago", 0))
        total_pagos_actual = _parse_num(fila.get("Total_Pagos", 0))
        saldo_actual = _parse_num(fila.get("Saldo_Actual", 0))
        if saldo_actual <= 0:
            saldo_actual = max(copago - total_pagos_actual, 0.0)

        tipo_pago_txt = str(tipo_pago or "").strip().lower()
        monto_f = float(monto)

        if tipo_pago_txt == "pago total de la deuda" and round(monto_f, 2) != round(saldo_actual, 2):
            raise ValueError("Monto no corresponde al Saldo Actual, verificar monto de pago")

        nuevo_total_pagos = total_pagos_actual + monto_f
        nuevo_saldo = max(copago - nuevo_total_pagos, 0.0)
        nuevo_estado_detalle = "Cliente Sin deuda" if round(nuevo_saldo, 2) == 0 else "Gestionado"

        ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        con.execute(
            f"""
            UPDATE "{TABLA_DETALLE}"
            SET Total_Pagos = ?, Saldo_Actual = ?, Estado_deudor = ?, {COL_FECHA_CARGA} = ?
            WHERE REPLACE(REPLACE(TRIM(Rut_Afiliado), '.', ''), '-', '') = ?
              AND TRIM(Nro_Expediente) = ?
            """,
            (
                _fmt_monto_txt(nuevo_total_pagos),
                _fmt_monto_txt(nuevo_saldo),
                nuevo_estado_detalle,
                ahora,
                rut_norm,
                expediente,
            ),
        )

        resultado = _recalcular_resumen_desde_detalle(con, rut_norm)

        if resultado.get("estado_deudor") == "Cliente Sin deuda":
            con.execute(
                f"""
                UPDATE "{TABLA_DETALLE}"
                SET Estado_deudor = ?, {COL_FECHA_CARGA} = ?
                WHERE REPLACE(REPLACE(TRIM(Rut_Afiliado), '.', ''), '-', '') = ?
                """,
                ("Cliente Sin deuda", ahora, rut_norm),
            )

        con.commit()
        return resultado


def revertir_pago_por_rut(empresa: str, rut: str, expediente: str, monto: float) -> dict:
    empresa = str(empresa or "").strip()
    rut_norm = _normalizar_rut(rut)
    expediente = str(expediente or "").strip()
    monto_f = float(monto or 0)

    if not empresa:
        raise ValueError("Empresa inválida.")
    if not rut_norm:
        raise ValueError("RUT inválido.")
    if not expediente:
        raise ValueError("Expediente inválido.")
    if monto_f <= 0:
        raise ValueError("Monto inválido para reversa.")

    with _conexion(empresa) as con:
        _ensure_column(con, TABLA, "Total_Pagos", "TEXT")
        _ensure_column(con, TABLA, "Saldo_Actual", "TEXT")
        _ensure_column(con, TABLA, "Estado_deudor", "TEXT")
        _ensure_column(con, TABLA_DETALLE, "Total_Pagos", "TEXT")
        _ensure_column(con, TABLA_DETALLE, "Saldo_Actual", "TEXT")
        _ensure_column(con, TABLA_DETALLE, "Estado_deudor", "TEXT")

        filas = _obtener_filas_detalle_por_rut_y_expediente(con, rut_norm, expediente)
        if filas.empty:
            raise ValueError("No se encontró el expediente para revertir el pago.")

        fila = filas.iloc[0]
        copago = _parse_num(fila.get("Copago", 0))
        total_pagos_actual = _parse_num(fila.get("Total_Pagos", 0))

        nuevo_total_pagos = max(total_pagos_actual - monto_f, 0.0)
        nuevo_saldo = max(copago - nuevo_total_pagos, 0.0)
        nuevo_estado_detalle = "Cliente Sin deuda" if round(nuevo_saldo, 2) == 0 else "Gestionado"

        ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        con.execute(
            f"""
            UPDATE "{TABLA_DETALLE}"
            SET Total_Pagos = ?, Saldo_Actual = ?, Estado_deudor = ?, {COL_FECHA_CARGA} = ?
            WHERE REPLACE(REPLACE(TRIM(Rut_Afiliado), '.', ''), '-', '') = ?
              AND TRIM(Nro_Expediente) = ?
            """,
            (
                _fmt_monto_txt(nuevo_total_pagos),
                _fmt_monto_txt(nuevo_saldo),
                nuevo_estado_detalle,
                ahora,
                rut_norm,
                expediente,
            ),
        )

        resultado = _recalcular_resumen_desde_detalle(con, rut_norm)
        con.commit()
        return resultado
