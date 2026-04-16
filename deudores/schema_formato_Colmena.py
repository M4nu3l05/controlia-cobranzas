# ================================================================
#  deudores/schema_formato_b.py
#
#  PERFIL DE IMPORTACIÓN - FORMATO B
#  ─────────────────────────────────
#  Este archivo define cómo leer un Excel de deudores cuando
#  la estructura del archivo NO coincide con schema.py +
#  schema_detalle.py.
#
#  Aquí se configura:
#   - Hoja RESUMEN
#   - Hoja DETALLE
#   - Columnas obligatorias
#   - Etiquetas visibles
#   - Orden de columnas
#   - Extracción del detalle del deudor
# ================================================================


# ================================================================
#  1. CONFIGURACIÓN DE RESUMEN
# ================================================================

# Nombre exacto de la hoja principal del Excel.
HOJA_RESUMEN: str = "RESUMEN"

# Columnas mínimas que deben existir para aceptar el archivo.
COLUMNAS_OBLIGATORIAS: list[str] = [
    "Rut_Afiliado",
    "Nombre_Afiliado",
]

# Columnas que NO quieres mostrar nunca en la tabla principal.
EXCLUIR_EXACTAS: list[str] = [
    # Ejemplo:
    # "Observacion_Interna",
]

# Excluye cualquier columna cuyo nombre empiece con estos prefijos.
EXCLUIR_PREFIJOS: list[str] = [
    "GES_",
]

# Columna virtual agregada por la app.
COLUMNA_EMPRESA: str = "_empresa"

# Nombre de la columna RUT del Excel.
COLUMNA_RUT: str = "Rut_Afiliado"

# Nombre de la columna DV del Excel.
COLUMNA_DV: str = "Dv"

# Etiquetas visibles en la tabla principal.
ETIQUETAS: dict[str, str] = {
    "_empresa":        "Compañía",
    "Rut_Afiliado":    "RUT",
    "Dv":              "DV",
    "Nombre_Afiliado": "Nombre",
    "BN":              "Email",
    "Nro_Expediente":  "N° Expediente",
    "Fecha_Emision":   "Fecha Emisión",
    "Copago":          "Copago ($)",
    "Total_Pagos":     "Total Pagos ($)",
    "Saldo_Actual":    "Saldo Actual ($)",
}

# Orden visual de la tabla principal.
ORDEN_COLUMNAS: list[str] = [
    "Rut_Afiliado",
    "Dv",
    "Nombre_Afiliado",
    "BN",
    "Nro_Expediente",
    "Fecha_Emision",
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
]

# Columnas numéricas que se deben formatear con miles.
COLUMNAS_NUMERICAS: list[str] = [
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
]

# Columnas de fecha con formato YYYYMM si este formato lo usa.
COLUMNAS_FECHA_YYYYMM: list[str] = [
    # Ejemplo:
    # "Periodo",
]


# ================================================================
#  2. CONFIGURACIÓN DE DETALLE
# ================================================================

# Nombre exacto de la hoja de detalle en este formato.
HOJA_DETALLE: str = "DETALLE"

# Columna clave para vincular resumen y detalle.
COL_RUT_DETALLE: str = "Rut_Afiliado"

# Campos visibles en la tarjeta "Datos del cliente".
CAMPOS_CLIENTE: list[tuple[str, str]] = [
    ("RUT",            "Rut_Afiliado"),
    ("Nombre",         "Nombre_Afiliado"),
    ("Correo",         "mail_afiliado"),
    ("Correo (Excel)", "BN"),
    ("Teléfono Fijo",  "telefono_fijo_afiliado"),
    ("Teléfono Móvil", "telefono_movil_afiliado"),
]

# Columnas visibles en la tabla "Detalle de deuda".
COLUMNAS_DETALLE_DEUDA: list[tuple[str, str]] = [
    ("N° Expediente",   "Nro_Expediente"),
    ("Fecha Emisión",   "Fecha_Emision"),
    ("Copago ($)",      "Copago"),
    ("Total Pagos ($)", "Total_Pagos"),
    ("Saldo Actual ($)","Saldo_Actual"),
    ("Correo",          "mail_afiliado"),
]

# Columnas numéricas del detalle.
COLUMNAS_DETALLE_NUMERICAS: list[str] = [
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
]

# Columnas fecha del detalle.
COLUMNAS_DETALLE_FECHA: list[str] = [
    "Fecha_Emision",
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
    """
    Prepara la hoja RESUMEN de este formato para mostrarla en la tabla principal.
    """
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
    """
    Filtra la hoja DETALLE por RUT y construye:
      - tarjeta de datos del cliente
      - tabla de expedientes
    """
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
            "Rut_Afiliado", "Nombre_Afiliado"
        ) else (val if val not in ("", "nan", "None") else "—")

    filas_deuda = []
    for _, row in filas.iterrows():
        entrada = {}
        for etq, col in COLUMNAS_DETALLE_DEUDA:
            val = str(row.get(col, "")).strip()
            entrada[etq] = _fmt_valor_detalle(val, col)
        filas_deuda.append(entrada)

    return info_cliente, filas_deuda