# ================================================================
#  deudores/schema_formato_c.py
#
#  PERFIL DE IMPORTACIÓN - FORMATO C
#  ─────────────────────────────────
#  Este archivo define un tercer tipo de estructura de Excel.
#
#  La idea es que aquí adaptes otro diseño distinto del archivo:
#   - otros nombres de hoja
#   - otras columnas
#   - otro orden
#   - otro detalle
# ================================================================


# ================================================================
#  1. CONFIGURACIÓN DE RESUMEN
# ================================================================

HOJA_RESUMEN: str = "Resumen"

COLUMNAS_OBLIGATORIAS: list[str] = [
    "Rut",
    "Nombre",
]

EXCLUIR_EXACTAS: list[str] = [
    # Ejemplo:
    # "Notas",
]

EXCLUIR_PREFIJOS: list[str] = [
    # Ejemplo:
    # "TMP_",
]

COLUMNA_EMPRESA: str = "_empresa"

COLUMNA_RUT: str = "Rut"
COLUMNA_DV: str = "Dv"

ETIQUETAS: dict[str, str] = {
    "_empresa":      "Compañía",
    "Rut":           "RUT",
    "Dv":            "DV",
    "Nombre":        "Nombre",
    "Correo":        "Email",
    "Expediente":    "N° Expediente",
    "FechaEmision":  "Fecha Emisión",
    "MontoCopago":   "Copago ($)",
    "Pagado":        "Total Pagos ($)",
    "Saldo":         "Saldo Actual ($)",
}

ORDEN_COLUMNAS: list[str] = [
    "Rut",
    "Dv",
    "Nombre",
    "Correo",
    "Expediente",
    "FechaEmision",
    "MontoCopago",
    "Pagado",
    "Saldo",
]

COLUMNAS_NUMERICAS: list[str] = [
    "MontoCopago",
    "Pagado",
    "Saldo",
]

COLUMNAS_FECHA_YYYYMM: list[str] = [
    # Ejemplo:
    # "PeriodoCobro",
]


# ================================================================
#  2. CONFIGURACIÓN DE DETALLE
# ================================================================

HOJA_DETALLE: str = "Detalle"
COL_RUT_DETALLE: str = "Rut"

CAMPOS_CLIENTE: list[tuple[str, str]] = [
    ("RUT",            "Rut"),
    ("Nombre",         "Nombre"),
    ("Correo",         "Correo"),
    ("Teléfono Fijo",  "TelefonoFijo"),
    ("Teléfono Móvil", "TelefonoMovil"),
]

COLUMNAS_DETALLE_DEUDA: list[tuple[str, str]] = [
    ("N° Expediente",   "Expediente"),
    ("Fecha Emisión",   "FechaEmision"),
    ("Copago ($)",      "MontoCopago"),
    ("Total Pagos ($)", "Pagado"),
    ("Saldo Actual ($)","Saldo"),
    ("Correo",          "Correo"),
]

COLUMNAS_DETALLE_NUMERICAS: list[str] = [
    "MontoCopago",
    "Pagado",
    "Saldo",
]

COLUMNAS_DETALLE_FECHA: list[str] = [
    "FechaEmision",
]


# ================================================================
#  3. FUNCIONES AUXILIARES PARA RESUMEN
# ================================================================

def _fmt_numero(val: str) -> str:
    try:
        n = float(str(val).replace(",", "").replace(".", ""))
        return f"{int(n):,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(val)


def _fmt_fecha_yyyymm(val: str) -> str:
    v = str(val).strip().replace(".0", "")
    if len(v) == 6 and v.isdigit():
        return f"{v[4:6]}/{v[0:4]}"
    return v


def aplicar_schema(df, empresa: str = ""):
    import pandas as pd

    col_map_norm = {c: c.strip() for c in df.columns}
    df = df.rename(columns=col_map_norm)

    def _excluir(col: str) -> bool:
        c_upper = col.upper()
        if col.upper() in [e.upper() for e in EXCLUIR_EXACTAS]:
            return True
        for pref in EXCLUIR_PREFIJOS:
            if c_upper.startswith(pref.upper()):
                return True
        return False

    cols_visibles_raw = [c for c in df.columns if not _excluir(c)]

    cols_en_orden = [c for c in ORDEN_COLUMNAS if c in cols_visibles_raw]
    cols_resto = [c for c in cols_visibles_raw if c not in cols_en_orden]
    columnas = cols_en_orden + cols_resto

    df_vista = df[columnas].copy()

    if empresa:
        df_vista.insert(0, COLUMNA_EMPRESA, empresa)
        columnas = [COLUMNA_EMPRESA] + columnas

    for col in COLUMNAS_NUMERICAS:
        if col in df_vista.columns:
            df_vista[col] = df_vista[col].apply(_fmt_numero)

    for col in COLUMNAS_FECHA_YYYYMM:
        if col in df_vista.columns:
            df_vista[col] = df_vista[col].apply(_fmt_fecha_yyyymm)

    if COLUMNA_RUT and COLUMNA_RUT in df.columns:
        rut_base = (
            df[COLUMNA_RUT].astype(str)
            .str.replace(".", "", regex=False)
            .str.replace("-", "", regex=False)
            .str.strip()
        )
        if COLUMNA_DV and COLUMNA_DV in df.columns:
            dv_base = df[COLUMNA_DV].astype(str).str.strip()
            df_vista["_RUT_COMPLETO"] = rut_base + "-" + dv_base
        else:
            df_vista["_RUT_COMPLETO"] = rut_base

    etiquetas = [ETIQUETAS.get(c, c) for c in columnas]
    return df_vista, columnas, etiquetas


# ================================================================
#  4. FUNCIONES AUXILIARES PARA DETALLE
# ================================================================

def _fmt_fecha_detalle(val: str) -> str:
    v = str(val).strip()
    if not v or v.lower() in ("nan", "nat", "none", ""):
        return "—"
    try:
        import pandas as pd
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return v
        return ts.strftime("%d/%m/%Y")
    except Exception:
        return v


def _fmt_valor_detalle(val: str, col_original: str) -> str:
    if col_original in COLUMNAS_DETALLE_NUMERICAS:
        return _fmt_numero(val)
    if col_original in COLUMNAS_DETALLE_FECHA:
        return _fmt_fecha_detalle(val)
    if str(val).strip() in ("", "N", "nan", "None"):
        return "—"
    return str(val)


def extraer_detalle_deudor(df_detalle_completo, rut: str):
    rut_norm = str(rut).strip().replace(".", "").replace("-", "")

    mascara = (
        df_detalle_completo[COL_RUT_DETALLE]
        .astype(str).str.strip()
        .str.replace(".", "", regex=False)
        .str.replace("-", "", regex=False)
        == rut_norm
    )
    filas = df_detalle_completo[mascara]

    if filas.empty:
        return {}, []

    primera = filas.iloc[0]

    info_cliente = {}
    for etq, col in CAMPOS_CLIENTE:
        val = str(primera.get(col, "")).strip()
        info_cliente[etq] = _fmt_valor_detalle(val, col) if col not in (
            "Rut", "Nombre"
        ) else (val if val not in ("", "nan", "None") else "—")

    filas_deuda = []
    for _, row in filas.iterrows():
        entrada = {}
        for etq, col in COLUMNAS_DETALLE_DEUDA:
            val = str(row.get(col, "")).strip()
            entrada[etq] = _fmt_valor_detalle(val, col)
        filas_deuda.append(entrada)

    return info_cliente, filas_deuda