# ================================================================
#  deudores/schema_detalle.py
#
#  CONFIGURACIÓN DE LA HOJA "DETALLE"
# ================================================================

from __future__ import annotations

import pandas as pd


HOJA_DETALLE: str = "DETALLE"
HOJA_RESUMEN: str = "RESUMEN"

COL_RUT_DETALLE: str = "Rut_Afiliado"


# ------------------------------------------------
# Configuración base (otras compañías)
# ------------------------------------------------
CAMPOS_CLIENTE_BASE: list[tuple[str, str]] = [
    ("RUT", "_RUT_COMPLETO"),
    ("Nombre", "Nombre_Afiliado"),
    ("Correo", "mail_afiliado"),
    ("Correo (Excel)", "BN"),
    ("Teléfono Fijo", "telefono_fijo_afiliado"),
    ("Teléfono Móvil", "telefono_movil_afiliado"),
]

COLUMNAS_DETALLE_DEUDA_BASE: list[tuple[str, str]] = [
    ("N° Expediente", "Nro_Expediente"),
    ("Nombre Afil", "Nombre Afil"),
    ("RUT Afil", "RUT Afil"),
    ("Fecha Pago", "Fecha Pago"),
    ("Fecha Emisión", "Fecha_Emision"),
    ("Copago ($)", "Copago"),
    ("Total Pagos ($)", "Total_Pagos"),
    ("Saldo Actual ($)", "Saldo_Actual"),
    ("Correo", "mail_afiliado"),
]


# ------------------------------------------------
# Configuración Cart-56
# ------------------------------------------------
CAMPOS_CLIENTE_CART56: list[tuple[str, str]] = [
    ("RUT", "_RUT_COMPLETO"),
    ("Nombre", "Nombre_Afiliado"),
    ("Correo", "mail_afiliado"),
    ("Correo (Excel)", "BN"),
    ("Teléfono Fijo", "telefono_fijo_afiliado"),
    ("Teléfono Móvil", "telefono_movil_afiliado"),
]

COLUMNAS_DETALLE_DEUDA_CART56: list[tuple[str, str]] = [
    ("No Licencia", "Nro_Expediente"),
    ("Nombre Afil", "Nombre Afil"),
    ("RUT Afil", "RUT Afil"),
    ("Fecha Pago", "Fecha Pago"),
    ("Fecha Recep", "Cart56_Fecha_Recep"),
    ("Fecha Recep ISA", "Cart56_Fecha_Recep_ISA"),
    ("Dias Pagar", "Cart56_Dias_Pagar"),
    ("Mto Pagar", "Copago"),
    ("Pagos", "Total_Pagos"),
    ("Saldo Actual", "Saldo_Actual"),
    ("Correo", "mail_afiliado"),
]


CAMPOS_CLIENTE: list[tuple[str, str]] = list(CAMPOS_CLIENTE_BASE)
COLUMNAS_DETALLE_DEUDA: list[tuple[str, str]] = list(COLUMNAS_DETALLE_DEUDA_BASE)

COLUMNAS_DETALLE_NUMERICAS_BASE: list[str] = [
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
]

COLUMNAS_DETALLE_FECHA_BASE: list[str] = [
    "Fecha_Emision",
    "Fecha Pago",
]

COLUMNAS_DETALLE_NUMERICAS_CART56: list[str] = [
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
]

COLUMNAS_DETALLE_FECHA_CART56: list[str] = [
    "Cart56_Fecha_Recep",
    "Cart56_Fecha_Recep_ISA",
    "Fecha Pago",
]

COLUMNAS_DETALLE_NUMERICAS: list[str] = list(COLUMNAS_DETALLE_NUMERICAS_BASE)
COLUMNAS_DETALLE_FECHA: list[str] = list(COLUMNAS_DETALLE_FECHA_BASE)


def _configurar_layout_detalle_para_empresa(empresa: str) -> None:
    empresa_txt = str(empresa or "").strip().lower()

    if empresa_txt == "cart-56":
        CAMPOS_CLIENTE[:] = CAMPOS_CLIENTE_CART56
        COLUMNAS_DETALLE_DEUDA[:] = COLUMNAS_DETALLE_DEUDA_CART56
        COLUMNAS_DETALLE_NUMERICAS[:] = COLUMNAS_DETALLE_NUMERICAS_CART56
        COLUMNAS_DETALLE_FECHA[:] = COLUMNAS_DETALLE_FECHA_CART56
    else:
        CAMPOS_CLIENTE[:] = CAMPOS_CLIENTE_BASE
        COLUMNAS_DETALLE_DEUDA[:] = COLUMNAS_DETALLE_DEUDA_BASE
        COLUMNAS_DETALLE_NUMERICAS[:] = COLUMNAS_DETALLE_NUMERICAS_BASE
        COLUMNAS_DETALLE_FECHA[:] = COLUMNAS_DETALLE_FECHA_BASE


def _valor_limpio(val) -> str:
    txt = str(val or "").strip()
    return "" if txt.lower() in ("", "nan", "none", "nat", "n") else txt


def _parse_numero_crudo(val) -> float:
    txt = _valor_limpio(val)
    if not txt:
        return 0.0

    txt = txt.replace("$", "").replace(" ", "")

    if "," in txt and "." not in txt:
        partes = txt.split(",")
        if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
            txt = "".join(partes)
        else:
            txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "." in txt:
        partes = txt.split(".")
        if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
            txt = "".join(partes)

    try:
        return float(txt)
    except Exception:
        return 0.0


def _fmt_numero(val: str) -> str:
    try:
        n = _parse_numero_crudo(val)
        return f"$ {int(round(n)):,}".replace(",", ".")
    except Exception:
        return str(val)


def _parse_fecha_segura(v: str):
    """
    Evita warnings de pandas cuando la fecha ya viene en formato ISO
    (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS) y usa dayfirst=True solo cuando
    corresponde a formatos tipo dd/mm/yyyy.
    """
    texto = str(v or "").strip()
    if not texto:
        return pd.NaT

    formatos_directos = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y",
        "%d-%m-%Y %H:%M:%S",
    )

    for fmt in formatos_directos:
        try:
            return pd.to_datetime(texto, format=fmt, errors="raise")
        except Exception:
            pass

    if "/" in texto or "-" in texto:
        try:
            return pd.to_datetime(texto, errors="coerce", dayfirst=True)
        except Exception:
            return pd.NaT

    try:
        return pd.to_datetime(texto, errors="coerce")
    except Exception:
        return pd.NaT


def _fmt_fecha(val: str) -> str:
    v = str(val or "").strip()
    if not v or v.lower() in ("nan", "nat", "none", ""):
        return "—"
    try:
        ts = _parse_fecha_segura(v)
        if pd.isna(ts):
            return v
        return ts.strftime("%d/%m/%Y")
    except Exception:
        return v


def _armar_rut_completo_desde_fila(row) -> str:
    rut = _valor_limpio(row.get("Rut_Afiliado", ""))
    dv = _valor_limpio(row.get("Dv", ""))

    rut = rut.replace(".", "").replace("-", "").lstrip("0")

    if rut and dv:
        return f"{rut}-{dv}"
    if rut:
        return rut

    rut_full = _valor_limpio(row.get("_RUT_COMPLETO", ""))
    return rut_full or "—"


def _resolver_email_fila(row) -> str:
    candidatos = [
        "mail_afiliado",
        "Mail Emp",
        "BN",
        "Correo",
        "Email",
    ]
    for col in candidatos:
        val = _valor_limpio(row.get(col, ""))
        if val and "@" in val:
            return val
    return "—"


def _resolver_telefono_fila(row) -> str:
    candidatos = [
        "telefono_fijo_afiliado",
        "Telefono Empleador",
        "Teléfono Empleador",
        "telefono_movil_afiliado",
    ]
    for col in candidatos:
        val = _valor_limpio(row.get(col, ""))
        if val:
            return val
    return "—"


def _resolver_telefono_movil_fila(row) -> str:
    candidatos = [
        "telefono_movil_afiliado",
        "Telefono Empleador",
        "Teléfono Empleador",
        "telefono_fijo_afiliado",
    ]
    for col in candidatos:
        val = _valor_limpio(row.get(col, ""))
        if val:
            return val
    return "—"


def _fmt_valor(val: str, col_original: str) -> str:
    if col_original in COLUMNAS_DETALLE_NUMERICAS:
        return _fmt_numero(val)
    if col_original in COLUMNAS_DETALLE_FECHA:
        return _fmt_fecha(val)
    if str(val).strip() in ("", "N", "nan", "None"):
        return "—"
    return str(val)


def extraer_detalle_deudor(df_detalle_completo, rut: str):
    """
    Filtra el DataFrame de DETALLE por RUT y devuelve:
      - info_cliente: dict {etiqueta: valor}
      - filas_deuda: list[dict]
    Además ajusta en caliente las etiquetas visibles del detalle
    según la compañía.
    """
    rut_txt = str(rut).strip().replace(".", "")
    if "-" in rut_txt:
        rut_txt = rut_txt.split("-", 1)[0]
    rut_norm = rut_txt.replace("-", "").lstrip("0")

    mascara = (
        df_detalle_completo[COL_RUT_DETALLE]
        .astype(str)
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace("-", "", regex=False)
        .str.lstrip("0")
        == rut_norm
    )
    filas = df_detalle_completo[mascara]

    if filas.empty:
        _configurar_layout_detalle_para_empresa("")
        return {}, []

    primera = filas.iloc[0]
    empresa = str(primera.get("_empresa", "")).strip()
    _configurar_layout_detalle_para_empresa(empresa)

    info_cliente = {}
    for etq, col in CAMPOS_CLIENTE:
        if etq == "RUT":
            info_cliente[etq] = _armar_rut_completo_desde_fila(primera)
            continue

        if etq == "Correo":
            info_cliente[etq] = _resolver_email_fila(primera)
            continue

        if etq == "Correo (Excel)":
            correo_excel = _valor_limpio(primera.get("BN", "")) or _resolver_email_fila(primera)
            info_cliente[etq] = correo_excel if correo_excel else "—"
            continue

        if etq == "Teléfono Fijo":
            info_cliente[etq] = _resolver_telefono_fila(primera)
            continue

        if etq == "Teléfono Móvil":
            info_cliente[etq] = _resolver_telefono_movil_fila(primera)
            continue

        val = str(primera.get(col, "")).strip()
        info_cliente[etq] = _fmt_valor(val, col) if col not in (
            "Rut_Afiliado",
            "Nombre_Afiliado",
        ) else (val if val not in ("", "nan", "None") else "—")

    filas_deuda = []
    for _, row in filas.iterrows():
        entrada = {}
        for etq, col in COLUMNAS_DETALLE_DEUDA:
            if col == "mail_afiliado":
                entrada[etq] = _resolver_email_fila(row)
            else:
                val = str(row.get(col, "")).strip()
                entrada[etq] = _fmt_valor(val, col)
        filas_deuda.append(entrada)

    return info_cliente, filas_deuda
