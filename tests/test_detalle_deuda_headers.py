from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import deudores.detalle_dialog as detalle_dialog


@pytest.mark.parametrize("clave_interna", ["N° Expediente", "No Licencia", "No de Licencia"])
def test_folio_cuenta_es_solo_el_encabezado_visible(monkeypatch, clave_interna: str):
    columnas = [
        (clave_interna, "campo_interno"),
        ("Nombre Afil", "nombre_afil"),
    ]
    monkeypatch.setattr(detalle_dialog, "COLUMNAS_DETALLE_DEUDA", columnas)
    fila = {
        clave_interna: "FOLIO-123",
        "Nombre Afil": "Persona de prueba",
    }

    modelo = detalle_dialog._DeudaModel([fila])

    assert modelo.headerData(
        0,
        Qt.Orientation.Horizontal,
        Qt.ItemDataRole.DisplayRole,
    ) == "Folio cuenta"
    assert modelo.headerData(
        1,
        Qt.Orientation.Horizontal,
        Qt.ItemDataRole.DisplayRole,
    ) == "Nombre Afil"
    assert modelo.item(0, 0).text() == "FOLIO-123"
    assert "Folio cuenta" not in fila


def test_datos_cliente_muestran_estado_y_asignado_a():
    dialog = detalle_dialog._CorreoDeudorMixin()
    dialog._info_cliente = {"RUT": "12.345.678-9", "Nombre": "Persona Prueba"}
    dialog._fila_resumen = {
        "Estado_deudor": "Contactado",
        "Ejecutiva_responsable": "Supervisora Prueba",
    }
    dialog._rut = "12345678"

    dialog._aplicar_fallbacks_info_cliente()

    assert dialog._info_cliente["Estado del deudor"] == "Contactado"
    assert dialog._info_cliente["Asignado a"] == "Supervisora Prueba"


def test_datos_cliente_usan_valores_por_defecto_sin_asignacion():
    dialog = detalle_dialog._CorreoDeudorMixin()
    dialog._info_cliente = {"Nombre": "Persona Prueba"}
    dialog._fila_resumen = {}
    dialog._rut = "12345678"

    dialog._aplicar_fallbacks_info_cliente()

    assert dialog._info_cliente["Estado del deudor"] == "Sin Gestión"
    assert dialog._info_cliente["Asignado a"] == "Sin responsable"


def test_detalle_deudor_conserva_alturas_y_scrolls_independientes(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(detalle_dialog, "cargar_plantillas", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(detalle_dialog._GestionWidget, "_cargar", lambda _self: None)
    monkeypatch.setattr(
        detalle_dialog.DetalleDeudorDialog,
        "_refrescar_selector_trabajador_individual",
        lambda _self: None,
    )
    monkeypatch.setattr(
        detalle_dialog.DetalleDeudorDialog,
        "_on_cambio_tipo_envio_detalle",
        lambda _self: None,
    )
    monkeypatch.setattr(
        detalle_dialog.DetalleDeudorDialog,
        "_actualizar_permisos_cartera",
        lambda _self: None,
    )

    detalle = pd.DataFrame([
        {
            "Rut_Afiliado": "12345678",
            "Dv": "5",
            "_RUT_COMPLETO": "12345678-5",
            "Nombre_Afiliado": "Persona de prueba",
            "Nro_Expediente": "EXP-001",
            "Copago": 100000,
            "Total_Pagos": 0,
            "Saldo_Actual": 100000,
            "_empresa": "Cartera de prueba",
        }
    ])
    dialog = detalle_dialog.DetalleDeudorDialog(
        detalle,
        "12345678",
        fila_resumen={"_empresa": "Cartera de prueba"},
    )
    dialog.resize(900, 520)
    dialog.show()
    app.processEvents()

    assert dialog._module_scroll.widget() is dialog._module_content
    assert dialog._debt_scroll.minimumHeight() >= dialog._MIN_DEUDA_SECTION_HEIGHT
    assert dialog._gestion_scroll.minimumHeight() >= dialog._MIN_GESTION_SECTION_HEIGHT
    assert dialog._main_splitter.minimumHeight() >= (
        dialog._MIN_DEUDA_SECTION_HEIGHT
        + dialog._MIN_GESTION_SECTION_HEIGHT
        + dialog._main_splitter.handleWidth()
    )
    assert dialog.tbl_deuda.minimumHeight() >= 170
    assert dialog._module_scroll.verticalScrollBar().maximum() > 0

    dialog.close()
