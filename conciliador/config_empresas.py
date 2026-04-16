from __future__ import annotations

CONFIG_CONCILIACION = {
    "Colmena": {
        "sheet_name": "DETALLE",
        "id_columns": ["RUT", "DV"],
        "required_columns": ["RUT", "DV"],
    },
    "Consalud": {
        "sheet_name": "DETALLE",
        "id_columns": ["RUT", "DV"],
        "required_columns": ["RUT", "DV"],
    },
    "Cruz Blanca": {
        "sheet_name": "DETALLE",
        "id_columns": ["RUT", "DV"],
        "required_columns": ["RUT", "DV"],
    },
    "Cart-56": {
        "sheet_name": "DETALLE",
        "id_columns": ["RUT", "DV"],
        "required_columns": ["RUT", "DV"],
    },
}


def obtener_config_empresa(empresa: str) -> dict:
    return CONFIG_CONCILIACION.get(empresa, CONFIG_CONCILIACION["Colmena"]).copy()