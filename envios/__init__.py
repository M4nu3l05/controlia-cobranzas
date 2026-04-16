from .config import SMTP_PRESETS, cargar_config, config_completa, guardar_config
from .plantillas import VARIABLES_DISPONIBLES, cargar_plantillas, guardar_plantillas, renderizar
from .worker import EnvioParams, EnvioWorker, probar_conexion

try:
    from .view import EnviosWidget
except Exception:  # pragma: no cover
    EnviosWidget = None

__all__ = [
    "EnviosWidget",
    "guardar_config", "cargar_config", "config_completa", "SMTP_PRESETS",
    "cargar_plantillas", "guardar_plantillas", "renderizar", "VARIABLES_DISPONIBLES",
    "EnvioWorker", "EnvioParams", "probar_conexion",
]
