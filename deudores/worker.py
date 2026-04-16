# ================================================================
#  deudores/worker.py
#  Carga RESUMEN + DETALLE, guarda en SQLite por empresa.
#  Ahora integra cargas acumulativas (upsert/merge) por empresa.
# ================================================================

from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from .database import guardar_contactos, guardar_detalle, guardar_registros
from .schema import (
    COLUMNAS_OBLIGATORIAS,
    HOJA_EXCEL,
    aplicar_schema,
    transformar_cart56_raw,
)
from .schema_detalle import HOJA_DETALLE


def _friendly_excel_load_error(exc: Exception, excel_path: str) -> str:
    msg = str(exc or "").strip()
    lower = msg.lower()

    if isinstance(exc, FileNotFoundError):
        return f"No se encontró el archivo Excel seleccionado.\n\nArchivo:\n{excel_path}"
    if isinstance(exc, PermissionError):
        return (
            "No se pudo abrir el archivo Excel porque está bloqueado o está abierto en otro programa.\n\n"
            "Cierra el archivo en Excel e intenta nuevamente."
        )
    if "worksheet" in lower or "sheet" in lower or "hoja" in lower:
        return "El archivo Excel no contiene la hoja esperada para esta carga.\n\nDetalle:\n" + msg
    if "columnas m" in lower or "required" in lower or "columns" in lower:
        return msg
    if "excel file format cannot be determined" in lower or "file is not a zip file" in lower:
        return "El archivo seleccionado no parece ser un Excel válido. Verifica que sea un archivo .xlsx o .xls correcto."

    return (
        "No se pudo procesar la base de deudores.\n\n"
        f"Archivo:\n{excel_path}\n\n"
        f"Detalle:\n{msg or type(exc).__name__}"
    )


@dataclass
class CargaDeudoresParams:
    excel_path: str
    empresa: str          # "Colmena" | "Consalud" | "Cruz Blanca" | "Cart-56"
    sheet_name: str = ""  # vacío = usa HOJA_EXCEL de schema.py


class CargaDeudoresWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object, list, list, object)   # df_vista, cols, etqs, df_detalle
    failed = pyqtSignal(str)

    def __init__(self, params: CargaDeudoresParams, parent=None):
        super().__init__(parent)
        self.params = params

    def _run_cart56(self):
        p = self.params
        source_file = os.path.abspath(p.excel_path)

        self.progress.emit(10, "Leyendo base cruda de Cart-56…")
        xls = pd.ExcelFile(p.excel_path)
        hoja_raw = p.sheet_name or (xls.sheet_names[0] if xls.sheet_names else 0)

        df_raw = pd.read_excel(p.excel_path, sheet_name=hoja_raw, dtype=str).fillna("")
        self.progress.emit(28, f"Cart-56: {len(df_raw):,} filas × {len(df_raw.columns)} columnas detectadas")

        self.progress.emit(45, "Transformando Cart-56 al esquema estándar del CRM…")
        df_resumen, df_detalle = transformar_cart56_raw(df_raw)

        self.progress.emit(60, "Integrando resumen en base acumulativa…")
        n_resumen = guardar_registros(df_resumen, p.empresa, source_file=source_file)

        self.progress.emit(72, "Preparando vista principal…")
        df_vista, columnas, etiquetas = aplicar_schema(df_resumen, p.empresa)

        self.progress.emit(84, "Integrando contactos y detalle en base acumulativa…")
        n_contactos = guardar_contactos(df_detalle, p.empresa, source_file=source_file)
        n_detalle = guardar_detalle(df_detalle, p.empresa, source_file=source_file)

        self.progress.emit(
            100,
            f"¡Listo! Base integrada. "
            f"Resumen procesado: {n_resumen:,} | "
            f"Contactos: {n_contactos:,} | "
            f"Detalle: {n_detalle:,}"
        )
        self.finished_ok.emit(df_vista, columnas, etiquetas, df_detalle)

    def _run_general(self):
        p = self.params
        source_file = os.path.abspath(p.excel_path)
        hoja_resumen = p.sheet_name or HOJA_EXCEL

        self.progress.emit(10, "Leyendo hoja RESUMEN…")
        kwargs = {"sheet_name": hoja_resumen} if hoja_resumen else {}
        df = pd.read_excel(p.excel_path, dtype=str, **kwargs).fillna("")
        self.progress.emit(30, f"RESUMEN: {len(df):,} filas × {len(df.columns)} columnas")

        cols_upper = {c.strip().upper(): c for c in df.columns}
        faltantes = [c for c in COLUMNAS_OBLIGATORIAS if c.strip().upper() not in cols_upper]
        if faltantes:
            self.failed.emit(
                f"Columnas mínimas requeridas no encontradas:\n  ➜  {', '.join(faltantes)}\n\n"
                f"Columnas en el archivo:\n  {', '.join(df.columns.tolist())}"
            )
            return

        self.progress.emit(45, f"Integrando resumen en base acumulativa ({p.empresa})…")
        n_resumen = guardar_registros(df, p.empresa, source_file=source_file)
        self.progress.emit(60, f"Resumen procesado: {n_resumen:,} registros.")

        self.progress.emit(70, "Preparando vista…")
        df_vista, columnas, etiquetas = aplicar_schema(df, p.empresa)

        self.progress.emit(80, "Leyendo hoja DETALLE…")
        try:
            df_detalle = pd.read_excel(p.excel_path, sheet_name=HOJA_DETALLE, dtype=str).fillna("")
            self.progress.emit(88, f"DETALLE: {len(df_detalle):,} filas. Integrando…")
            n_contactos = guardar_contactos(df_detalle, p.empresa, source_file=source_file)
            n_detalle = guardar_detalle(df_detalle, p.empresa, source_file=source_file)
            self.progress.emit(
                95,
                f"Base integrada. Contactos procesados: {n_contactos:,} | Detalle procesado: {n_detalle:,}"
            )
        except Exception:
            df_detalle = pd.DataFrame()
            self.progress.emit(95, "Hoja DETALLE no encontrada — solo se integró RESUMEN.")

        self.progress.emit(100, "¡Listo! Base integrada correctamente.")
        self.finished_ok.emit(df_vista, columnas, etiquetas, df_detalle)

    def run(self):
        try:
            if str(self.params.empresa).strip().lower() == "cart-56":
                self._run_cart56()
            else:
                self._run_general()

        except Exception as e:
            self.failed.emit(_friendly_excel_load_error(e, self.params.excel_path))
