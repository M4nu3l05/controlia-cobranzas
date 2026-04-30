"""
Lógica de comparación de archivos Excel
"""

import os
from typing import Dict, Any, Tuple, Callable, Optional

import pandas as pd
from core.excel_export import write_excel_report


def build_id(df: pd.DataFrame, col_a: str | list[str] | tuple[str, ...], col_b: str | None = None) -> pd.Series:
    """
    Genera una columna ID concatenando dos columnas del DataFrame.
    """
    if col_b is None and isinstance(col_a, (list, tuple)):
        if len(col_a) != 2:
            raise ValueError("build_id requiere exactamente dos columnas.")
        col_a, col_b = col_a
    if col_b is None:
        raise ValueError("build_id requiere exactamente dos columnas.")
    return df[col_a].str.strip() + "_" + df[col_b].str.strip()


def _pick_excel_writer_engine() -> str:
    """
    Intenta usar xlsxwriter (más rápido) y si no está, cae a openpyxl.
    """
    try:
        import xlsxwriter  # noqa: F401
        return "xlsxwriter"
    except Exception:
        return "openpyxl"


def compare_excels(
    file1: str,
    file2: str,
    output: str,
    sheet: str = "DETALLE",
    progress_cb: Optional[Callable[[int, str], None]] = None,
    export_both: bool = False
) -> Tuple[str, Dict[str, Any]]:
    """
    Genera el reporte Excel y devuelve:
      - output path
      - dict de métricas para previsualización
    """

    if progress_cb:
        progress_cb(3, "Validando rutas...")

    if not os.path.exists(file1):
        raise FileNotFoundError(f"No se encontró el archivo Mes Anterior:\n{file1}")
    if not os.path.exists(file2):
        raise FileNotFoundError(f"No se encontró el archivo Mes Actual:\n{file2}")

    if progress_cb:
        progress_cb(8, "Leyendo Mes Anterior (Excel)...")

    # Lectura rápida
    df1 = pd.read_excel(
        file1,
        sheet_name=sheet,
        engine="openpyxl",
        dtype=str,
        keep_default_na=False
    )

    if progress_cb:
        progress_cb(18, "Leyendo Mes Actual (Excel)...")

    df2 = pd.read_excel(
        file2,
        sheet_name=sheet,
        engine="openpyxl",
        dtype=str,
        keep_default_na=False
    )

    if df1.empty:
        raise ValueError(f"La hoja '{sheet}' del Mes Anterior está vacía.")
    if df2.empty:
        raise ValueError(f"La hoja '{sheet}' del Mes Actual está vacía.")

    if df1.shape[1] < 2 or df2.shape[1] < 2:
        raise ValueError("Los archivos deben tener al menos 2 columnas (A y B) para crear el ID.")

    col_a_1, col_b_1 = df1.columns[0], df1.columns[1]
    col_a_2, col_b_2 = df2.columns[0], df2.columns[1]

    if progress_cb:
        progress_cb(30, "Generando ID (Col A + Col B)...")

    id_col = "ID_A_B"
    df1 = df1.copy()
    df2 = df2.copy()
    df1[id_col] = build_id(df1, col_a_1, col_b_1)
    df2[id_col] = build_id(df2, col_a_2, col_b_2)

    if progress_cb:
        progress_cb(45, "Comparando IDs (altas/bajas/en ambos)...")

    set1 = set(df1[id_col].tolist())
    set2 = set(df2[id_col].tolist())

    only1 = set1 - set2
    only2 = set2 - set1
    both = set1 & set2

    only1_df = df1[df1[id_col].isin(only1)].copy()
    only2_df = df2[df2[id_col].isin(only2)].copy()

    dup1 = df1[df1[id_col].duplicated(keep=False)].sort_values(id_col)
    dup2 = df2[df2[id_col].duplicated(keep=False)].sort_values(id_col)

    # (Opcional) exportar "En ambos"
    both1_df = df1[df1[id_col].isin(both)].copy() if export_both else None
    both2_df = df2[df2[id_col].isin(both)].copy() if export_both else None

    metrics = {
        "Filas Mes Anterior (DETALLE)": int(len(df1)),
        "Filas Mes Actual (DETALLE)": int(len(df2)),
        "IDs únicos Mes Anterior": int(df1[id_col].nunique()),
        "IDs únicos Mes Actual": int(df2[id_col].nunique()),
        "IDs solo en Mes Actual (altas)": int(len(only2)),
        "IDs solo en Mes Anterior (bajas)": int(len(only1)),
        "IDs en ambos": int(len(both)),
        "Filas con ID duplicado Mes Anterior": int(len(dup1)),
        "Filas con ID duplicado Mes Actual": int(len(dup2)),
        "Exportó pestañas 'En ambos'": "SI" if export_both else "NO",
    }

    summary = pd.DataFrame({"Metrica": list(metrics.keys()), "Valor": list(metrics.values())})

    if progress_cb:
        progress_cb(70, "Escribiendo reporte Excel...")

    out_dir = os.path.dirname(output) or "."
    os.makedirs(out_dir, exist_ok=True)

    if progress_cb:
        progress_cb(72, "Exportando reporte final...")

    sheets = {
        "RESUMEN": summary,
        "Solo_en_Anterior": only1_df,
        "Solo_en_Actual": only2_df,
        "Duplicados_Anterior": dup1,
        "Duplicados_Actual": dup2,
    }

    if export_both:
        sheets["En_ambos_Anterior"] = both1_df
        sheets["En_ambos_Actual"] = both2_df

    write_excel_report(output, sheets)

    if progress_cb:
        progress_cb(100, "Listo ✅ Reporte generado.")

    return output, metrics
