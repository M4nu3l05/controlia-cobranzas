from __future__ import annotations

from io import BytesIO
import os
import re
import unicodedata
from collections import Counter

import pandas as pd
from sqlalchemy.orm import Session

from app.models.deudor import DeudorDetalle, DeudorResumen

EMPRESAS_VALIDAS = ["Colmena", "Consalud", "Cruz Blanca", "Cart-56"]
HOJA_RESUMEN = "RESUMEN"
HOJA_DETALLE = "DETALLE"

COLUMNAS_RESUMEN_REQUERIDAS = [
    "Rut_Afiliado",
    "Nombre_Afiliado",
]

COLUMNAS_DETALLE_ESPERADAS = [
    "Rut_Afiliado", "Dv", "Nombre_Afiliado", "mail_afiliado", "BN",
    "Nombre Afil", "RUT Afil", "Fecha Pago",
    "telefono_fijo_afiliado", "telefono_movil_afiliado", "Nro_Expediente",
    "Fecha_Emision", "Copago", "Total_Pagos", "Saldo_Actual",
    "Cart56_Fecha_Recep", "Cart56_Fecha_Recep_ISA", "Cart56_Dias_Pagar", "Cart56_Mto_Pagar",
    "_RUT_COMPLETO", "Mail Emp", "Telefono Empleador", "Estado_deudor",
]


def _clean_text(value) -> str:
    txt = str(value or "").strip()
    return "" if txt.lower() in ("", "nan", "none", "nat", "n") else txt


def _norm_rut(value: str) -> str:
    txt = _clean_text(value).replace(".", "")
    if "-" in txt:
        txt = txt.split("-", 1)[0]
    return txt.replace("-", "").lstrip("0")


def _rut_completo(rut: str, dv: str) -> str:
    rut_n = _norm_rut(rut)
    dv_n = _clean_text(dv).upper()
    return f"{rut_n}-{dv_n}" if rut_n and dv_n else rut_n


def _parse_monto(value) -> float:
    txt = _clean_text(value)
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


def _yyyymm_from_date(value) -> str:
    txt = _clean_text(value)
    if not txt:
        return ""
    ts = pd.to_datetime(txt, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y%m")


def _date_to_ddmmyyyy(value) -> str:
    txt = _clean_text(value)
    if not txt:
        return ""
    ts = pd.to_datetime(txt, errors="coerce", dayfirst=True)
    if pd.isna(ts):
        return txt
    return ts.strftime("%d/%m/%Y")


def _first_non_empty(series: pd.Series) -> str:
    for value in series.tolist():
        txt = _clean_text(value)
        if txt:
            return txt
    return ""


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    colmap = {str(c).strip().upper(): str(c) for c in df.columns}
    colmap_norm = {_normalize_column_name(c): str(c) for c in df.columns}
    for cand in candidates:
        found = colmap.get(str(cand).strip().upper())
        if found:
            return found
        found_norm = colmap_norm.get(_normalize_column_name(cand))
        if found_norm:
            return found_norm
    return ""


def _normalize_column_name(name: str) -> str:
    txt = str(name or "").strip().lower()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", txt)


def _coalesce_column(df: pd.DataFrame, target: str, aliases: list[str]) -> None:
    if target in df.columns:
        return
    src = _find_column(df, [target] + aliases)
    if src:
        df[target] = df[src]


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().fillna("")
    out = out.rename(columns={c: str(c).strip() for c in out.columns})
    _coalesce_column(out, "Nombre Afil", ["Nombre Afiliado", "Nom Afil"])
    _coalesce_column(out, "RUT Afil", ["Rut Afil", "RUT Afiliado", "Rut Afiliado"])
    _coalesce_column(out, "Fecha Pago", ["Fecha de Pago", "Fec Pago"])
    if "Rut_Afiliado" in out.columns:
        rut_series = out["Rut_Afiliado"].astype(str)
        dv_series = out["Dv"].astype(str) if "Dv" in out.columns else pd.Series([""] * len(out), index=out.index)
        rut_full_series = out["_RUT_COMPLETO"].astype(str) if "_RUT_COMPLETO" in out.columns else pd.Series([""] * len(out), index=out.index)

        rut_vals: list[str] = []
        dv_vals: list[str] = []
        rut_full_vals: list[str] = []

        for rut_val, dv_val, rut_full_val in zip(rut_series.tolist(), dv_series.tolist(), rut_full_series.tolist()):
            source = _clean_text(rut_full_val) or _clean_text(rut_val)
            source = source.replace(".", "")
            dv_txt = _clean_text(dv_val).upper()

            if "-" in source:
                base, dv_from_source = source.rsplit("-", 1)
                rut_txt = base.strip().replace("-", "").lstrip("0")
                dv_txt = dv_txt or _clean_text(dv_from_source).upper()
            else:
                rut_txt = source.replace("-", "").strip().lstrip("0")

            rut_vals.append(rut_txt)
            dv_vals.append(dv_txt)
            rut_full_vals.append(_rut_completo(rut_txt, dv_txt))

        out["Rut_Afiliado"] = rut_vals
        out["Dv"] = dv_vals
        out["_RUT_COMPLETO"] = rut_full_vals
    return out


def _periodo_from_source_name(source_file: str) -> str:
    source = _clean_text(source_file).lower()
    if not source:
        return ""

    m = re.search(r"(20\d{2})(0[1-9]|1[0-2])", source)
    if m:
        return f"{m.group(1)}{m.group(2)}"

    month_map = {
        "enero": "01",
        "febrero": "02",
        "marzo": "03",
        "abril": "04",
        "mayo": "05",
        "junio": "06",
        "julio": "07",
        "agosto": "08",
        "septiembre": "09",
        "setiembre": "09",
        "octubre": "10",
        "noviembre": "11",
        "diciembre": "12",
    }

    year_match = re.search(r"(20\d{2})", source)
    month_num = ""
    for name, num in month_map.items():
        if name in source:
            month_num = num
            break

    if year_match and month_num:
        return f"{year_match.group(1)}{month_num}"

    return ""


def _periodo_from_source_or_df(source_file: str, df_resumen: pd.DataFrame | None, df_detalle: pd.DataFrame | None) -> str:
    from_name = _periodo_from_source_name(source_file)
    if from_name:
        return from_name

    source = _clean_text(source_file).lower()
    month_map = {
        "enero": "01",
        "febrero": "02",
        "marzo": "03",
        "abril": "04",
        "mayo": "05",
        "junio": "06",
        "julio": "07",
        "agosto": "08",
        "septiembre": "09",
        "setiembre": "09",
        "octubre": "10",
        "noviembre": "11",
        "diciembre": "12",
    }
    month_from_name = ""
    for name, num in month_map.items():
        if name in source:
            month_from_name = num
            break

    year_from_data = ""
    for df in (df_resumen, df_detalle):
        if df is None or df.empty:
            continue
        for col in ("MAX_Emision_ok", "MIN_Emision_ok", "Fecha_Emision", "Cart56_Fecha_Recep_ISA", "Cart56_Fecha_Recep"):
            if col not in df.columns:
                continue
            for value in df[col].astype(str).tolist():
                period = _yyyymm_from_date(value) or _clean_text(value)
                period = re.sub(r"\D", "", period)
                if len(period) >= 6:
                    if not year_from_data:
                        year_from_data = period[:4]
                    return period[:6]

    if year_from_data and month_from_name:
        return f"{year_from_data}{month_from_name}"

    # 🔥 NUEVO: fallback mínimo
    if month_from_name:
        return f"2026{month_from_name}"  # puedes ajustar el año si quieres dinámico

    return ""


def _base_ya_cargada(db: Session, empresa: str, source_file: str) -> bool:
    source_name = os.path.basename(_clean_text(source_file)).strip().lower()
    if not source_name:
        return False

    rows = db.query(DeudorResumen.source_file).filter(DeudorResumen.empresa == empresa).all()
    for (loaded_source,) in rows:
        loaded_name = os.path.basename(_clean_text(loaded_source)).strip().lower()
        if loaded_name and loaded_name == source_name:
            return True

    return False


def _detalle_signature_from_df(df: pd.DataFrame) -> Counter:
    if df is None or df.empty:
        return Counter()

    sigs: list[tuple[str, str, str, str, str]] = []
    for _, row in df.iterrows():
        rut = _norm_rut(row.get("Rut_Afiliado", ""))
        if not rut:
            continue
        expediente = _clean_text(row.get("Nro_Expediente", ""))
        fecha = _clean_text(row.get("Fecha_Emision", ""))
        copago = f"{_parse_monto(row.get('Copago', 0)):.2f}"
        saldo = f"{_parse_monto(row.get('Saldo_Actual', 0)):.2f}"
        sigs.append((rut, expediente, fecha, copago, saldo))
    return Counter(sigs)


def _detalle_signature_from_rows(rows: list[DeudorDetalle]) -> Counter:
    sigs: list[tuple[str, str, str, str, str]] = []
    for row in rows or []:
        rut = _norm_rut(getattr(row, "rut_afiliado", ""))
        if not rut:
            continue
        expediente = _clean_text(getattr(row, "nro_expediente", ""))
        fecha = _clean_text(getattr(row, "fecha_emision", ""))
        copago = f"{float(getattr(row, 'copago', 0) or 0):.2f}"
        saldo = f"{float(getattr(row, 'saldo_actual', 0) or 0):.2f}"
        sigs.append((rut, expediente, fecha, copago, saldo))
    return Counter(sigs)


def _rut_profile_from_df(df: pd.DataFrame) -> dict[str, tuple[int, str, str]]:
    if df is None or df.empty:
        return {}

    out: dict[str, tuple[int, str, str]] = {}
    for rut, g in df.groupby(df["Rut_Afiliado"].astype(str).map(_norm_rut)):
        rut_n = _norm_rut(rut)
        if not rut_n:
            continue
        n = int(len(g))
        copago = f"{sum(_parse_monto(v) for v in g.get('Copago', pd.Series(dtype=str)).tolist()):.2f}"
        saldo = f"{sum(_parse_monto(v) for v in g.get('Saldo_Actual', pd.Series(dtype=str)).tolist()):.2f}"
        out[rut_n] = (n, copago, saldo)
    return out


def _rut_profile_from_rows(rows: list[DeudorDetalle]) -> dict[str, tuple[int, str, str]]:
    tmp: dict[str, list[DeudorDetalle]] = {}
    for row in rows or []:
        rut = _norm_rut(getattr(row, "rut_afiliado", ""))
        if not rut:
            continue
        tmp.setdefault(rut, []).append(row)

    out: dict[str, tuple[int, str, str]] = {}
    for rut, items in tmp.items():
        n = len(items)
        copago = f"{sum(float(getattr(x, 'copago', 0) or 0) for x in items):.2f}"
        saldo = f"{sum(float(getattr(x, 'saldo_actual', 0) or 0) for x in items):.2f}"
        out[rut] = (n, copago, saldo)
    return out


def _detectar_base_duplicada_por_contenido(
    *,
    df_detalle: pd.DataFrame,
    existentes: list[DeudorDetalle],
) -> str:
    if df_detalle is None or df_detalle.empty or not existentes:
        return ""

    sig_in = _detalle_signature_from_df(df_detalle)
    sig_ex = _detalle_signature_from_rows(existentes)

    if sig_in and sig_in == sig_ex:
        return (
            "La base ya fue cargada anteriormente (mismos registros), "
            "aunque el archivo tenga otro nombre."
        )

    perfil_in = _rut_profile_from_df(df_detalle)
    perfil_ex = _rut_profile_from_rows(existentes)
    if perfil_in and perfil_in == perfil_ex:
        return (
            "La base contiene los mismos deudores y montos globales ya cargados. "
            "Solo cambian folios/expedientes u orden de filas."
        )

    return ""


def _tiene_texto(value: object) -> bool:
    return bool(_clean_text(value))


def _modo_enriquecimiento_campos_afil(
    *,
    empresa: str,
    df_detalle: pd.DataFrame,
    existentes_detalle: list[DeudorDetalle],
) -> bool:
    if str(empresa or "").strip() != "Cart-56":
        return False
    if df_detalle is None or df_detalle.empty:
        return False

    incoming_has_data = bool(
        df_detalle.get("Nombre Afil", pd.Series(dtype=str)).astype(str).map(_tiene_texto).any()
        or df_detalle.get("RUT Afil", pd.Series(dtype=str)).astype(str).map(_tiene_texto).any()
        or df_detalle.get("Fecha Pago", pd.Series(dtype=str)).astype(str).map(_tiene_texto).any()
    )
    if not incoming_has_data:
        return False

    for row in existentes_detalle or []:
        if not _clean_text(getattr(row, "nombre_afil", "")):
            return True
        if not _clean_text(getattr(row, "rut_afil", "")):
            return True
        if not _clean_text(getattr(row, "fecha_pago", "")):
            return True
    return False


def _reparar_estado_inconsistente_empresa(db: Session, empresa: str) -> None:
    empresa_txt = _clean_text(empresa)
    if not empresa_txt:
        return

    resumen_count = db.query(DeudorResumen).filter(DeudorResumen.empresa == empresa_txt).count()
    if resumen_count > 0:
        return

    db.query(DeudorDetalle).filter(DeudorDetalle.empresa == empresa_txt).delete(synchronize_session=False)
    db.commit()


def _build_resumen_objects(df: pd.DataFrame, empresa: str, source_file: str, periodo_carga: str) -> list[DeudorResumen]:
    objects = []
    for _, row in df.iterrows():
        rut = _norm_rut(row.get("Rut_Afiliado", ""))
        if not rut:
            continue
        dv = _clean_text(row.get("Dv", ""))
        rut_full = _clean_text(row.get("_RUT_COMPLETO", "")) or _rut_completo(rut, dv)
        objects.append(
            DeudorResumen(
                empresa=empresa,
                rut_afiliado=rut,
                dv=dv,
                rut_completo=rut_full,
                nombre_afiliado=_clean_text(row.get("Nombre_Afiliado", "")),
                estado_deudor=_clean_text(row.get("Estado_deudor", "")) or "Sin Gestión",
                bn=_clean_text(row.get("BN", "")),
                nro_expediente=_clean_text(row.get("Nro_Expediente", "")),
                max_emision_ok=_clean_text(row.get("MAX_Emision_ok", "")),
                min_emision_ok=_clean_text(row.get("MIN_Emision_ok", "")),
                copago=_parse_monto(row.get("Copago", 0)),
                total_pagos=_parse_monto(row.get("Total_Pagos", 0)),
                saldo_actual=_parse_monto(row.get("Saldo_Actual", 0)),
                source_file=source_file,
                periodo_carga=periodo_carga,
            )
        )
    return objects


def _build_detalle_objects(df: pd.DataFrame, empresa: str, source_file: str, periodo_carga: str) -> list[DeudorDetalle]:
    objects = []
    for _, row in df.iterrows():
        rut = _norm_rut(row.get("Rut_Afiliado", ""))
        if not rut:
            continue
        dv = _clean_text(row.get("Dv", ""))
        rut_full = _clean_text(row.get("_RUT_COMPLETO", "")) or _rut_completo(rut, dv)
        objects.append(
            DeudorDetalle(
                empresa=empresa,
                rut_afiliado=rut,
                dv=dv,
                rut_completo=rut_full,
                nombre_afiliado=_clean_text(row.get("Nombre_Afiliado", "")),
                nombre_afil=_clean_text(row.get("Nombre Afil", "")),
                rut_afil=_clean_text(row.get("RUT Afil", "")),
                fecha_pago=_date_to_ddmmyyyy(row.get("Fecha Pago", "")),
                mail_afiliado=_clean_text(row.get("mail_afiliado", "")),
                bn=_clean_text(row.get("BN", "")),
                telefono_fijo_afiliado=_clean_text(row.get("telefono_fijo_afiliado", "")),
                telefono_movil_afiliado=_clean_text(row.get("telefono_movil_afiliado", "")),
                nro_expediente=_clean_text(row.get("Nro_Expediente", "")),
                fecha_emision=_clean_text(row.get("Fecha_Emision", "")),
                copago=_parse_monto(row.get("Copago", 0)),
                total_pagos=_parse_monto(row.get("Total_Pagos", 0)),
                saldo_actual=_parse_monto(row.get("Saldo_Actual", 0)),
                cart56_fecha_recep=_clean_text(row.get("Cart56_Fecha_Recep", "")),
                cart56_fecha_recep_isa=_clean_text(row.get("Cart56_Fecha_Recep_ISA", "")),
                cart56_dias_pagar=_clean_text(row.get("Cart56_Dias_Pagar", "")),
                cart56_mto_pagar=_parse_monto(row.get("Cart56_Mto_Pagar", 0)),
                mail_emp=_clean_text(row.get("Mail Emp", "")),
                telefono_empleador=_clean_text(row.get("Telefono Empleador", "")),
                estado_deudor=_clean_text(row.get("Estado_deudor", "")) or "Sin Gestión",
                source_file=source_file,
                periodo_carga=periodo_carga,
                is_active=True,
            )
        )
    return objects


def _transform_cart56_raw(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_raw is None or df_raw.empty:
        raise ValueError("La base de Cart-56 está vacía.")
    df = _normalize_dataframe(df_raw)

    col_rut_emp = _find_column(df, ["RUT Emp"])
    col_no_licencia = _find_column(df, ["No Licencia", "No. Licencia", "N° Licencia", "Nº Licencia", "Nro Licencia", "Folio LIQ"])
    col_mto_pagar = _find_column(df, ["Mto Pagar"])
    if not col_rut_emp or not col_no_licencia or not col_mto_pagar:
        raise ValueError("La base de Cart-56 no contiene las columnas mínimas requeridas: RUT Emp, No Licencia/Folio LIQ, Mto Pagar.")

    col_nombre_emp = _find_column(df, ["Empresa", "Razon social", "Razon Social", "Razón social", "Razón Social", "Nombre Empresa", "Nombre_Empresa", "Empleador"])
    col_email = _find_column(df, ["mail_afiliado", "Mail Emp", "Email", "Correo", "Correo Empresa", "Mail Empresa"])
    col_tel_fijo = _find_column(df, ["telefono_fijo_afiliado", "Telefono Empleador", "Teléfono Empleador", "Telefono Fijo", "Teléfono Fijo", "Fono"])
    col_tel_movil = _find_column(df, ["telefono_movil_afiliado", "Telefono Empleador", "Teléfono Empleador", "Telefono Movil", "Teléfono Móvil", "Celular", "Movil", "Móvil"])
    col_fecha_recep = _find_column(df, ["Fecha Recep", "Fecha Recep "])
    col_fecha_recep_isa = _find_column(df, ["Fecha Recep ISA"])
    col_dias_pagar = _find_column(df, ["Dias Pagar", "Días Pagar", "Dias de Pagar", "Días de Pagar"])
    col_nombre_afil = _find_column(df, ["Nombre Afil", "Nombre Afiliado", "Nom Afil"])
    col_rut_afil = _find_column(df, ["RUT Afil", "Rut Afil", "RUT Afiliado", "Rut Afiliado"])
    col_fecha_pago = _find_column(df, ["Fecha Pago", "Fecha de Pago", "Fec Pago"])

    detalle_rows = []
    for _, row in df.iterrows():
        rut_txt = _norm_rut(row.get(col_rut_emp, ""))
        if not rut_txt:
            continue
        rut_bruto = _clean_text(row.get(col_rut_emp, "")).replace(".", "")
        dv_txt = ""
        if "-" in rut_bruto:
            _, dv_txt = rut_bruto.rsplit("-", 1)
            dv_txt = dv_txt.strip().upper()

        nombre_emp = _clean_text(row.get(col_nombre_emp, "")) if col_nombre_emp else ""
        if not nombre_emp:
            nombre_emp = f"Empresa {rut_txt}"

        email_emp = _clean_text(row.get(col_email, "")) if col_email else ""
        tel_emp_fijo = _clean_text(row.get(col_tel_fijo, "")) if col_tel_fijo else ""
        tel_emp_movil = _clean_text(row.get(col_tel_movil, "")) if col_tel_movil else ""

        no_licencia = _clean_text(row.get(col_no_licencia, ""))
        dias_pagar = _clean_text(row.get(col_dias_pagar, "")) if col_dias_pagar else ""
        monto = _parse_monto(row.get(col_mto_pagar, 0))
        fecha_recep = _date_to_ddmmyyyy(row.get(col_fecha_recep, "")) if col_fecha_recep else ""
        fecha_recep_isa = _date_to_ddmmyyyy(row.get(col_fecha_recep_isa, "")) if col_fecha_recep_isa else ""
        nombre_afil = _clean_text(row.get(col_nombre_afil, "")) if col_nombre_afil else ""
        rut_afil = _clean_text(row.get(col_rut_afil, "")) if col_rut_afil else ""
        fecha_pago = _date_to_ddmmyyyy(row.get(col_fecha_pago, "")) if col_fecha_pago else ""
        periodo_emision = _yyyymm_from_date(row.get(col_fecha_recep_isa, "")) or _yyyymm_from_date(row.get(col_fecha_recep, ""))
        fecha_emision = fecha_recep_isa or fecha_recep

        detalle_rows.append({
            "Rut_Afiliado": rut_txt,
            "Dv": dv_txt,
            "_RUT_COMPLETO": _rut_completo(rut_txt, dv_txt),
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
            "Copago": str(int(round(monto))),
            "Total_Pagos": "0",
            "Saldo_Actual": str(int(round(monto))),
            "Cart56_Fecha_Recep": fecha_recep,
            "Cart56_Fecha_Recep_ISA": fecha_recep_isa,
            "Cart56_Dias_Pagar": dias_pagar,
            "Cart56_Mto_Pagar": str(int(round(monto))),
            "Mail Emp": email_emp,
            "Telefono Empleador": tel_emp_movil or tel_emp_fijo,
        })

    df_detalle = pd.DataFrame(detalle_rows).fillna("")
    if df_detalle.empty:
        raise ValueError("No se pudieron construir registros válidos para Cart-56.")

    resumen = (
        df_detalle.groupby(["Rut_Afiliado", "Dv", "Nombre_Afiliado"], dropna=False)
        .agg(
            Estado_deudor=("Estado_deudor", "first"),
            BN=("BN", _first_non_empty),
            Nro_Expediente=("Nro_Expediente", lambda s: str(len({str(v).strip() for v in s.tolist() if str(v).strip()}))),
            MAX_Emision_ok=("MAX_Emision_ok", lambda s: max([str(v).strip() for v in s.tolist() if str(v).strip()] or [""])),
            MIN_Emision_ok=("MIN_Emision_ok", lambda s: min([str(v).strip() for v in s.tolist() if str(v).strip()] or [""])),
            Copago=("Copago", lambda s: str(int(round(sum(_parse_monto(v) for v in s))))),
            Total_Pagos=("Total_Pagos", lambda s: str(int(round(sum(_parse_monto(v) for v in s))))),
            Saldo_Actual=("Saldo_Actual", lambda s: str(int(round(sum(_parse_monto(v) for v in s))))),
        )
        .reset_index()
        .fillna("")
    )
    return resumen, df_detalle


def _read_general_excel(content: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    xls = pd.ExcelFile(BytesIO(content))
    if HOJA_RESUMEN not in xls.sheet_names:
        raise ValueError(f"No se encontró la hoja '{HOJA_RESUMEN}' en el archivo Excel.")

    df_resumen = _normalize_dataframe(pd.read_excel(BytesIO(content), sheet_name=HOJA_RESUMEN, dtype=str))
    faltantes = [c for c in COLUMNAS_RESUMEN_REQUERIDAS if c not in df_resumen.columns]
    if faltantes:
        raise ValueError("Faltan columnas obligatorias en RESUMEN: " + ", ".join(faltantes))

    if HOJA_DETALLE in xls.sheet_names:
        df_detalle = _normalize_dataframe(pd.read_excel(BytesIO(content), sheet_name=HOJA_DETALLE, dtype=str))
    else:
        df_detalle = pd.DataFrame(columns=COLUMNAS_DETALLE_ESPERADAS)

    return df_resumen.fillna(""), df_detalle.fillna("")


def _detalle_identity_key(row: DeudorDetalle) -> tuple[str, str, str, str, str]:
    empresa = _clean_text(row.empresa)
    rut = _norm_rut(row.rut_afiliado)
    expediente = _clean_text(row.nro_expediente)
    fecha = _clean_text(row.fecha_emision)
    monto_cart56 = ""
    if empresa == "Cart-56":
        raw_monto = float(getattr(row, "cart56_mto_pagar", 0) or 0)
        if raw_monto <= 0:
            raw_monto = float(getattr(row, "copago", 0) or 0)
        monto_cart56 = f"{raw_monto:.2f}"
    return (empresa, rut, expediente, fecha, monto_cart56)


def _rebuild_resumen_from_detalle(db: Session, *, empresa: str) -> int:
    detalle_rows = (
        db.query(DeudorDetalle)
        .filter(
            DeudorDetalle.empresa == empresa,
            DeudorDetalle.is_active.is_(True),
        )
        .all()
    )

    estado_existente = {
        _norm_rut(row.rut_afiliado): _clean_text(row.estado_deudor) or "Sin Gestión"
        for row in db.query(DeudorResumen).filter(DeudorResumen.empresa == empresa).all()
    }

    grupos = {}
    for row in detalle_rows:
        rut = _norm_rut(row.rut_afiliado)
        if not rut:
            continue

        g = grupos.setdefault(
            rut,
            {
                "empresa": empresa,
                "rut_afiliado": rut,
                "dv": _clean_text(row.dv),
                "rut_completo": _clean_text(row.rut_completo) or _rut_completo(rut, row.dv),
                "nombre_afiliado": _clean_text(row.nombre_afiliado),
                "bn": "",
                "expedientes": set(),
                "max_emision_ok": [],
                "min_emision_ok": [],
                "copago": 0.0,
                "total_pagos": 0.0,
                "saldo_actual": 0.0,
                "estado_deudor": estado_existente.get(rut, _clean_text(row.estado_deudor) or "Sin Gestión"),
                "source_file": "",
                "periodo_carga": "",
            },
        )

        if not g["bn"]:
            g["bn"] = _clean_text(row.bn)
        if not g["nombre_afiliado"]:
            g["nombre_afiliado"] = _clean_text(row.nombre_afiliado)
        if not g["dv"]:
            g["dv"] = _clean_text(row.dv)
        if not g["rut_completo"]:
            g["rut_completo"] = _clean_text(row.rut_completo)

        expediente = _clean_text(row.nro_expediente)
        if expediente:
            g["expedientes"].add(expediente)

        periodo = _yyyymm_from_date(row.fecha_emision) or _clean_text(getattr(row, "periodo_carga", ""))
        if periodo:
            g["max_emision_ok"].append(periodo)
            g["min_emision_ok"].append(periodo)

        if not g["source_file"] and _clean_text(getattr(row, "source_file", "")):
            g["source_file"] = _clean_text(getattr(row, "source_file", ""))

        row_periodo = _clean_text(getattr(row, "periodo_carga", ""))
        if row_periodo and row_periodo >= _clean_text(g["periodo_carga"]):
            g["periodo_carga"] = row_periodo

        g["copago"] += float(row.copago or 0)
        g["total_pagos"] += float(row.total_pagos or 0)
        g["saldo_actual"] += float(row.saldo_actual or 0)

    db.query(DeudorResumen).filter(DeudorResumen.empresa == empresa).delete(synchronize_session=False)

    resumen_objs = []
    for rut, g in grupos.items():
        resumen_objs.append(
            DeudorResumen(
                empresa=empresa,
                rut_afiliado=rut,
                dv=g["dv"],
                rut_completo=g["rut_completo"] or _rut_completo(rut, g["dv"]),
                nombre_afiliado=g["nombre_afiliado"],
                estado_deudor=g["estado_deudor"] or "Sin Gestión",
                bn=g["bn"],
                nro_expediente=str(len(g["expedientes"])) if g["expedientes"] else "",
                max_emision_ok=max(g["max_emision_ok"]) if g["max_emision_ok"] else "",
                min_emision_ok=min(g["min_emision_ok"]) if g["min_emision_ok"] else "",
                copago=float(g["copago"]),
                total_pagos=float(g["total_pagos"]),
                saldo_actual=float(g["saldo_actual"]),
                source_file=g["source_file"],
                periodo_carga=g["periodo_carga"],
            )
        )

    if resumen_objs:
        db.bulk_save_objects(resumen_objs)

    return len(resumen_objs)


def import_deudores_excel_service(
    db: Session,
    *,
    empresa: str,
    content: bytes,
    source_file: str,
) -> dict:
    empresa_txt = str(empresa or "").strip()
    if empresa_txt not in EMPRESAS_VALIDAS:
        raise ValueError(f"Empresa no válida. Opciones: {', '.join(EMPRESAS_VALIDAS)}")
    if not content:
        raise ValueError("El archivo recibido está vacío.")

    _reparar_estado_inconsistente_empresa(db, empresa_txt)

    if empresa_txt == "Cart-56":
        xls = pd.ExcelFile(BytesIO(content))
        hoja = xls.sheet_names[0] if xls.sheet_names else 0
        df_raw = _normalize_dataframe(pd.read_excel(BytesIO(content), sheet_name=hoja, dtype=str))
        df_resumen, df_detalle = _transform_cart56_raw(df_raw)
    else:
        df_resumen, df_detalle = _read_general_excel(content)

    existentes_detalle = (
        db.query(DeudorDetalle)
        .filter(DeudorDetalle.empresa == empresa_txt, DeudorDetalle.is_active.is_(True))
        .all()
    )
    modo_enriquecimiento = _modo_enriquecimiento_campos_afil(
        empresa=empresa_txt,
        df_detalle=df_detalle,
        existentes_detalle=existentes_detalle,
    )

    if _base_ya_cargada(db, empresa_txt, source_file) and not modo_enriquecimiento and empresa_txt != "Cart-56":
        raise ValueError(
            f"La base '{os.path.basename(_clean_text(source_file))}' ya fue cargada anteriormente para {empresa_txt}. "
            "No se puede importar dos veces la misma base de deudores."
        )

    motivo_duplicada = _detectar_base_duplicada_por_contenido(
        df_detalle=df_detalle,
        existentes=existentes_detalle,
    )
    if motivo_duplicada and not modo_enriquecimiento and empresa_txt != "Cart-56":
        raise ValueError(
            f"{motivo_duplicada} No se puede importar dos veces la misma base de deudores."
        )

    periodo_carga = _periodo_from_source_or_df(source_file, df_resumen, df_detalle)
    resumen_objs = _build_resumen_objects(df_resumen, empresa_txt, source_file, periodo_carga)
    detalle_objs = _build_detalle_objects(df_detalle, empresa_txt, source_file, periodo_carga)

    existentes = db.query(DeudorDetalle).filter(DeudorDetalle.empresa == empresa_txt).all()
    existentes_map = {_detalle_identity_key(row): row for row in existentes}

    insertados = 0
    actualizados = 0
    omitidos = 0
    keys_procesadas: set[tuple[str, str, str, str, str]] = set()

    for nuevo in detalle_objs:
        key = _detalle_identity_key(nuevo)
        if key in keys_procesadas:
            omitidos += 1
            continue
        keys_procesadas.add(key)

        existente = existentes_map.get(key)

        if existente is None:
            db.add(nuevo)
            existentes_map[key] = nuevo
            insertados += 1
            continue

        if not modo_enriquecimiento:
            omitidos += 1
            continue

        existente.dv = nuevo.dv or existente.dv
        existente.rut_completo = nuevo.rut_completo or existente.rut_completo
        existente.nombre_afiliado = nuevo.nombre_afiliado or existente.nombre_afiliado
        existente.nombre_afil = nuevo.nombre_afil or existente.nombre_afil
        existente.rut_afil = nuevo.rut_afil or existente.rut_afil
        existente.fecha_pago = nuevo.fecha_pago or existente.fecha_pago
        existente.mail_afiliado = nuevo.mail_afiliado or existente.mail_afiliado
        existente.bn = nuevo.bn or existente.bn
        existente.telefono_fijo_afiliado = nuevo.telefono_fijo_afiliado or existente.telefono_fijo_afiliado
        existente.telefono_movil_afiliado = nuevo.telefono_movil_afiliado or existente.telefono_movil_afiliado
        existente.fecha_emision = nuevo.fecha_emision or existente.fecha_emision
        existente.cart56_fecha_recep = nuevo.cart56_fecha_recep or existente.cart56_fecha_recep
        existente.cart56_fecha_recep_isa = nuevo.cart56_fecha_recep_isa or existente.cart56_fecha_recep_isa
        existente.cart56_dias_pagar = nuevo.cart56_dias_pagar or existente.cart56_dias_pagar
        existente.cart56_mto_pagar = float(nuevo.cart56_mto_pagar or existente.cart56_mto_pagar or 0)
        existente.mail_emp = nuevo.mail_emp or existente.mail_emp
        existente.telefono_empleador = nuevo.telefono_empleador or existente.telefono_empleador
        existente.source_file = source_file or existente.source_file
        existente.periodo_carga = periodo_carga or existente.periodo_carga
        existente.is_active = True

        tenia_movimiento = float(existente.total_pagos or 0) != 0 or float(existente.saldo_actual or 0) != float(existente.copago or 0)
        if not tenia_movimiento:
            existente.copago = float(nuevo.copago or 0)
            existente.total_pagos = float(nuevo.total_pagos or 0)
            existente.saldo_actual = float(nuevo.saldo_actual or 0)

        if (_clean_text(existente.estado_deudor) or "Sin Gestión") == "Sin Gestión":
            existente.estado_deudor = nuevo.estado_deudor or "Sin Gestión"

        actualizados += 1

    resumen_insertados = _rebuild_resumen_from_detalle(db, empresa=empresa_txt)
    if resumen_insertados == 0 and resumen_objs:
        db.query(DeudorResumen).filter(DeudorResumen.empresa == empresa_txt).delete(synchronize_session=False)
        db.bulk_save_objects(resumen_objs)
        resumen_insertados = len(resumen_objs)
    db.commit()

    return {
        "empresa": empresa_txt,
        "resumen_insertados": int(resumen_insertados),
        "detalle_insertados": int(insertados + actualizados),
        "detalle_nuevos": int(insertados),
        "detalle_actualizados": int(actualizados),
        "detalle_omitidos": int(omitidos),
        "source_file": source_file,
        "periodo_carga": periodo_carga,
    }
