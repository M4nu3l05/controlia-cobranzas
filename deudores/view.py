from __future__ import annotations

import os
import sqlite3
import datetime
import re
import unicodedata
from time import sleep

import pandas as pd
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget, QLabel, QComboBox, QTableWidgetItem

from core.excel_export import write_excel_report
from core.paths import get_data_dir
from deudores.database import (
    EMPRESAS,
    base_deudores_ya_cargada,
    cargar_detalle_empresa,
    cargar_detalle_empresas,
    cargar_detalle_todas,
    cargar_empresas,
    cargar_todas,
    guardar_detalle,
    hay_datos,
    hay_datos_empresas,
)
from admin_carteras.service import obtener_empresas_asignadas_para_session, session_tiene_restriccion_por_cartera
from auth.auth_service import (
    backend_create_gestion,
    backend_get_deudor_detalle,
    backend_import_deudores,
    backend_list_all_gestiones,
    backend_list_deudores,
    backend_list_mis_gestiones_asignadas,
    backend_marcar_gestion_asignada_realizada,
)
from .detalle_dialog import DetalleDeudorDialog
from .gestiones_db import (
    ESTADO_DEUDOR_DEFAULT,
    TABLA,
    leer_gestiones_excel,
    obtener_estados_deudor_por_rut,
    insertar_gestion_manual,
)
from .gestiones_worker import CargaGestionesParams, CargaGestionesWorker
from .panels import build_splitter_layout
from .schema import COLUMNA_EMPRESA, COLUMNA_RUT, ETIQUETAS, transformar_cart56_raw
from .ui_components import DeudoresTableModel, EmpresaFilterProxy
from .worker import CargaDeudoresParams, CargaDeudoresWorker


class DeudoresWidget(QWidget):
    datos_actualizados = pyqtSignal()

    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        self._df: pd.DataFrame | None = None
        self._df_detalle: pd.DataFrame | None = None
        self._worker: CargaDeudoresWorker | None = None
        self._gest_worker: CargaGestionesWorker | None = None
        self._columnas: list[str] = []
        self._etiquetas: list[str] = []
        self._sort_column: str | None = None
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
        self._session = session
        self._empresas_asignadas: list[str] = []
        self._tareas_asignadas: list[dict] = []
        self._cart56_detalle_cache_df: pd.DataFrame | None = None

        _, self.lbl_total, self._splitter, self.sidebar, self.table_panel = build_splitter_layout(self, session=session)
        self.table = self.table_panel.table
        self.lbl_placeholder = self.table_panel.lbl_placeholder

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filter)

        self._connect_ui()
        self._ensure_period_filter_ui()
        self._toggle_descarga_gestiones_fields()
        self._aplicar_permisos_por_rol()
        self._refrescar_panel_tareas_asignadas()

        QTimer.singleShot(0, self._ajustar_splitter_inicial)
        QTimer.singleShot(120, self._ajustar_splitter_inicial)
        QTimer.singleShot(200, self._cargar_inicial)

    def _usa_backend_deudores(self) -> bool:
        return bool(self._session and getattr(self._session, "auth_source", "") == "backend")

    def _puede_cargar_bases(self) -> bool:
        if self._session is None:
            return True
        return bool(getattr(self._session, "role", "") in ("admin", "supervisor"))

    def _aplicar_permisos_por_rol(self) -> None:
        puede_cargar = self._puede_cargar_bases()
        s = self.sidebar

        if hasattr(s, "btn_pick"):
            s.btn_pick.setEnabled(puede_cargar)
            s.btn_pick.setVisible(puede_cargar)
        if hasattr(s, "btn_cargar"):
            s.btn_cargar.setEnabled(puede_cargar)
            s.btn_cargar.setVisible(puede_cargar)
            if not puede_cargar:
                s.btn_cargar.setToolTip("Solo administradores y supervisores pueden cargar bases.")
        if hasattr(s, "txt_excel"):
            s.txt_excel.setEnabled(puede_cargar)
            if not puede_cargar:
                s.txt_excel.clear()
                s.txt_excel.setPlaceholderText("Solo administradores y supervisores pueden cargar bases.")
        if hasattr(s, "cmb_empresa"):
            s.cmb_empresa.setEnabled(puede_cargar)

    def _ensure_period_filter_ui(self) -> None:
        s = self.sidebar
        if hasattr(s, "cmb_periodo"):
            return False

        s.lbl_periodo = QLabel("Periodo:")
        s.cmb_periodo = QComboBox()
        s.cmb_periodo.addItem("Acumulado")
        s.cmb_periodo.setEnabled(False)
        s.cmb_periodo.currentIndexChanged.connect(self._on_search_changed)

        lay = s.layout()
        if lay is not None:
            try:
                idx_insert = max(lay.count() - 1, 0)
                lay.insertWidget(idx_insert, s.lbl_periodo)
                lay.insertWidget(idx_insert + 1, s.cmb_periodo)
            except Exception:
                lay.addWidget(s.lbl_periodo)
                lay.addWidget(s.cmb_periodo)

    def _periodo_actual(self) -> str:
        s = self.sidebar
        if hasattr(s, "cmb_periodo"):
            return s.cmb_periodo.currentText().strip()
        return "Acumulado"

    def _filtrar_por_periodo(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df

        periodo = self._periodo_actual()
        if not periodo or periodo == "Acumulado":
            return df

        if "_periodo_carga" not in df.columns:
            return df

        return df[df["_periodo_carga"].astype(str).str.strip() == periodo].copy()

    def _empresas_asignadas_actuales(self) -> list[str]:
        empresas = obtener_empresas_asignadas_para_session(self._session)
        self._empresas_asignadas = list(empresas)
        return self._empresas_asignadas

    def _cargar_inicial(self):
        if self._usa_backend_deudores():
            self._cargar_desde_backend()
        else:
            self._cargar_desde_db()

    def refrescar_datos(self) -> None:
        texto = self.sidebar.txt_search.text()
        empresa = self.sidebar.cmb_filtro_empresa.currentText()
        col_idx = self.sidebar.cmb_col.currentIndex()
        periodo = self._periodo_actual()

        if self._usa_backend_deudores():
            self._cargar_desde_backend()
        else:
            self._cargar_desde_db()

        self._restaurar_filtros_ui(
            texto=texto,
            empresa=empresa,
            col_idx=col_idx,
            periodo=periodo,
        )


    def _tiene_restriccion_por_cartera(self) -> bool:
        return session_tiene_restriccion_por_cartera(self._session)

    def _sin_carteras_asignadas(self) -> bool:
        # Ejecutivos pueden ver todas las bases; la restriccin aplica solo a acciones.
        return False

    def _es_ejecutivo(self) -> bool:
        role = str(getattr(self._session, "role", "")).strip().lower()
        return role.startswith("ejecut")

    def _texto_normalizado(self, value: str) -> str:
        txt = str(value or "").strip().lower()
        txt = "".join(ch for ch in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(ch))
        return " ".join(txt.split())

    def _es_gestion_asignada(self, estado: str) -> bool:
        return self._texto_normalizado(estado) in {"gestion asignada", "gestin asignada"}

    def _es_gestion_realizada(self, estado: str) -> bool:
        return self._texto_normalizado(estado) in {"gestion realizada", "gestin realizada"}

    def _gestion_es_para_sesion_actual(self, observacion: str) -> bool:
        obs = self._texto_normalizado(observacion)
        email = self._texto_normalizado(getattr(self._session, "email", ""))
        username = self._texto_normalizado(getattr(self._session, "username", ""))
        return (email and email in obs) or (username and username in obs)

    def _row_get(self, row: dict, *keys: str, default: str = "") -> str:
        for key in keys:
            if key in row and str(row.get(key, "")).strip():
                return str(row.get(key, "")).strip()
        return default

    def _ref_ids_gestiones_realizadas(self, rows: list[dict]) -> set[int]:
        ref_ids: set[int] = set()
        for row in rows or []:
            estado = self._row_get(row, "estado", "Estado")
            if not self._es_gestion_realizada(estado):
                continue
            obs = self._row_get(row, "observacion", "Observacion")
            for match in re.findall(r"Ref#\s*(\d+)", obs, flags=re.IGNORECASE):
                try:
                    ref_ids.add(int(match))
                except Exception:
                    pass
        return ref_ids

    def _listar_tareas_asignadas_backend(self) -> tuple[list[dict], str]:
        rows, err = backend_list_mis_gestiones_asignadas(self._session)
        if err:
            return [], err
        tareas: list[dict] = []
        for row in rows or []:
            estado = self._row_get(row, "estado", "Estado")
            if not self._es_gestion_asignada(estado):
                continue
            empresa = self._row_get(row, "empresa", "Empresa")
            observacion = self._row_get(row, "observacion", "Observacion")
            try:
                gid = int(self._row_get(row, "id", default="0") or 0)
            except Exception:
                gid = 0
            tareas.append(
                {
                    "id": gid,
                    "rut": self._row_get(row, "rut_afiliado", "Rut_Afiliado", "rut", "Rut"),
                    "nombre": self._row_get(row, "nombre_afiliado", "Nombre_Afiliado", "nombre", "Nombre"),
                    "empresa": empresa,
                    "observacion": observacion,
                }
            )
        return tareas, ""

    def _listar_tareas_asignadas_local(self) -> tuple[list[dict], str]:
        db_path = os.path.join(str(get_data_dir()), "db_gestiones.sqlite")
        if not os.path.exists(db_path):
            return [], ""
        try:
            with sqlite3.connect(db_path) as con:
                df = pd.read_sql(
                    f"SELECT id, Rut_Afiliado, Nombre_Afiliado, Estado, Observacion FROM {TABLA}",
                    con,
                ).fillna("")
        except Exception as exc:
            return [], str(exc)

        rows = [
            {
                "id": int(r.get("id", 0) or 0),
                "rut_afiliado": str(r.get("Rut_Afiliado", "")).strip(),
                "nombre_afiliado": str(r.get("Nombre_Afiliado", "")).strip(),
                "estado": str(r.get("Estado", "")).strip(),
                "observacion": str(r.get("Observacion", "")).strip(),
                "empresa": "",
            }
            for _, r in df.iterrows()
        ]

        completadas_ref = self._ref_ids_gestiones_realizadas(rows)
        tareas: list[dict] = []
        for row in rows:
            if not self._es_gestion_asignada(row.get("estado", "")):
                continue
            if not self._gestion_es_para_sesion_actual(row.get("observacion", "")):
                continue
            gid = int(row.get("id", 0) or 0)
            if gid and gid in completadas_ref:
                continue
            tareas.append(
                {
                    "id": gid,
                    "rut": str(row.get("rut_afiliado", "")).strip(),
                    "nombre": str(row.get("nombre_afiliado", "")).strip(),
                    "empresa": "",
                    "observacion": str(row.get("observacion", "")).strip(),
                }
            )
        return tareas, ""

    def _refrescar_panel_tareas_asignadas(self) -> None:
        s = self.sidebar
        if not hasattr(s, "card_tareas"):
            return
        s.card_tareas.setVisible(self._es_ejecutivo())
        if not self._es_ejecutivo():
            return

        if self._usa_backend_deudores():
            tareas, err = self._listar_tareas_asignadas_backend()
        else:
            tareas, err = self._listar_tareas_asignadas_local()

        if err:
            tareas = []

        self._tareas_asignadas = tareas
        s.tbl_tareas.setRowCount(0)
        for ri, tarea in enumerate(tareas):
            s.tbl_tareas.insertRow(ri)
            chk = QTableWidgetItem("")
            chk.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            chk.setCheckState(Qt.CheckState.Unchecked)
            chk.setData(Qt.ItemDataRole.UserRole, int(tarea.get("id", 0) or 0))
            s.tbl_tareas.setItem(ri, 0, chk)

            rut_item = QTableWidgetItem(str(tarea.get("rut", "")))
            rut_item.setToolTip(str(tarea.get("observacion", "")))
            s.tbl_tareas.setItem(ri, 1, rut_item)

            nombre_item = QTableWidgetItem(str(tarea.get("nombre", "")))
            nombre_item.setToolTip(str(tarea.get("observacion", "")))
            s.tbl_tareas.setItem(ri, 2, nombre_item)

        s.btn_marcar_tareas.setEnabled(bool(tareas))

    def _marcar_tareas_asignadas_realizadas(self) -> None:
        if not self._es_ejecutivo():
            return
        s = self.sidebar
        if not hasattr(s, "tbl_tareas"):
            return

        ids_marcados: list[int] = []
        for ri in range(s.tbl_tareas.rowCount()):
            item = s.tbl_tareas.item(ri, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            try:
                gid = int(item.data(Qt.ItemDataRole.UserRole) or 0)
            except Exception:
                gid = 0
            if gid:
                ids_marcados.append(gid)

        if not ids_marcados:
            QMessageBox.information(self, "Sin selección", "Marca al menos una gestión asignada.")
            return

        index_by_id = {int(t.get("id", 0) or 0): t for t in self._tareas_asignadas}
        hoy = datetime.datetime.now().strftime("%d/%m/%Y")
        ok_count = 0
        errores: list[str] = []
        ruts_actualizar: set[str] = set()

        for gid in ids_marcados:
            tarea = index_by_id.get(gid)
            if not tarea:
                continue
            rut = str(tarea.get("rut", "")).strip()
            nombre = str(tarea.get("nombre", "")).strip() or rut
            empresa = str(tarea.get("empresa", "")).strip()
            obs_base = str(tarea.get("observacion", "")).strip()
            obs_cierre = f"Cierre de tarea asignada Ref#{gid}"
            if obs_base:
                obs_cierre += f" | {obs_base}"

            if self._usa_backend_deudores():
                _, err = backend_marcar_gestion_asignada_realizada(
                    self._session,
                    gestion_id=gid,
                )
                if err:
                    errores.append(f"{rut}: {err}")
                    continue
            else:
                try:
                    insertar_gestion_manual(
                        rut=rut,
                        nombre=nombre,
                        tipo_gestion="Manual",
                        estado="Gestión realizada",
                        fecha=hoy,
                        observacion=obs_cierre,
                    )
                except Exception as exc:
                    errores.append(f"{rut}: {exc}")
                    continue

            ok_count += 1
            if rut:
                ruts_actualizar.add(rut)

        for rut in ruts_actualizar:
            self._refrescar_estado_deudor_en_tabla(rut)

        self._refrescar_panel_tareas_asignadas()

        if errores:
            detalle = "\n".join(errores[:5])
            QMessageBox.warning(
                self,
                "Resultado parcial",
                f"Se marcaron {ok_count} gestión(es) como realizadas.\n\nErrores:\n{detalle}",
            )
        else:
            QMessageBox.information(
                self,
                "Gestiones actualizadas",
                f"✅ Se marcaron {ok_count} gestión(es) como realizadas.",
            )

    def _mostrar_sin_carteras_asignadas(self) -> None:
        self._df = None
        self._df_detalle = None
        self._columnas = []
        self._etiquetas = []
        self.table.setModel(None)
        self.table.setVisible(False)
        self.lbl_placeholder.setVisible(True)
        self.lbl_placeholder.setText("Carga un archivo Excel para visualizar la base de deudores.")
        self.lbl_placeholder.setText("Sin carteras asignadas. Contacta a un supervisor o administrador.")
        s = self.sidebar
        s.txt_search.clear()
        s.txt_search.setEnabled(False)
        s.cmb_filtro_empresa.setEnabled(False)
        s.cmb_col.clear()
        s.cmb_col.addItem("Todas las columnas")
        s.cmb_col.setEnabled(False)
        if hasattr(s, "cmb_periodo"):
            s.cmb_periodo.blockSignals(True)
            s.cmb_periodo.clear()
            s.cmb_periodo.addItem("Acumulado")
            s.cmb_periodo.setEnabled(False)
            s.cmb_periodo.blockSignals(False)
        s.lbl_resultados.setText("Sin carteras asignadas")
        self.lbl_total.setText("Sin carteras asignadas")

    def _connect_ui(self) -> None:
        s = self.sidebar
        s.btn_pick.clicked.connect(self._pick_excel)
        s.btn_cargar.clicked.connect(self._cargar_base)
        s.txt_search.textChanged.connect(self._on_search_changed)
        s.btn_cls.clicked.connect(lambda: s.txt_search.clear())
        s.cmb_filtro_empresa.currentIndexChanged.connect(self._on_search_changed)
        s.cmb_col.currentIndexChanged.connect(self._on_search_changed)
        s.btn_pick_gest.clicked.connect(self._pick_gestiones)
        s.btn_descargar_plantilla_gest.clicked.connect(self._descargar_plantilla_gestiones)
        s.btn_cargar_gest.clicked.connect(self._cargar_gestiones)
        s.chk_descarga_completa.toggled.connect(self._toggle_descarga_gestiones_fields)
        s.btn_descargar_gestiones.clicked.connect(self._descargar_base_gestiones)
        if hasattr(s, "btn_refrescar_tareas"):
            s.btn_refrescar_tareas.clicked.connect(self._refrescar_panel_tareas_asignadas)
        if hasattr(s, "btn_marcar_tareas"):
            s.btn_marcar_tareas.clicked.connect(self._marcar_tareas_asignadas_realizadas)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.setSortingEnabled(False)

    def _ajustar_splitter_inicial(self) -> None:
        parent_width = self._splitter.parentWidget().width() if self._splitter.parentWidget() else 0
        total = max(self._splitter.width(), self.width(), parent_width, 1)

        left_target = int(total * 0.33)
        left_target = max(240, min(520, left_target))

        right_min = 460 if total >= 980 else 340
        if total - left_target < right_min:
            left_target = max(220, total - right_min)

        right_target = max(right_min, total - left_target)
        self._splitter.setSizes([left_target, right_target])

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._ajustar_splitter_inicial)
        QTimer.singleShot(120, self._ajustar_splitter_inicial)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._ajustar_splitter_si_hace_falta)

    def _ajustar_splitter_si_hace_falta(self) -> None:
        sizes = self._splitter.sizes()
        if len(sizes) != 2:
            return False

        total = sum(sizes)
        if total <= 0:
            return

        left_size, right_size = sizes

        if left_size < 230 or right_size < 330:
            self._ajustar_splitter_inicial()

    def _toggle_descarga_gestiones_fields(self) -> None:
        completa = self.sidebar.chk_descarga_completa.isChecked()
        self.sidebar.date_desde.setEnabled(not completa)
        self.sidebar.date_hasta.setEnabled(not completa)

    def _agregar_estado_deudor(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df

        df_out = df.copy()

        if COLUMNA_RUT not in df_out.columns:
            df_out["Estado_deudor"] = ESTADO_DEUDOR_DEFAULT
            return df_out

        # En modo backend el estado ya viene calculado por la API.
        # Aqu solo usamos el mapa local como refuerzo, sin pisar el valor
        # que ya trae el dataframe.
        mapa_estados = obtener_estados_deudor_por_rut()

        rut_norm = (
            df_out[COLUMNA_RUT].astype(str)
            .str.replace(".", "", regex=False)
            .str.replace("-", "", regex=False)
            .str.strip()
            .str.lstrip("0")
        )

        estado_actual = (
            df_out["Estado_deudor"]
            if "Estado_deudor" in df_out.columns
            else pd.Series([ESTADO_DEUDOR_DEFAULT] * len(df_out), index=df_out.index)
        )

        df_out["Estado_deudor"] = rut_norm.map(mapa_estados).fillna(estado_actual).fillna(ESTADO_DEUDOR_DEFAULT)
        return df_out

    def _formatear_moneda_cl(self, valor) -> str:
        try:
            if valor is None:
                return ""

            v = str(valor).strip()
            if v.lower() in ("", "nan", "none"):
                return ""

            v = v.replace("$", "").replace(" ", "")

            if "," in v and "." in v:
                v = v.replace(".", "").split(",")[0]
            elif "," in v:
                v = v.split(",")[0]

            n = float(v)
            return f"$ {int(n):,}".replace(",", ".")
        except Exception:
            return str(valor)

    def _formatear_columnas_monetarias(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df

        df_out = df.copy()
        columnas_monto = ["Copago", "Total_Pagos", "Saldo_Actual"]

        for col in columnas_monto:
            if col in df_out.columns:
                df_out[col] = df_out[col].apply(self._formatear_moneda_cl)

        return df_out

    def _es_columna_numerica(self, columna: str) -> bool:
        return {
            "Rut_Afiliado",
            "Dv",
            "Nro_Expediente",
            "Copago",
            "Total_Pagos",
            "Saldo_Actual",
        }.__contains__(columna)

    def _es_columna_fecha(self, columna: str) -> bool:
        return columna in {"MAX_Emision_ok", "MIN_Emision_ok"}

    def _serie_numerica_para_sort(self, serie: pd.Series) -> pd.Series:
        s = serie.astype(str).str.strip()
        s = s.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "": pd.NA})
        s = s.str.replace("$", "", regex=False)
        s = s.str.replace(" ", "", regex=False)
        s = s.str.replace(".", "", regex=False)
        s = s.str.replace(",", "", regex=False)
        return pd.to_numeric(s, errors="coerce")

    def _serie_fecha_para_sort(self, serie: pd.Series) -> pd.Series:
        s = serie.astype(str).str.strip()
        s = s.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "": pd.NA})
        s = s.str.replace(".0", "", regex=False)

        fechas = pd.to_datetime(s, format="%Y%m", errors="coerce")
        faltantes = fechas.isna()
        if faltantes.any():
            fechas_alt = pd.to_datetime(s[faltantes], format="%m/%Y", errors="coerce")
            fechas.loc[faltantes] = fechas_alt
        return fechas

    def _serie_texto_para_sort(self, serie: pd.Series) -> pd.Series:
        return serie.astype(str).str.strip().str.lower()

    def _ordenar_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty or not self._sort_column or self._sort_column not in df.columns:
            return df

        ascending = self._sort_order == Qt.SortOrder.AscendingOrder
        df_out = df.copy()

        if self._es_columna_fecha(self._sort_column):
            df_out["_sort_key_temp"] = self._serie_fecha_para_sort(df_out[self._sort_column])
        elif self._es_columna_numerica(self._sort_column):
            df_out["_sort_key_temp"] = self._serie_numerica_para_sort(df_out[self._sort_column])
        else:
            df_out["_sort_key_temp"] = self._serie_texto_para_sort(df_out[self._sort_column])

        df_out = df_out.sort_values(
            by=["_sort_key_temp", self._sort_column],
            ascending=[ascending, ascending],
            na_position="last",
            kind="mergesort",
        ).drop(columns=["_sort_key_temp"])

        return df_out.reset_index(drop=True)

    def _actualizar_indicador_orden(self) -> None:
        header = self.table.horizontalHeader()
        if not self._sort_column or self._sort_column not in self._columnas:
            header.setSortIndicatorShown(False)
            return

        section = self._columnas.index(self._sort_column)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(section, self._sort_order)

    def _on_header_clicked(self, section: int) -> None:
        if self._df is None or self._df.empty:
            return
        if section < 0 or section >= len(self._columnas):
            return

        columna = self._columnas[section]
        if columna == COLUMNA_EMPRESA:
            return

        if self._sort_column == columna:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = columna
            self._sort_order = Qt.SortOrder.AscendingOrder

        self._mostrar_dataframe(self._df)


    def _backend_items_a_dataframe(self, items: list[dict]) -> pd.DataFrame:
        rows = []
        for item in items or []:
            rows.append({
                "_empresa": str(item.get("empresa", "")).strip(),
                "Rut_Afiliado": str(item.get("rut_afiliado", "")).strip(),
                "Dv": str(item.get("dv", "")).strip(),
                "_RUT_COMPLETO": str(item.get("rut_completo", "")).strip(),
                "Nombre_Afiliado": str(item.get("nombre_afiliado", "")).strip(),
                "Estado_deudor": str(item.get("estado_deudor", "")).strip() or ESTADO_DEUDOR_DEFAULT,
                "BN": str(item.get("bn", "")).strip(),
                "Nro_Expediente": str(item.get("nro_expediente", "")).strip(),
                "MAX_Emision_ok": str(item.get("max_emision_ok", "")).strip(),
                "MIN_Emision_ok": str(item.get("min_emision_ok", "")).strip(),
                "Copago": item.get("copago", 0),
                "Total_Pagos": item.get("total_pagos", 0),
                "Saldo_Actual": item.get("saldo_actual", 0),
                "_source_file": str(item.get("source_file", "")).strip(),
                "_periodo_carga": str(item.get("periodo_carga", "")).strip(),
            })
        return pd.DataFrame(rows).fillna("")

    def _backend_detalle_response_to_local(self, payload: dict) -> tuple[pd.DataFrame, dict]:
        detalle_rows = []
        for item in (payload.get("detalle") or []):
            detalle_rows.append({
                "_empresa": str(item.get("empresa", "")).strip(),
                "Rut_Afiliado": str(item.get("rut_afiliado", "")).strip(),
                "Dv": str(item.get("dv", "")).strip(),
                "_RUT_COMPLETO": str(item.get("rut_completo", "")).strip(),
                "Nombre_Afiliado": str(item.get("nombre_afiliado", "")).strip(),
                "Nombre Afil": str(item.get("nombre_afil", "")).strip(),
                "RUT Afil": str(item.get("rut_afil", "")).strip(),
                "Fecha Pago": str(item.get("fecha_pago", "")).strip(),
                "mail_afiliado": str(item.get("mail_afiliado", "")).strip(),
                "BN": str(item.get("bn", "")).strip(),
                "telefono_fijo_afiliado": str(item.get("telefono_fijo_afiliado", "")).strip(),
                "telefono_movil_afiliado": str(item.get("telefono_movil_afiliado", "")).strip(),
                "Nro_Expediente": str(item.get("nro_expediente", "")).strip(),
                "Fecha_Emision": str(item.get("fecha_emision", "")).strip(),
                "Copago": item.get("copago", 0),
                "Total_Pagos": item.get("total_pagos", 0),
                "Saldo_Actual": item.get("saldo_actual", 0),
                "Cart56_Fecha_Recep": str(item.get("cart56_fecha_recep", "")).strip(),
                "Cart56_Fecha_Recep_ISA": str(item.get("cart56_fecha_recep_isa", "")).strip(),
                "Cart56_Dias_Pagar": str(item.get("cart56_dias_pagar", "")).strip(),
                "Cart56_Mto_Pagar": item.get("cart56_mto_pagar", 0),
                "Mail Emp": str(item.get("mail_emp", "")).strip(),
                "Telefono Empleador": str(item.get("telefono_empleador", "")).strip(),
                "Estado_deudor": str(item.get("estado_deudor", "")).strip() or ESTADO_DEUDOR_DEFAULT,
                "_source_file": str(item.get("source_file", "")).strip(),
                "_periodo_carga": str(item.get("periodo_carga", "")).strip(),
            })
        df_detalle = pd.DataFrame(detalle_rows).fillna("")
        df_detalle = self._enriquecer_detalle_cart56_desde_cache(df_detalle)
        resumen_raw = payload.get("resumen") or {}
        fila_resumen = {
            "_empresa": str((payload.get("empresa") or resumen_raw.get("empresa") or "")).strip(),
            "Rut_Afiliado": str(resumen_raw.get("rut_afiliado", payload.get("rut", ""))).strip(),
            "Dv": str(resumen_raw.get("dv", "")).strip(),
            "_RUT_COMPLETO": str(resumen_raw.get("rut_completo", "")).strip(),
            "Nombre_Afiliado": str(resumen_raw.get("nombre_afiliado", "")).strip(),
            "Estado_deudor": str(resumen_raw.get("estado_deudor", "")).strip() or ESTADO_DEUDOR_DEFAULT,
            "BN": str(resumen_raw.get("bn", "")).strip(),
            "Nro_Expediente": str(resumen_raw.get("nro_expediente", "")).strip(),
            "MAX_Emision_ok": str(resumen_raw.get("max_emision_ok", "")).strip(),
            "MIN_Emision_ok": str(resumen_raw.get("min_emision_ok", "")).strip(),
            "Copago": resumen_raw.get("copago", 0),
            "Total_Pagos": resumen_raw.get("total_pagos", 0),
            "Saldo_Actual": resumen_raw.get("saldo_actual", 0),
            "_source_file": str(resumen_raw.get("source_file", "")).strip(),
            "_periodo_carga": str(resumen_raw.get("periodo_carga", "")).strip(),
        }
        return df_detalle, fila_resumen

    def _cache_cart56_detalle_desde_excel(self, excel_path: str) -> None:
        try:
            df_raw = pd.read_excel(excel_path, sheet_name=0, dtype=str).fillna("")
            _, df_detalle = transformar_cart56_raw(df_raw)
            self._cart56_detalle_cache_df = df_detalle.copy().fillna("")
            # Persistimos este detalle en la DB local para reutilizarlo entre sesiones/usuarios.
            guardar_detalle(self._cart56_detalle_cache_df, "Cart-56", source_file=os.path.abspath(excel_path))
        except Exception:
            self._cart56_detalle_cache_df = None

    def _enriquecer_detalle_cart56_desde_cache(self, df_detalle: pd.DataFrame) -> pd.DataFrame:
        if df_detalle is None or df_detalle.empty:
            return df_detalle
        if self._cart56_detalle_cache_df is None or self._cart56_detalle_cache_df.empty:
            try:
                self._cart56_detalle_cache_df = cargar_detalle_empresa("Cart-56")
            except Exception:
                self._cart56_detalle_cache_df = None
        if self._cart56_detalle_cache_df is None or self._cart56_detalle_cache_df.empty:
            return df_detalle

        df = df_detalle.copy().fillna("")
        if "_empresa" in df.columns:
            empresas = df["_empresa"].astype(str).str.strip().str.lower()
            if not empresas.eq("cart-56").any():
                return df

        cache = self._cart56_detalle_cache_df.copy().fillna("")

        def _norm_rut(v: str) -> str:
            t = str(v or "").strip().replace(".", "")
            if "-" in t:
                t = t.split("-", 1)[0]
            return t.replace("-", "").lstrip("0")

        def _norm_txt(v: str) -> str:
            return str(v or "").strip()

        map_full: dict[tuple[str, str, str], tuple[str, str, str]] = {}
        map_reduced: dict[tuple[str, str], tuple[str, str, str]] = {}
        for _, r in cache.iterrows():
            rut = _norm_rut(r.get("Rut_Afiliado", ""))
            exp = _norm_txt(r.get("Nro_Expediente", ""))
            fem = _norm_txt(r.get("Fecha_Emision", ""))
            if not rut or not exp:
                continue
            vals = (
                _norm_txt(r.get("Nombre Afil", "")),
                _norm_txt(r.get("RUT Afil", "")),
                _norm_txt(r.get("Fecha Pago", "")),
            )
            map_full[(rut, exp, fem)] = vals
            map_reduced[(rut, exp)] = vals

        for idx, row in df.iterrows():
            has_missing = any(
                str(row.get(c, "")).strip() in ("", "nan", "None", "—")
                for c in ("Nombre Afil", "RUT Afil", "Fecha Pago")
            )
            if not has_missing:
                continue

            rut = _norm_rut(row.get("Rut_Afiliado", ""))
            exp = _norm_txt(row.get("Nro_Expediente", ""))
            fem = _norm_txt(row.get("Fecha_Emision", ""))
            vals = map_full.get((rut, exp, fem)) or map_reduced.get((rut, exp))
            if not vals:
                continue

            n_afil, rut_afil, fecha_pago = vals
            if str(row.get("Nombre Afil", "")).strip() in ("", "nan", "None", "—") and n_afil:
                df.at[idx, "Nombre Afil"] = n_afil
            if str(row.get("RUT Afil", "")).strip() in ("", "nan", "None", "—") and rut_afil:
                df.at[idx, "RUT Afil"] = rut_afil
            if str(row.get("Fecha Pago", "")).strip() in ("", "nan", "None", "—") and fecha_pago:
                df.at[idx, "Fecha Pago"] = fecha_pago

        return df

    def _cargar_desde_backend(self) -> bool:
        if self._sin_carteras_asignadas():
            self._mostrar_sin_carteras_asignadas()
            return

        items_total: list[dict] = []

        if self._tiene_restriccion_por_cartera() and self._empresas_asignadas:
            for empresa in self._empresas_asignadas_actuales():
                items, err = backend_list_deudores(self._session, empresa=empresa, periodo_carga="" if self._periodo_actual() == "Acumulado" else self._periodo_actual(), limit=5000)
                if err:
                    QMessageBox.warning(self, "Error de conexión", err)
                    return
                items_total.extend(items)
        else:
            items_total, err = backend_list_deudores(self._session, periodo_carga="" if self._periodo_actual() == "Acumulado" else self._periodo_actual(), limit=5000)
            if err:
                QMessageBox.warning(self, "Error de conexión", err)
                return

        if not items_total:
            self._limpiar_vista()
            self.lbl_placeholder.setVisible(True)
            self.lbl_placeholder.setText("No hay deudores cargados en el backend. Usa 'Cargar base' para subir una empresa.")
            return

        df_all = self._backend_items_a_dataframe(items_total)
        self._df_detalle = None
        self._mostrar_dataframe(df_all)
        self.sidebar.btn_cargar.setToolTip(f"Datos cargados desde CRM_Backend  {len(df_all):,} registros.")


    def _cargar_desde_backend(self) -> bool:
        items_total: list[dict] = []
        periodo = "" if self._periodo_actual() == "Acumulado" else self._periodo_actual()

        items_total, err = backend_list_deudores(
            self._session,
            periodo_carga=periodo,
            limit=5000,
        )
        if err:
            QMessageBox.warning(self, "Error de conexión", err)
            return False

        if not items_total:
            self._limpiar_vista()
            self.lbl_placeholder.setVisible(True)
            self.lbl_placeholder.setText("No hay deudores cargados en el backend. Usa 'Cargar base' para subir una empresa.")
            return False

        df_all = self._backend_items_a_dataframe(items_total)
        self._df_detalle = None
        self._mostrar_dataframe(df_all)
        self.sidebar.btn_cargar.setToolTip(f"Datos cargados desde CRM_Backend  {len(df_all):,} registros.")
        return True

    def _restaurar_filtros_ui(self, *, texto: str, empresa: str, col_idx: int, periodo: str = "Acumulado") -> None:
        s = self.sidebar
        s.txt_search.blockSignals(True)
        s.cmb_filtro_empresa.blockSignals(True)
        s.cmb_col.blockSignals(True)

        s.txt_search.setText(texto)

        idx_empresa = s.cmb_filtro_empresa.findText(empresa)
        if idx_empresa >= 0:
            s.cmb_filtro_empresa.setCurrentIndex(idx_empresa)

        if 0 <= col_idx < s.cmb_col.count():
            s.cmb_col.setCurrentIndex(col_idx)

        if hasattr(s, "cmb_periodo"):
            s.cmb_periodo.blockSignals(True)
            idx_periodo = s.cmb_periodo.findText(periodo)
            if idx_periodo >= 0:
                s.cmb_periodo.setCurrentIndex(idx_periodo)
            s.cmb_periodo.blockSignals(False)

        s.txt_search.blockSignals(False)
        s.cmb_filtro_empresa.blockSignals(False)
        s.cmb_col.blockSignals(False)
        self._apply_filter()

    def _seleccionar_rut_en_tabla(self, rut: str) -> None:
        proxy = self.table.model()
        if proxy is None or not rut:
            return

        rut_norm = str(rut).strip().replace(".", "").replace("-", "").lstrip("0")
        if not rut_norm:
            return

        try:
            source_model = proxy.sourceModel()
            rut_col_idx = next((i for i, c in enumerate(self._columnas) if c == COLUMNA_RUT), None)
            if source_model is None or rut_col_idx is None:
                return

            for row in range(source_model.rowCount()):
                item = source_model.item(row, rut_col_idx)
                if item is None:
                    continue

                item_rut = str(item.text()).strip().replace(".", "").replace("-", "").lstrip("0")
                if item_rut == rut_norm:
                    src_index = source_model.index(row, 0)
                    proxy_index = proxy.mapFromSource(src_index)
                    if proxy_index.isValid():
                        self.table.selectRow(proxy_index.row())
                        self.table.scrollTo(proxy_index)
                    return
        except Exception:
            return

    def _refrescar_backend_manteniendo_contexto(self, rut_focus: str | None = None) -> None:
        s = self.sidebar
        texto = s.txt_search.text()
        empresa = s.cmb_filtro_empresa.currentText()
        col_idx = s.cmb_col.currentIndex()
        periodo = self._periodo_actual()

        self._cargar_desde_backend()
        self._restaurar_filtros_ui(texto=texto, empresa=empresa, col_idx=col_idx, periodo=periodo)

        if rut_focus:
            self._seleccionar_rut_en_tabla(rut_focus)

    def _recargar_backend_post_import(self, empresa: str, source_file: str) -> bool:
        source_name = os.path.basename(str(source_file or "")).strip().lower()
        # Espera confirmacin real de que la carga ya est visible por empresa/source_file.
        # Antes se aceptaba cualquier lista no vaca y eso generaba falsos positivos.
        for intento in range(8):
            items, err = backend_list_deudores(
                self._session,
                empresa=empresa,
                periodo_carga="",
                limit=5000,
            )
            if not err:
                if source_name:
                    if any(
                        os.path.basename(str(item.get("source_file", "")).strip()).lower() == source_name
                        for item in (items or [])
                    ):
                        return self._cargar_desde_backend()
                elif items:
                    return self._cargar_desde_backend()

            if intento < 7:
                QApplication.processEvents()
                sleep(0.3)

        return self._cargar_desde_backend()

    def _refrescar_estado_deudor_en_tabla(self, rut_focus: str | None = None) -> None:
        if self._usa_backend_deudores():
            self._refrescar_backend_manteniendo_contexto(rut_focus=rut_focus)
            self._refrescar_panel_tareas_asignadas()
            return

        if self._df is None or self._df.empty:
            return

        df_all = cargar_todas()
        if df_all.empty:
            self._limpiar_vista()
            self._refrescar_panel_tareas_asignadas()
            return

        self._mostrar_dataframe(df_all)
        self._refrescar_panel_tareas_asignadas()

    def _cargar_desde_db(self):
        if self._sin_carteras_asignadas():
            self._mostrar_sin_carteras_asignadas()
            return

        if not hay_datos():
            self.sidebar.btn_cargar.setToolTip("Sin datos. Sube un Excel para comenzar.")
            return
        df_all = cargar_todas()
        self._df_detalle = cargar_detalle_todas()

        if df_all.empty:
            return
        self._mostrar_dataframe(df_all)
        self.sidebar.btn_cargar.setToolTip(f"Datos cargados desde base de datos  {len(df_all):,} registros.")
        self._refrescar_panel_tareas_asignadas()

    def _seleccionar_excel_deudores(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar base de deudores", "", "Excel (*.xlsx *.xls)")
        if path:
            self.sidebar.txt_excel.setText(path)
            self.sidebar.btn_cargar.setToolTip("Archivo listo. Pulsa 'Cargar base'.")
        return str(path or "").strip()

    def _pick_excel(self):
        if not self._puede_cargar_bases():
            QMessageBox.warning(self, "Acceso restringido", "Solo administradores y supervisores pueden cargar bases.")
            return

        self._seleccionar_excel_deudores()

    def _pick_gestiones(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar base de gestiones", "", "Excel (*.xlsx *.xls)")
        if path:
            self.sidebar.txt_gest_excel.setText(path)
            self.sidebar.btn_cargar_gest.setToolTip("Archivo listo. Pulsa 'Cargar gestiones'.")

    def _descargar_plantilla_gestiones(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar plantilla de gestiones",
            "plantilla_gestiones.xlsx",
            "Excel (*.xlsx)"
        )

        if not path:
            QMessageBox.warning(
                self,
                "Descarga cancelada",
                "No se seleccion una ubicacin para guardar la plantilla."
            )
            return

        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            df_sms = pd.DataFrame([
                {
                    "Rut_Afiliado": "12345678",
                    "Dv": "9",
                    "Nombre_Afiliado": "Juan Perez",
                    "telefono_movil_afiliado": "912345678",
                    "Estado": "Contactado",
                    "Fecha_gestion": "2024-01-01",
                    "Observacion": "Ejemplo de gestión SMS"
                }
            ])

            df_email = pd.DataFrame([
                {
                    "Rut_Afiliado": "12345678",
                    "Dv": "9",
                    "Nombre_Afiliado": "Juan Perez",
                    "mail_afiliado": "juan.perez@email.com",
                    "Estado": "Contactado",
                    "Fecha_gestion": "2024-01-01",
                    "Observacion": "Ejemplo de gestión Email"
                }
            ])

            df_carta = pd.DataFrame([
                {
                    "Rut_Afiliado": "12345678",
                    "Dv": "9",
                    "Nombre_Afiliado": "Juan Perez",
                    "direccion_afiliado": "Av. Ejemplo 123",
                    "comuna_afiliado": "Santiago",
                    "Estado": "Contactado",
                    "Fecha_gestion": "2024-01-01",
                    "Observacion": "Ejemplo de gestión Carta"
                }
            ])

            write_excel_report(
                path,
                {
                    "SMS": df_sms,
                    "Email": df_email,
                    "Carta": df_carta,
                },
            )

            QMessageBox.information(
                self,
                "Plantilla generada",
                f"La plantilla de gestiones se guard correctamente en:\n{path}"
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo generar la plantilla de gestiones.\n\nDetalle:\n{e}"
            )

    def _normalizar_columnas_exportacion_gestiones(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(
                columns=[
                    "Rut_Afiliado",
                    "Nombre_Afiliado",
                    "Tipo_gestion",
                    "Estado",
                    "Fecha_gestion",
                    "Observacion",
                    "Origen",
                ]
            )

        out = df.copy()
        out = out.rename(columns={
            "rut_afiliado": "Rut_Afiliado",
            "nombre_afiliado": "Nombre_Afiliado",
            "tipo_gestion": "Tipo_gestion",
            "estado": "Estado",
            "fecha_gestion": "Fecha_gestion",
            "observacion": "Observacion",
            "origen": "Origen",
        })

        columnas_preferidas = [
            "Rut_Afiliado",
            "Nombre_Afiliado",
            "Tipo_gestion",
            "Estado",
            "Fecha_gestion",
            "Observacion",
            "Origen",
        ]
        columnas_presentes = [col for col in columnas_preferidas if col in out.columns]
        otras_columnas = [col for col in out.columns if col not in columnas_presentes]
        return out[columnas_presentes + otras_columnas]

    def _descargar_base_gestiones(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar base de gestiones",
            "base_gestiones.xlsx",
            "Excel (*.xlsx)"
        )

        if not path:
            return

        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            if self._usa_backend_deudores():
                fecha_desde_txt = ""
                fecha_hasta_txt = ""

                if not self.sidebar.chk_descarga_completa.isChecked():
                    desde_qdate = self.sidebar.date_desde.date()
                    hasta_qdate = self.sidebar.date_hasta.date()

                    if desde_qdate > hasta_qdate:
                        QMessageBox.warning(
                            self,
                            "Rango inválido",
                            "La fecha 'Desde' no puede ser mayor que la fecha 'Hasta'."
                        )
                        return

                    fecha_desde_txt = f"{desde_qdate.day():02d}/{desde_qdate.month():02d}/{desde_qdate.year():04d}"
                    fecha_hasta_txt = f"{hasta_qdate.day():02d}/{hasta_qdate.month():02d}/{hasta_qdate.year():04d}"

                rows, err = backend_list_all_gestiones(
                    self._session,
                    fecha_desde=fecha_desde_txt,
                    fecha_hasta=fecha_hasta_txt,
                )
                if err:
                    raise ValueError(err)

                df = pd.DataFrame(rows).fillna("")
            else:
                db_path = os.path.join(str(get_data_dir()), "db_gestiones.sqlite")

                if not os.path.exists(db_path):
                    QMessageBox.information(
                        self,
                        "Sin base de gestiones",
                        "Aún no existe una base de gestiones para exportar."
                    )
                    return

                with sqlite3.connect(db_path) as con:
                    df = pd.read_sql(f"SELECT * FROM {TABLA}", con).fillna("")

            df = self._normalizar_columnas_exportacion_gestiones(df)

            if df.empty:
                QMessageBox.information(
                    self,
                    "Sin datos",
                    "No hay gestiones registradas para exportar."
                )
                return

            if not self._usa_backend_deudores() and not self.sidebar.chk_descarga_completa.isChecked():
                desde_qdate = self.sidebar.date_desde.date()
                hasta_qdate = self.sidebar.date_hasta.date()

                if desde_qdate > hasta_qdate:
                    QMessageBox.warning(
                        self,
                        "Rango inválido",
                        "La fecha 'Desde' no puede ser mayor que la fecha 'Hasta'."
                    )
                    return

                fecha_col = pd.to_datetime(
                    df.get("Fecha_gestion", pd.Series(dtype=str)),
                    format="%d/%m/%Y",
                    errors="coerce"
                )

                fecha_desde = pd.Timestamp(
                    year=desde_qdate.year(),
                    month=desde_qdate.month(),
                    day=desde_qdate.day()
                )
                fecha_hasta = pd.Timestamp(
                    year=hasta_qdate.year(),
                    month=hasta_qdate.month(),
                    day=hasta_qdate.day()
                )

                mask = fecha_col.notna() & (fecha_col >= fecha_desde) & (fecha_col <= fecha_hasta)
                df = df.loc[mask].copy()

            if df.empty:
                QMessageBox.information(
                    self,
                    "Sin resultados",
                    "No se encontraron gestiones para el rango de fechas seleccionado."
                )
                return

            if "Fecha_gestion" in df.columns:
                fecha_sort = pd.to_datetime(df["Fecha_gestion"], format="%d/%m/%Y", errors="coerce")
                df = df.assign(_fecha_sort=fecha_sort).sort_values(
                    by=["_fecha_sort", "id"] if "id" in df.columns else ["_fecha_sort"],
                    ascending=[False, False] if "id" in df.columns else [False]
                ).drop(columns=["_fecha_sort"])

            write_excel_report(path, {"Gestiones": df})

            QMessageBox.information(
                self,
                "Descarga completada",
                f"La base de gestiones se export correctamente en:\n{path}"
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo exportar la base de gestiones.\n\nDetalle:\n{e}"
            )

    def _cargar_base(self):
        if not self._puede_cargar_bases():
            QMessageBox.warning(self, "Acceso restringido", "Solo administradores y supervisores pueden cargar bases.")
            return

        path = self.sidebar.txt_excel.text().strip()
        if not path:
            path = self._seleccionar_excel_deudores()
            if not path:
                return
            self.sidebar.txt_excel.setText(path)

        if not os.path.isfile(path):
            path = self._seleccionar_excel_deudores()
            if not path or not os.path.isfile(path):
                QMessageBox.warning(self, "Archivo no vlido", "Selecciona un archivo Excel vlido de deudores.")
                return
            self.sidebar.txt_excel.setText(path)

        empresa = self.sidebar.cmb_empresa.currentText()

        if self._tiene_restriccion_por_cartera() and empresa not in self._empresas_asignadas_actuales():
            QMessageBox.warning(self, "Acceso restringido", "No puedes cargar bases de una empresa no asignada.")
            return

        if not self._usa_backend_deudores() and base_deudores_ya_cargada(empresa, path):
            QMessageBox.warning(
                self,
                "Base duplicada",
                f"La base '{os.path.basename(path)}' ya fue cargada anteriormente para {empresa}.\n\n"
                "No se puede importar dos veces la misma base de deudores.",
            )
            return

        if self._usa_backend_deudores():
            if str(empresa).strip().lower() == "cart-56":
                self._cache_cart56_detalle_desde_excel(path)

            def _empresa_fingerprint(rows: list[dict]) -> set[tuple[str, str, str, str]]:
                out: set[tuple[str, str, str, str]] = set()
                for it in rows or []:
                    out.add(
                        (
                            str(it.get("rut_afiliado", "")).strip(),
                            str(it.get("nro_expediente", "")).strip(),
                            str(it.get("source_file", "")).strip().lower(),
                            str(it.get("periodo_carga", "")).strip(),
                        )
                    )
                return out

            pre_items, _ = backend_list_deudores(
                self._session,
                empresa=empresa,
                periodo_carga="",
                limit=5000,
            )
            pre_fp = _empresa_fingerprint(pre_items or [])

            self.sidebar.progress.setVisible(True)
            self.sidebar.progress.setValue(15)
            self._set_loading(True)
            resultado, err = backend_import_deudores(self._session, empresa=empresa, excel_path=path)
            if err:
                # Reintento corto para absorber latencias/transientes de red/backend.
                QApplication.processEvents()
                sleep(0.25)
                resultado, err_retry = backend_import_deudores(self._session, empresa=empresa, excel_path=path)
                if not err_retry:
                    err = ""
                else:
                    err = err_retry
            if err:
                self._set_loading(False)
                self.sidebar.progress.setVisible(False)
                err_norm = self._texto_normalizado(err)
                if str(empresa).strip().lower() == "cart-56" and (
                    "ya fue cargada" in err_norm
                    or "no se puede importar dos veces" in err_norm
                    or "base duplicada" in err_norm
                ):
                    QMessageBox.information(
                        self,
                        "Actualizacion incremental no disponible en el servidor",
                        (
                            "La nomina Cart-56 ya existe en el servidor y el backend activo "
                            "aun esta usando la proteccion antigua contra duplicados.\n\n"
                            "Con la correccion nueva, esta carga deberia procesarse como actualizacion incremental, "
                            "registrando solo los No Licencia + Mto Pagar faltantes y omitiendo los ya existentes.\n\n"
                            "Para habilitarlo en la aplicacion real, primero hay que desplegar la version actualizada "
                            "del backend en el servidor."
                        ),
                    )
                    return
                QMessageBox.critical(self, "Error al cargar base de deudores", err)
                return

            if hasattr(self.sidebar, "cmb_periodo"):
                self.sidebar.cmb_periodo.blockSignals(True)
                idx_acumulado = self.sidebar.cmb_periodo.findText("Acumulado")
                if idx_acumulado >= 0:
                    self.sidebar.cmb_periodo.setCurrentIndex(idx_acumulado)
                self.sidebar.cmb_periodo.blockSignals(False)
            self.sidebar.txt_search.clear()

            self.sidebar.progress.setValue(70)

            ok_refresh = False
            items_emp: list[dict] = []
            for _ in range(9):
                rows_emp, err_emp = backend_list_deudores(
                    self._session,
                    empresa=empresa,
                    periodo_carga="",
                    limit=5000,
                )
                if not err_emp:
                    items_emp = rows_emp or []
                    post_fp = _empresa_fingerprint(items_emp)
                    if post_fp != pre_fp or items_emp:
                        ok_refresh = True
                        break
                QApplication.processEvents()
                sleep(0.25)

            if not ok_refresh:
                ok_refresh = self._recargar_backend_post_import(empresa=empresa, source_file=path)

            # En flujo backend/web la vista siempre debe quedar acumulada.
            # Evitamos pintar temporalmente solo la empresa recin cargada.
            ok_refresh = bool(self._cargar_desde_backend()) or ok_refresh
            self.sidebar.progress.setValue(100)
            self.sidebar.progress.setVisible(False)
            self._set_loading(False)
            self.sidebar.btn_cargar.setToolTip(
                f" Base de {empresa} cargada en CRM_Backend. "
                f"Resumen: {resultado.get('resumen_insertados', 0):,} | "
                f"Detalle: {resultado.get('detalle_insertados', 0):,}"
            )
            detalle_nuevos = int(resultado.get("detalle_nuevos", resultado.get("detalle_insertados", 0)) or 0)
            detalle_actualizados = int(resultado.get("detalle_actualizados", 0) or 0)
            detalle_omitidos = int(resultado.get("detalle_omitidos", 0) or 0)
            QMessageBox.information(
                self,
                "Carga actualizada",
                (
                    f"Nómina de {empresa} procesada correctamente.\n\n"
                    f"Registros nuevos: {detalle_nuevos:,}\n"
                    f"Registros actualizados: {detalle_actualizados:,}\n"
                    f"Registros omitidos por ya existir: {detalle_omitidos:,}\n"
                    f"Resumen recalculado: {int(resultado.get('resumen_insertados', 0) or 0):,}"
                ),
            )
            # Refrescos extra para cargas consecutivas (evita requerir segundo clic).
            QTimer.singleShot(250, self.refrescar_datos)
            QTimer.singleShot(900, self.refrescar_datos)
            if self._puede_cargar_bases():
                idx_todas = self.sidebar.cmb_filtro_empresa.findText("Todas")
                if idx_todas >= 0:
                    self.sidebar.cmb_filtro_empresa.setCurrentIndex(idx_todas)
            self._apply_filter()
            self.sidebar.txt_excel.clear()
            self.datos_actualizados.emit()
            QTimer.singleShot(0, self._ajustar_splitter_inicial)
            if not ok_refresh:
                QMessageBox.warning(
                    self,
                    "Carga completada con advertencia",
                    "La base se subi al backend, pero la vista no pudo refrescarse de inmediato.\n"
                    "Se actualizar en el prximo refresco automtico.",
                )
            return

        self._set_loading(True)
        self.sidebar.progress.setVisible(True)
        self.sidebar.progress.setValue(0)

        self._worker = CargaDeudoresWorker(CargaDeudoresParams(excel_path=path, empresa=empresa))
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_loaded)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str):
        self.sidebar.progress.setValue(pct)
        self.sidebar.btn_cargar.setToolTip(msg)

    def _on_loaded(self, df, columnas, etiquetas, df_detalle):
        from .database import (
            cargar_detalle_empresas,
            cargar_detalle_todas,
            cargar_empresas,
            cargar_todas,
        )

        self._set_loading(False)
        self.sidebar.progress.setVisible(False)

        self._df_detalle = cargar_detalle_todas()
        df_all = cargar_todas()

        self._mostrar_dataframe(df_all if not df_all.empty else df)

        empresa = self.sidebar.cmb_empresa.currentText()
        self.sidebar.btn_cargar.setToolTip(
            f"  Base de {empresa} integrada correctamente en la base acumulativa."
        )
        self.sidebar.txt_excel.clear()
        self.datos_actualizados.emit()

        QTimer.singleShot(0, self._ajustar_splitter_inicial)

    def _on_error(self, err: str):
        self._set_loading(False)
        self.sidebar.progress.setVisible(False)
        self.sidebar.btn_cargar.setToolTip("Error al cargar ")
        QMessageBox.critical(self, "Error al cargar base de deudores", err)

    def _mostrar_dataframe(self, df: pd.DataFrame):
        from .schema import EXCLUIR_EXACTAS, EXCLUIR_PREFIJOS, ORDEN_COLUMNAS

        if df is None or df.empty:
            self._limpiar_vista()
            return

        df_base = self._agregar_estado_deudor(df)

        def _excluir(col: str) -> bool:
            c_up = col.upper()
            if c_up in [e.upper() for e in EXCLUIR_EXACTAS]:
                return True
            return any(c_up.startswith(pref.upper()) for pref in EXCLUIR_PREFIJOS)

        cols_mostrar = [
            c for c in df_base.columns
            if (not c.startswith("_") or c == COLUMNA_EMPRESA) and c != "_fecha_carga" and not _excluir(c)
        ]
        cols_sin_empresa = [c for c in cols_mostrar if c != COLUMNA_EMPRESA]
        cols_ordenadas = [c for c in ORDEN_COLUMNAS if c in cols_sin_empresa]
        cols_resto = [c for c in cols_sin_empresa if c not in ORDEN_COLUMNAS]
        cols_mostrar = ([COLUMNA_EMPRESA] if COLUMNA_EMPRESA in cols_mostrar else []) + cols_ordenadas + cols_resto
        etiquetas = [ETIQUETAS.get(c, c) for c in cols_mostrar]

        df_base = self._ordenar_dataframe(df_base)
        self._df = df_base.reset_index(drop=True)
        self._columnas = cols_mostrar
        self._etiquetas = etiquetas

        df_display = self._formatear_columnas_monetarias(self._df.copy())

        model = DeudoresTableModel(df_display, cols_mostrar, etiquetas)
        proxy = EmpresaFilterProxy()
        proxy.setSourceModel(model)
        proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        proxy.setFilterKeyColumn(-1)
        if COLUMNA_EMPRESA in cols_mostrar:
            proxy.empresa_col_idx = cols_mostrar.index(COLUMNA_EMPRESA)
        self.table.setModel(proxy)
        self.table.resizeColumnsToContents()
        self._actualizar_indicador_orden()

        s = self.sidebar
        s.txt_search.setEnabled(True)
        s.cmb_col.setEnabled(True)
        s.cmb_filtro_empresa.blockSignals(True)
        s.cmb_filtro_empresa.clear()
        empresas_visibles = [e for e in EMPRESAS if e in self._df[COLUMNA_EMPRESA].astype(str).unique().tolist()]
        if len(empresas_visibles) != 1:
            s.cmb_filtro_empresa.addItem("Todas")
        s.cmb_filtro_empresa.addItems(empresas_visibles)
        if len(empresas_visibles) == 1:
            s.cmb_filtro_empresa.setCurrentIndex(0)
            s.cmb_filtro_empresa.setEnabled(False)
        else:
            s.cmb_filtro_empresa.setEnabled(True)
        s.cmb_filtro_empresa.blockSignals(False)
        s.cmb_col.clear()
        s.cmb_col.addItem("Todas las columnas")
        s.cmb_col.addItems(etiquetas)

        if hasattr(s, "cmb_periodo"):
            periodo_actual = s.cmb_periodo.currentText().strip()
            periodos = sorted(
                [p for p in self._df.get("_periodo_carga", pd.Series(dtype=str)).astype(str).str.strip().unique().tolist() if p],
                reverse=True,
            )
            s.cmb_periodo.blockSignals(True)
            s.cmb_periodo.clear()
            s.cmb_periodo.addItem("Acumulado")
            s.cmb_periodo.addItems(periodos)
            idx_periodo = s.cmb_periodo.findText(periodo_actual)
            s.cmb_periodo.setCurrentIndex(idx_periodo if idx_periodo >= 0 else 0)
            s.cmb_periodo.setEnabled(bool(periodos))
            s.cmb_periodo.blockSignals(False)

        n = len(self._df)
        pref = "Base cargada"
        self.lbl_total.setText(f"{pref}: {n:,} deudores")
        s.lbl_resultados.setText(f"Mostrando {n:,} registros")
        self.table.setVisible(True)
        self.lbl_placeholder.setVisible(False)

        self._apply_filter()
        self._refrescar_panel_tareas_asignadas()
        QTimer.singleShot(0, self._ajustar_splitter_inicial)

    def _on_search_changed(self):
        self._search_timer.start()

    def _apply_filter(self):
        if self._df is None or self._df.empty:
            return

        s = self.sidebar
        texto = s.txt_search.text().strip()
        empresa_sel = s.cmb_filtro_empresa.currentText()
        col_idx = s.cmb_col.currentIndex()
        periodo_sel = self._periodo_actual()

        df_base = self._filtrar_por_periodo(self._df)
        df_display = self._formatear_columnas_monetarias(df_base.copy())

        model = DeudoresTableModel(df_display, self._columnas, self._etiquetas)
        proxy = EmpresaFilterProxy()
        proxy.setSourceModel(model)
        proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        proxy.setFilterKeyColumn(-1)
        if COLUMNA_EMPRESA in self._columnas:
            proxy.empresa_col_idx = self._columnas.index(COLUMNA_EMPRESA)

        proxy.empresa_filtro = "" if empresa_sel == "Todas" else empresa_sel

        proxy.setFilterKeyColumn(-1 if col_idx == 0 else col_idx - 1)
        proxy.setFilterFixedString(texto)
        self.table.setModel(proxy)
        proxy.invalidateFilter()
        self._actualizar_indicador_orden()

        visible = proxy.rowCount()
        total = proxy.sourceModel().rowCount() if proxy.sourceModel() else 0
        s.lbl_resultados.setText(
            f"{visible:,} resultados de {total:,}" if (texto or empresa_sel != "Todas" or periodo_sel != "Acumulado") else f"Mostrando {total:,} registros"
        )

    def _on_double_click(self, index):
        proxy: EmpresaFilterProxy = self.table.model()
        if proxy is None:
            return

        src = proxy.mapToSource(index)
        model = proxy.sourceModel()
        rut_col_idx = next((i for i, c in enumerate(self._columnas) if c == COLUMNA_RUT), None)
        if rut_col_idx is None:
            return

        rut = model.item(src.row(), rut_col_idx).text().strip()
        if not rut:
            return

        fila_resumen = {}
        try:
            if self._df is not None and 0 <= src.row() < len(self._df):
                fila_resumen = self._df.iloc[src.row()].to_dict()
        except Exception:
            fila_resumen = {}

        if self._usa_backend_deudores():
            empresa = str(fila_resumen.get("_empresa", "")).strip()
            payload, err = backend_get_deudor_detalle(self._session, rut=rut, empresa=empresa)
            if err:
                QMessageBox.warning(self, "Sin detalle", err)
                return

            df_detalle_backend, fila_resumen_backend = self._backend_detalle_response_to_local(payload or {})
            fila_resumen.update(fila_resumen_backend)
            dlg = DetalleDeudorDialog(
                df_detalle_backend,
                rut,
                fila_resumen=fila_resumen,
                parent=self,
                session=self._session,
            )
            dlg.gestiones_actualizadas.connect(lambda: self._refrescar_estado_deudor_en_tabla(getattr(dlg, "_rut", rut)))
            dlg.exec()
            self._refrescar_estado_deudor_en_tabla(getattr(dlg, "_rut", rut))
            self._splitter.setSizes(self._splitter.sizes())
            return

        if self._df_detalle is None or self._df_detalle.empty:
            QMessageBox.information(
                self,
                "Sin detalle",
                "Este archivo no contiene hoja DETALLE o no se pudo cargar.\nVuelve a cargar el Excel para habilitar el detalle."
            )
            return

        dlg = DetalleDeudorDialog(cargar_detalle_todas(), rut, fila_resumen=fila_resumen, parent=self, session=self._session)
        dlg.gestiones_actualizadas.connect(lambda: self._refrescar_estado_deudor_en_tabla(getattr(dlg, "_rut", rut)))
        dlg.exec()
        self._refrescar_estado_deudor_en_tabla(getattr(dlg, "_rut", rut))
        self._splitter.setSizes(self._splitter.sizes())

    def _set_loading(self, loading: bool):
        s = self.sidebar
        s.btn_cargar.setEnabled(not loading)
        s.cmb_empresa.setEnabled(not loading)
        s.txt_search.setEnabled(not loading and self._df is not None)

    def _limpiar_vista(self):
        self._df = None
        self._df_detalle = None
        self._columnas = []
        self._etiquetas = []
        self._sort_column = None
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.table.setModel(None)
        self.table.setVisible(False)
        self.lbl_placeholder.setVisible(True)
        s = self.sidebar
        s.txt_search.clear()
        s.txt_search.setEnabled(False)
        s.cmb_filtro_empresa.setCurrentIndex(0)
        s.cmb_filtro_empresa.setEnabled(False)
        s.cmb_col.clear()
        s.cmb_col.addItem("Todas las columnas")
        s.cmb_col.setEnabled(False)
        if hasattr(s, "cmb_periodo"):
            s.cmb_periodo.blockSignals(True)
            s.cmb_periodo.clear()
            s.cmb_periodo.addItem("Acumulado")
            s.cmb_periodo.setEnabled(False)
            s.cmb_periodo.blockSignals(False)
        s.lbl_resultados.setText("")
        self.lbl_total.setText("Sin base cargada")
        if hasattr(s, "tbl_tareas"):
            s.tbl_tareas.setRowCount(0)
        self.table.horizontalHeader().setSortIndicatorShown(False)

        QTimer.singleShot(0, self._ajustar_splitter_inicial)

    def _cargar_gestiones(self):
        path = self.sidebar.txt_gest_excel.text().strip()
        if not path:
            QMessageBox.information(
                self,
                "Selecciona un archivo primero",
                "  Debes seleccionar un archivo Excel de gestiones antes de cargarlo.\n\n"
                "Pulsa el botn Seleccionar para elegir el archivo.\n\n"
                "El archivo debe contener hojas llamadas 'SMS', 'Email' y/o 'Carta'.",
            )
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Archivo no vlido", "Selecciona un archivo Excel vlido de gestiones.")
            return
        s = self.sidebar
        s.btn_cargar_gest.setEnabled(False)
        s.progress_gest.setVisible(True)
        s.progress_gest.setValue(0)
        s.btn_cargar_gest.setToolTip("Cargando gestiones")
        self._gest_worker = CargaGestionesWorker(CargaGestionesParams(excel_path=path))
        self._gest_worker.progress.connect(self._on_gest_progress)
        self._gest_worker.finished_ok.connect(self._on_gest_loaded)
        self._gest_worker.failed.connect(self._on_gest_error)
        self._gest_worker.start()

    def _on_gest_progress(self, pct: int, msg: str):
        self.sidebar.progress_gest.setValue(pct)
        self.sidebar.btn_cargar_gest.setToolTip(msg)

    def _on_gest_loaded(self, insertados: int, omitidos: int, errores: list):
        s = self.sidebar
        s.progress_gest.setVisible(False)
        s.btn_cargar_gest.setEnabled(True)

        if errores and insertados == 0:
            detalle = "\n".join(f"   {e}" for e in errores)
            s.btn_cargar_gest.setToolTip("  Sin datos cargados. Revisa las hojas del Excel.")
            QMessageBox.warning(
                self,
                "Gestiones no cargadas",
                f"No se encontraron datos para cargar.\n\nDetalles:\n{detalle}\n\n"
                f"El archivo debe tener hojas llamadas 'SMS', 'Email' y/o 'Carta' "
                f"con una columna 'Rut_Afiliado'."
            )
            return

        if errores:
            detalle = "\n".join(f"   {e}" for e in errores)
            aviso = f"\n\n  Advertencias:\n{detalle}"
        else:
            aviso = ""

        if omitidos > 0:
            s.btn_cargar_gest.setToolTip(
                f"  {insertados:,} nuevas gestiones agregadas.\n"
                f"  {omitidos:,} ya existan  omitidas."
            )
        else:
            s.btn_cargar_gest.setToolTip(f"  {insertados:,} gestiones cargadas correctamente.")

        if self._usa_backend_deudores():
            texto = self.sidebar.txt_search.text()
            empresa = self.sidebar.cmb_filtro_empresa.currentText()
            col_idx = self.sidebar.cmb_col.currentIndex()
            periodo = self._periodo_actual()
            self._cargar_desde_backend()
            self._restaurar_filtros_ui(
                texto=texto,
                empresa=empresa,
                col_idx=col_idx,
                periodo=periodo,
            )
            self.datos_actualizados.emit()
        else:
            df_all = cargar_todas()
            if not df_all.empty:
                self._mostrar_dataframe(df_all)
            self.datos_actualizados.emit()

        QMessageBox.information(
            self,
            "Gestiones cargadas",
            f"Carga completada:\n\n"
            f"    Nuevas:   {insertados:,}\n"
            f"     Omitidas: {omitidos:,}\n"
            f"{aviso}\n\n"
            f"Abre el detalle de cualquier deudor para ver las gestiones."
        )

    def _on_gest_error(self, err: str):
        s = self.sidebar
        s.progress_gest.setVisible(False)
        s.btn_cargar_gest.setEnabled(True)
        s.btn_cargar_gest.setToolTip("Error al cargar gestiones ")
        QMessageBox.critical(self, "Error al cargar base de gestiones", err)

    def limpiar_empresa_en_vista(self, empresas: list):
        if not empresas:
            return

        if "_todas_" in empresas:
            self._limpiar_vista()
            return

        if self._df is None or self._df.empty or COLUMNA_EMPRESA not in self._df.columns:
            return

        if self._tiene_restriccion_por_cartera():
            actuales = self._empresas_asignadas_actuales()
            self._empresas_asignadas = [e for e in actuales if e not in empresas]
            if self._sin_carteras_asignadas():
                self._mostrar_sin_carteras_asignadas()
                return

        self._df = self._df[~self._df[COLUMNA_EMPRESA].isin(empresas)].copy()

        if self._df.empty:
            self._limpiar_vista()
            return

        self._mostrar_dataframe(self._df)

    # Redefinicion para soportar carga de gestiones contra backend.
    # Se deja la version local (worker + sqlite) para sesiones sin backend.
    def _cargar_gestiones(self):
        path = self.sidebar.txt_gest_excel.text().strip()
        if not path:
            QMessageBox.information(
                self,
                "Selecciona un archivo primero",
                "Debes seleccionar un archivo Excel de gestiones antes de cargarlo.\n\n"
                "Pulsa el boton 'Seleccionar...' para elegir el archivo.\n\n"
                "El archivo debe contener hojas llamadas 'SMS', 'Email' y/o 'Carta'.",
            )
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Archivo no valido", "Selecciona un archivo Excel valido de gestiones.")
            return

        if self._usa_backend_deudores():
            self._cargar_gestiones_backend(path)
            return

        s = self.sidebar
        s.btn_cargar_gest.setEnabled(False)
        s.progress_gest.setVisible(True)
        s.progress_gest.setValue(0)
        s.btn_cargar_gest.setToolTip("Cargando gestiones...")
        self._gest_worker = CargaGestionesWorker(CargaGestionesParams(excel_path=path))
        self._gest_worker.progress.connect(self._on_gest_progress)
        self._gest_worker.finished_ok.connect(self._on_gest_loaded)
        self._gest_worker.failed.connect(self._on_gest_error)
        self._gest_worker.start()

    def _norm_rut_simple(self, rut: str) -> str:
        return str(rut or "").strip().replace(".", "").replace("-", "").lstrip("0")

    def _cargar_gestiones_backend(self, path: str) -> None:
        s = self.sidebar
        s.btn_cargar_gest.setEnabled(False)
        s.progress_gest.setVisible(True)
        s.progress_gest.setValue(5)
        s.btn_cargar_gest.setToolTip("Leyendo archivo de gestiones...")
        QApplication.processEvents()

        try:
            registros, errores = leer_gestiones_excel(path)
        except Exception as exc:
            self._on_gest_error(str(exc))
            return

        if not registros and errores:
            s.progress_gest.setVisible(False)
            s.btn_cargar_gest.setEnabled(True)
            detalle = "\n".join(f"  - {e}" for e in errores)
            QMessageBox.warning(
                self,
                "Gestiones no cargadas",
                f"No se encontraron datos para cargar.\n\nDetalles:\n{detalle}",
            )
            return

        s.progress_gest.setValue(20)
        s.btn_cargar_gest.setToolTip("Consultando deudores del backend...")
        QApplication.processEvents()

        deudores_backend, err_deudores = backend_list_deudores(self._session, limit=50000)
        if err_deudores:
            self._on_gest_error(err_deudores)
            return

        mapa_deudor_por_rut: dict[str, dict] = {}
        for d in deudores_backend or []:
            rut_key = self._norm_rut_simple(d.get("rut_afiliado", ""))
            if rut_key and rut_key not in mapa_deudor_por_rut:
                mapa_deudor_por_rut[rut_key] = d

        existentes, err_gestiones = backend_list_all_gestiones(self._session)
        if err_gestiones:
            self._on_gest_error(err_gestiones)
            return

        claves_existentes: set[tuple[str, str, str, str, str, str]] = set()
        for g in existentes or []:
            claves_existentes.add(
                (
                    self._norm_rut_simple(g.get("rut_afiliado", "")),
                    str(g.get("tipo_gestion", "")).strip(),
                    str(g.get("estado", "")).strip(),
                    str(g.get("observacion", "")).strip(),
                    str(g.get("origen", "")).strip(),
                    str(g.get("fecha_gestion", "")).strip(),
                )
            )

        total = len(registros)
        insertados = 0
        omitidos = 0
        errores_backend: list[str] = list(errores)

        for idx, row in enumerate(registros, start=1):
            rut_raw = str(row.get("rut", "")).strip()
            rut_key = self._norm_rut_simple(rut_raw)
            if not rut_key:
                continue

            deudor = mapa_deudor_por_rut.get(rut_key)
            if not deudor:
                omitidos += 1
                continue

            clave = (
                rut_key,
                str(row.get("tipo_gestion", "")).strip(),
                str(row.get("estado", "")).strip(),
                str(row.get("observacion", "")).strip(),
                str(row.get("origen", "")).strip(),
                str(row.get("fecha_gestion", "")).strip(),
            )
            if clave in claves_existentes:
                omitidos += 1
                continue

            empresa = str(deudor.get("empresa", "")).strip()
            nombre = str(row.get("nombre_afiliado", "")).strip() or str(deudor.get("nombre_afiliado", "")).strip()

            _, err_crear = backend_create_gestion(
                self._session,
                rut=rut_raw,
                empresa=empresa,
                nombre_afiliado=nombre,
                tipo_gestion=str(row.get("tipo_gestion", "")).strip(),
                estado=str(row.get("estado", "")).strip(),
                fecha_gestion=str(row.get("fecha_gestion", "")).strip(),
                observacion=str(row.get("observacion", "")).strip(),
                origen=str(row.get("origen", "")).strip() or "excel",
            )
            if err_crear:
                errores_backend.append(f"RUT {rut_raw}: {err_crear}")
                continue

            claves_existentes.add(clave)
            insertados += 1

            if idx % 25 == 0 or idx == total:
                pct = 20 + int((idx / max(total, 1)) * 75)
                s.progress_gest.setValue(min(pct, 95))
                s.btn_cargar_gest.setToolTip(f"Cargando gestiones... {idx}/{total}")
                QApplication.processEvents()

        s.progress_gest.setValue(100)
        QApplication.processEvents()
        self._on_gest_loaded(insertados, omitidos, errores_backend)
