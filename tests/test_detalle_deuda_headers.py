from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

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


def test_datos_cliente_muestran_estado_y_supervisor_responsable():
    dialog = detalle_dialog._CorreoDeudorMixin()
    dialog._info_cliente = {"RUT": "12.345.678-9", "Nombre": "Persona Prueba"}
    dialog._fila_resumen = {
        "Estado_deudor": "Contactado",
        "Ejecutiva_responsable": "Supervisora Prueba",
    }
    dialog._rut = "12345678"

    dialog._aplicar_fallbacks_info_cliente()

    assert dialog._info_cliente["Estado del deudor"] == "Contactado"
    assert dialog._info_cliente["Supervisor responsable"] == "Supervisora Prueba"


def test_datos_cliente_usan_valores_por_defecto_sin_asignacion():
    dialog = detalle_dialog._CorreoDeudorMixin()
    dialog._info_cliente = {"Nombre": "Persona Prueba"}
    dialog._fila_resumen = {}
    dialog._rut = "12345678"

    dialog._aplicar_fallbacks_info_cliente()

    assert dialog._info_cliente["Estado del deudor"] == "Sin Gestión"
    assert dialog._info_cliente["Supervisor responsable"] == "Sin responsable"
