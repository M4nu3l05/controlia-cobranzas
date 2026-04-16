"""
Modelos de datos para la conciliación
"""

from dataclasses import dataclass, field


@dataclass
class ConciliacionParams:
    empresa: str
    mes_anterior_path: str
    mes_actual_path: str
    salida_path: str
    sheet_name: str = "DETALLE"
    id_columns: list[str] = field(default_factory=lambda: ["RUT", "DV"])
    required_columns: list[str] = field(default_factory=lambda: ["RUT", "DV"])
    export_both: bool = False
