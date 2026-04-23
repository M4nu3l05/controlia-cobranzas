# ================================================================
#  deudores/schema.py
# ================================================================

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

import pandas as pd


COLUMNAS_OBLIGATORIAS: list[str] = [
    "Rut_Afiliado",
    "Nombre_Afiliado",
]


EXCLUIR_EXACTAS: list[str] = [
    "BN",
]

EXCLUIR_PREFIJOS: list[str] = [
    "GES_",
]


COLUMNA_EMPRESA: str = "_empresa"


ETIQUETAS: dict[str, str] = {
    "_empresa": "Compañía",
    "Rut_Afiliado": "RUT",
    "Dv": "DV",
    "Nombre_Afiliado": "Nombre",
    "Estado_deudor": "Estado deudor",
    "BN": "Email",
    "Nro_Expediente": "N° Expediente",
    "MAX_Emision_ok": "Última Emisión",
    "MIN_Emision_ok": "Primera Emisión",
    "Copago": "Copago ($)",
    "Total_Pagos": "Total Pagos ($)",
    "Saldo_Actual": "Saldo Actual ($)",
}


ORDEN_COLUMNAS: list[str] = [
    "Rut_Afiliado",
    "Dv",
    "Nombre_Afiliado",
    "Estado_deudor",
    "Nro_Expediente",
    "MAX_Emision_ok",
    "MIN_Emision_ok",
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
]


COLUMNAS_NUMERICAS: list[str] = [
    "Copago",
    "Total_Pagos",
    "Saldo_Actual",
]


COLUMNAS_FECHA_YYYYMM: list[str] = [
    "MAX_Emision_ok",
    "MIN_Emision_ok",
]


COLUMNA_RUT: str = "Rut_Afiliado"
COLUMNA_DV: str = "Dv"

HOJA_EXCEL: str = "RESUMEN"


# ================================================================
#  CONFIG CART-56
# ================================================================

CART56_COLUMNAS_MINIMAS: list[str] = [
    "RUT Emp",
    "Mto Pagar",
]

CART56_NO_LICENCIA_CANDIDATAS: list[str] = [
    "No Licencia",
    "No. Licencia",
    "N° Licencia",
    "Nº Licencia",
    "Nro Licencia",
    "Folio LIQ",
]

CART56_DIAS_PAGAR_CANDIDATAS: list[str] = [
    "Dias Pagar",
    "Días Pagar",
    "Dias de Pagar",
    "Días de Pagar",
]

CART56_NOMBRE_EMPRESA_CANDIDATAS: list[str] = [
    "Empresa",
    "Razon social",
    "Razon Social",
    "Razón social",
    "Razón Social",
    "Nombre Empresa",
    "Nombre_Empresa",
    "Empleador",
]

CART56_EMAIL_CANDIDATAS: list[str] = [
    "mail_afiliado",
    "Mail Emp",
    "Email",
    "Correo",
    "Correo Empresa",
    "Mail Empresa",
]

CART56_TEL_FIJO_CANDIDATAS: list[str] = [
    "telefono_fijo_afiliado",
    "Telefono Empleador",
    "Teléfono Empleador",
    "Telefono Fijo",
    "Teléfono Fijo",
    "Fono",
]

CART56_TEL_MOVIL_CANDIDATAS: list[str] = [
    "telefono_movil_afiliado",
    "Telefono Empleador",
    "Teléfono Empleador",
    "Telefono Movil",
    "Teléfono Móvil",
    "Celular",
    "Movil",
    "Móvil",
]

CART56_FECHA_RECEP_CANDIDATAS: list[str] = [
    "Fecha Recep",
    "Fecha Recep ",
]

CART56_FECHA_RECEP_ISA_CANDIDATAS: list[str] = [
    "Fecha Recep ISA",
]

CART56_NOMBRE_AFIL_CANDIDATAS: list[str] = [
    "Nombre Afil",
    "Nombre Afiliado",
    "Nom Afil",
]

CART56_RUT_AFIL_CANDIDATAS: list[str] = [
    "RUT Afil",
    "Rut Afil",
    "RUT Afiliado",
    "Rut Afiliado",
]

CART56_FECHA_PAGO_CANDIDATAS: list[str] = [
    "Fecha Pago",
    "Fecha de Pago",
    "Fec Pago",
]


# ================================================================
#  AUXILIARES
# ================================================================

def _col_map_case_insensitive(df: pd.DataFrame) -> dict[str, str]:
    return {str(c).strip().upper(): str(c) for c in df.columns}


def _normalizar_nombre_columna(nombre: str) -> str:
    txt = str(nombre or "").strip().lower()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^a-z0-9]+", "", txt)
    return txt


def _buscar_columna(df: pd.DataFrame, candidatos: Iterable[str]) -> str:
    mapa = _col_map_case_insensitive(df)
    mapa_norm = {_normalizar_nombre_columna(c): str(c) for c in df.columns}
    for c in candidatos:
        real = mapa.get(str(c).strip().upper())
        if real:
            return real
        real_norm = mapa_norm.get(_normalizar_nombre_columna(c))
        if real_norm:
            return real_norm
    return ""


def _valor_limpio(v) -> str:
    txt = str(v or "").strip()
    return "" if txt.lower() in ("", "nan", "none", "nat", "n") else txt


def _primer_no_vacio(serie: pd.Series) -> str:
    for val in serie.tolist():
        txt = _valor_limpio(val)
        if txt:
            return txt
    return ""


def _normalizar_rut_dv(valor: str) -> tuple[str, str]:
    txt = _valor_limpio(valor).replace(".", "")
    if not txt:
        return "", ""

    if "-" in txt:
        base, dv = txt.rsplit("-", 1)
        return base.strip().lstrip("0"), dv.strip().upper()

    solo = txt.replace("-", "").strip().lstrip("0")
    return solo, ""


def _normalizar_rut_dv_desde_fila(rut_valor, dv_valor="", rut_completo="") -> tuple[str, str, str]:
    rut_base, dv_base = _normalizar_rut_dv(rut_completo or rut_valor)
    dv_txt = _valor_limpio(dv_valor).upper() or dv_base
    rut_txt = rut_base
    rut_full = f"{rut_txt}-{dv_txt}" if rut_txt and dv_txt else rut_txt
    return rut_txt, dv_txt, rut_full


def _parse_monto(valor) -> float:
    txt = _valor_limpio(valor)
    if not txt:
        return 0.0

    txt = txt.replace("$", "").replace(" ", "")

    if "." in txt and "," not in txt:
        txt = txt.replace(".", "")
    elif "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(".", "").replace(",", ".")

    try:
        return float(txt)
    except Exception:
        return 0.0


def _monto_a_texto(valor: float) -> str:
    try:
        return str(int(round(float(valor))))
    except Exception:
        return "0"


def _yyyymm_desde_fecha(valor) -> str:
    txt = _valor_limpio(valor)
    if not txt:
        return ""

    ts = pd.to_datetime(txt, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y%m")


def _normalizar_fecha(val) -> str:
    txt = _valor_limpio(val)
    if not txt:
        return ""

    ts = pd.to_datetime(txt, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return txt
    return ts.strftime("%d/%m/%Y")


def _formatear_moneda_cl(valor):
    try:
        if valor is None:
            return "—"

        v = str(valor).strip()
        if v.lower() in ("", "nan", "none"):
            return "—"

        n = _parse_monto(v)
        return f"$ {int(round(n)):,}".replace(",", ".")
    except Exception:
        return str(valor)


def _formatear_fecha_general(valor) -> str:
    v = str(valor or "").strip().replace(".0", "")
    if not v or v.lower() in ("nan", "none", "nat"):
        return "—"

    if len(v) == 6 and v.isdigit():
        return v

    ts = pd.to_datetime(v, errors="coerce", dayfirst=True)
    if not pd.isna(ts):
        return ts.strftime("%Y%m")

    return v


# ================================================================
#  CART-56 → TRANSFORMACIÓN A ESQUEMA ESTÁNDAR
# ================================================================

def transformar_cart56_raw(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convierte la base cruda de Cart-56 al esquema estándar del CRM.

    Retorna:
      - df_resumen_std
      - df_detalle_std
    """
    if df_raw is None or df_raw.empty:
        raise ValueError("La base de Cart-56 está vacía.")

    df = df_raw.copy()
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    df = df.fillna("")

    faltantes = [c for c in CART56_COLUMNAS_MINIMAS if not _buscar_columna(df, [c])]
    col_no_licencia = _buscar_columna(df, CART56_NO_LICENCIA_CANDIDATAS)
    if not col_no_licencia:
        faltantes.append("No Licencia/Folio LIQ")
    if faltantes:
        raise ValueError(
            "La base de Cart-56 no contiene las columnas mínimas requeridas:\n"
            f"  ➜  {', '.join(faltantes)}\n\n"
            f"Columnas detectadas:\n  {', '.join(map(str, df.columns.tolist()))}"
        )

    col_rut_emp = _buscar_columna(df, ["RUT Emp"])
    col_nombre_emp = _buscar_columna(df, CART56_NOMBRE_EMPRESA_CANDIDATAS)
    col_no_licencia = _buscar_columna(df, CART56_NO_LICENCIA_CANDIDATAS)
    col_mto_pagar = _buscar_columna(df, ["Mto Pagar"])
    col_dias_pagar = _buscar_columna(df, CART56_DIAS_PAGAR_CANDIDATAS)
    col_email = _buscar_columna(df, CART56_EMAIL_CANDIDATAS)
    col_tel_fijo = _buscar_columna(df, CART56_TEL_FIJO_CANDIDATAS)
    col_tel_movil = _buscar_columna(df, CART56_TEL_MOVIL_CANDIDATAS)
    col_fecha_recep = _buscar_columna(df, CART56_FECHA_RECEP_CANDIDATAS)
    col_fecha_recep_isa = _buscar_columna(df, CART56_FECHA_RECEP_ISA_CANDIDATAS)
    col_nombre_afil = _buscar_columna(df, CART56_NOMBRE_AFIL_CANDIDATAS)
    col_rut_afil = _buscar_columna(df, CART56_RUT_AFIL_CANDIDATAS)
    col_fecha_pago = _buscar_columna(df, CART56_FECHA_PAGO_CANDIDATAS)

    detalle_rows: list[dict] = []

    for _, row in df.iterrows():
        rut_txt, dv_txt = _normalizar_rut_dv(row.get(col_rut_emp, ""))
        if not rut_txt:
            continue

        nombre_emp = _valor_limpio(row.get(col_nombre_emp, "")) if col_nombre_emp else ""
        if not nombre_emp:
            nombre_emp = f"Empresa {rut_txt}"

        email_emp = _valor_limpio(row.get(col_email, "")) if col_email else ""
        tel_emp_fijo = _valor_limpio(row.get(col_tel_fijo, "")) if col_tel_fijo else ""
        tel_emp_movil = _valor_limpio(row.get(col_tel_movil, "")) if col_tel_movil else ""

        no_licencia = _valor_limpio(row.get(col_no_licencia, ""))
        dias_pagar = _valor_limpio(row.get(col_dias_pagar, "")) if col_dias_pagar else ""
        monto = _parse_monto(row.get(col_mto_pagar, 0))
        fecha_recep = _normalizar_fecha(row.get(col_fecha_recep, "")) if col_fecha_recep else ""
        fecha_recep_isa = _normalizar_fecha(row.get(col_fecha_recep_isa, "")) if col_fecha_recep_isa else ""
        nombre_afil = _valor_limpio(row.get(col_nombre_afil, "")) if col_nombre_afil else ""
        rut_afil = _valor_limpio(row.get(col_rut_afil, "")) if col_rut_afil else ""
        fecha_pago = _normalizar_fecha(row.get(col_fecha_pago, "")) if col_fecha_pago else ""
        yyyymm_recep = _yyyymm_desde_fecha(row.get(col_fecha_recep, "")) if col_fecha_recep else ""
        yyyymm_recep_isa = _yyyymm_desde_fecha(row.get(col_fecha_recep_isa, "")) if col_fecha_recep_isa else ""
        fecha_emision = fecha_recep_isa or fecha_recep
        periodo_emision = yyyymm_recep_isa or yyyymm_recep

        detalle_rows.append(
            {
                "Rut_Afiliado": rut_txt,
                "Dv": dv_txt,
                "_RUT_COMPLETO": f"{rut_txt}-{dv_txt}" if dv_txt else rut_txt,
                "Nombre_Afiliado": nombre_emp,
                "Nombre Afil": nombre_afil,
                "RUT Afil": rut_afil,
                "Fecha Pago": fecha_pago,
                "Estado_deudor": "Sin Gestión",
                "BN": email_emp,
                "mail_afiliado": email_emp,
                "telefono_fijo_afiliado": tel_emp_fijo,
                "telefono_movil_afiliado": tel_emp_movil,
                "Nro_Expediente": no_licencia,
                "Fecha_Emision": fecha_emision,
                "MAX_Emision_ok": periodo_emision,
                "MIN_Emision_ok": periodo_emision,
                "Copago": _monto_a_texto(monto),
                "Total_Pagos": "0",
                "Saldo_Actual": _monto_a_texto(monto),
                "Cart56_Fecha_Recep": fecha_recep,
                "Cart56_Fecha_Recep_ISA": fecha_recep_isa,
                "Cart56_Dias_Pagar": dias_pagar,
                "Cart56_Mto_Pagar": _monto_a_texto(monto),
                "Mail Emp": email_emp,
                "Telefono Empleador": tel_emp_movil or tel_emp_fijo,
            }
        )

    df_detalle = pd.DataFrame(detalle_rows)
    if df_detalle.empty:
        raise ValueError("No se pudieron construir registros válidos para Cart-56.")

    def _agg_nro_expediente(s: pd.Series) -> str:
        valores = [str(v).strip() for v in s.tolist() if str(v).strip()]
        unicos = list(dict.fromkeys(valores))
        return str(len(unicos)) if unicos else "0"

    def _agg_fecha_min_yyyymm(s: pd.Series) -> str:
        validos = [str(v).strip() for v in s.tolist() if str(v).strip()]
        if not validos:
            return ""
        return min(validos)

    def _agg_fecha_max_yyyymm(s: pd.Series) -> str:
        validos = [str(v).strip() for v in s.tolist() if str(v).strip()]
        if not validos:
            return ""
        return max(validos)

    resumen = (
        df_detalle.groupby(["Rut_Afiliado", "Dv", "Nombre_Afiliado"], dropna=False)
        .agg(
            Estado_deudor=("Estado_deudor", "first"),
            BN=("BN", _primer_no_vacio),
            Nro_Expediente=("Nro_Expediente", _agg_nro_expediente),
            MAX_Emision_ok=("MAX_Emision_ok", _agg_fecha_max_yyyymm),
            MIN_Emision_ok=("MIN_Emision_ok", _agg_fecha_min_yyyymm),
            Copago=("Copago", lambda s: _monto_a_texto(sum(_parse_monto(v) for v in s))),
            Total_Pagos=("Total_Pagos", lambda s: "0"),
            Saldo_Actual=("Saldo_Actual", lambda s: _monto_a_texto(sum(_parse_monto(v) for v in s))),
        )
        .reset_index()
    )

    return resumen.fillna(""), df_detalle.fillna("")


# ================================================================
#  FUNCIÓN PRINCIPAL DE VISTA
# ================================================================

def aplicar_schema(df, empresa: str = ""):
    col_map_norm = {c: c.strip() for c in df.columns}
    df = df.rename(columns=col_map_norm)
    df = df.copy()

    if COLUMNA_RUT in df.columns:
        rut_completo_src = df["_RUT_COMPLETO"] if "_RUT_COMPLETO" in df.columns else ""
        dv_src = df[COLUMNA_DV] if COLUMNA_DV in df.columns else ""

        normalizados = [
            _normalizar_rut_dv_desde_fila(
                row.get(COLUMNA_RUT, ""),
                row.get(COLUMNA_DV, "") if COLUMNA_DV in df.columns else "",
                row.get("_RUT_COMPLETO", "") if "_RUT_COMPLETO" in df.columns else "",
            )
            for _, row in df.iterrows()
        ]

        if normalizados:
            rut_vals, dv_vals, rut_full_vals = zip(*normalizados)
            df[COLUMNA_RUT] = list(rut_vals)
            df[COLUMNA_DV] = list(dv_vals)
            df["_RUT_COMPLETO"] = list(rut_full_vals)

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
            df_vista[col] = df_vista[col].apply(_formatear_moneda_cl)

    for col in COLUMNAS_FECHA_YYYYMM:
        if col in df_vista.columns:
            df_vista[col] = df_vista[col].apply(_formatear_fecha_general)

    if COLUMNA_RUT and COLUMNA_RUT in df.columns:
        rut_base = (
            df[COLUMNA_RUT].astype(str)
            .str.replace(".", "", regex=False)
            .str.replace("-", "", regex=False)
            .str.strip()
            .str.lstrip("0")
        )

        if COLUMNA_DV and COLUMNA_DV in df.columns:
            dv_base = df[COLUMNA_DV].astype(str).str.strip()
            df_vista["_RUT_COMPLETO"] = rut_base + "-" + dv_base
        else:
            df_vista["_RUT_COMPLETO"] = rut_base

        if "Rut_Afiliado" in df_vista.columns:
            df_vista["Rut_Afiliado"] = rut_base

    etiquetas = [ETIQUETAS.get(c, c) for c in columnas]
    return df_vista, columnas, etiquetas
