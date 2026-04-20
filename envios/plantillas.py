# ================================================================
#  envios/plantillas.py
#
#  MOTOR DE PLANTILLAS DE CORREO
#  ──────────────────────────────
#  Las plantillas usan variables entre llaves: {nombre}, {saldo}
#  Se guardan en data/plantillas.json y son editables desde la UI.
# ================================================================

import os
import json
import re

from auth.auth_service import backend_list_email_templates
from core.paths import get_data_dir

# ────────────────────────────────────────────────────────────────
#  Variables disponibles (se muestran como ayuda en el editor)
# ────────────────────────────────────────────────────────────────
VARIABLES_DISPONIBLES = {
    "{nombre}":          "Nombre completo del deudor",
    "{rut}":             "RUT del deudor",
    "{saldo}":           "Saldo actual pendiente ($)",
    "{copago}":          "Monto copago original ($)",
    "{total_pagos}":     "Total de pagos realizados ($)",
    "{empresa}":         "Compañía (Colmena, Consalud, Cruz Blanca)",
    "{nro_expediente}":  "Número de expediente (si aplica)",
    "{ultima_emision}":  "Fecha última emisión",
    "{primera_emision}": "Fecha primera emisión",
}

# ────────────────────────────────────────────────────────────────
#  Plantillas predeterminadas
# ────────────────────────────────────────────────────────────────
PLANTILLAS_DEFAULT = [
    {
        "nombre": "Recordatorio de deuda",
        "asunto": "Recordatorio de saldo pendiente — {empresa}",
        "cuerpo": (
            "Estimado/a {nombre},\n\n"
            "Le contactamos para recordarle que registra un saldo pendiente de "
            "${saldo} en {empresa}.\n\n"
            "Le solicitamos regularizar su situación a la brevedad. Si ya realizó "
            "el pago, por favor ignore este mensaje.\n\n"
            "Atentamente,\n"
            "Equipo de Controlia Cobranzas"
        ),
    },
    {
        "nombre": "Aviso de mora",
        "asunto": "Aviso de cuenta en mora — Expediente {nro_expediente}",
        "cuerpo": (
            "Estimado/a {nombre},\n\n"
            "Su cuenta con expediente N° {nro_expediente} presenta un saldo "
            "vencido de ${saldo}.\n\n"
            "Para evitar mayores consecuencias, le invitamos a ponerse en "
            "contacto con nosotros para acordar un plan de pago.\n\n"
            "Atentamente,\n"
            "Equipo de Controlia Cobranzas"
        ),
    },
    {
        "nombre": "Primer contacto",
        "asunto": "Información sobre su cuenta — {empresa}",
        "cuerpo": (
            "Estimado/a {nombre},\n\n"
            "Nos comunicamos en representación de {empresa} para informarle "
            "que hemos recibido su caso para gestión de cobranza.\n\n"
            "Monto copago: ${copago}\n"
            "Pagos registrados: ${total_pagos}\n"
            "Saldo pendiente: ${saldo}\n\n"
            "Para consultas, responda este correo o contáctenos directamente.\n\n"
            "Atentamente,\n"
            "Equipo de Controlia Cobranzas"
        ),
    },
]

_PLANTILLAS_FILE = None


def _plantillas_path() -> str:
    global _PLANTILLAS_FILE
    if _PLANTILLAS_FILE:
        return _PLANTILLAS_FILE
    data_dir = get_data_dir()
    return os.path.join(data_dir, "plantillas.json")


def _normalizar_backend_templates(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        out.append(
            {
                "_id": int(row.get("id", 0) or 0),
                "nombre": str(row.get("nombre", "")).strip(),
                "asunto": str(row.get("asunto", "")).strip(),
                "cuerpo": str(row.get("cuerpo", "")).strip(),
            }
        )
    return out


def cargar_plantillas(session=None) -> list[dict]:
    """Devuelve plantillas. En sesión backend usa DB central; si falla, usa fallback local/default."""
    if session is not None and getattr(session, "auth_source", "") == "backend":
        rows, err = backend_list_email_templates(session)
        if not err and rows:
            return _normalizar_backend_templates(rows)

    # Fallback local/default para modo no-backend o contingencia.
    path = _plantillas_path()
    if not os.path.exists(path):
        return [dict(p) for p in PLANTILLAS_DEFAULT]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if data else [dict(p) for p in PLANTILLAS_DEFAULT]
    except Exception:
        return [dict(p) for p in PLANTILLAS_DEFAULT]


def guardar_plantillas(plantillas: list[dict]) -> None:
    with open(_plantillas_path(), "w", encoding="utf-8") as f:
        json.dump(plantillas, f, indent=2, ensure_ascii=False)


def renderizar(plantilla: dict, variables: dict) -> tuple[str, str]:
    """
    Aplica las variables al asunto y cuerpo de la plantilla.
    Devuelve (asunto_renderizado, cuerpo_renderizado).
    Variables no encontradas se dejan como {variable}.
    """
    asunto = plantilla.get("asunto", "")
    cuerpo = plantilla.get("cuerpo", "")

    for key, val in variables.items():
        token = "{" + key + "}"
        asunto = asunto.replace(token, str(val))
        cuerpo = cuerpo.replace(token, str(val))

    return asunto, cuerpo


def _fmt_monto(val: str) -> str:
    """Formatea número como $ 1.112.838"""
    try:
        txt = str(val).strip()
        if not txt or txt in ("â€”", "nan", "None"):
            return "â€”"

        txt = txt.replace("$", "").replace(" ", "")

        if "," in txt and "." not in txt:
            partes = txt.split(",")
            if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
                txt = "".join(partes)
            else:
                txt = txt.replace(".", "").replace(",", ".")
        elif "," in txt and "." in txt:
            txt = txt.replace(".", "").replace(",", ".")
        elif "." in txt:
            partes = txt.split(".")
            if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
                txt = "".join(partes)

        n = int(round(float(txt)))
        return f"{n:,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(val).strip() if val else "—"


def variables_desde_fila(fila: dict) -> dict:
    """
    Construye el dict de variables desde una fila del DataFrame de deudores.
    Las claves del dict deben coincidir con las variables sin llaves.
    """
    def _limpio(val):
        v = str(val).strip()
        return v if v not in ("", "nan", "None", "—") else "—"

    return {
        "nombre":          _limpio(fila.get("Nombre_Afiliado", fila.get("Nombre", ""))),
        "rut":             _limpio(fila.get("Rut_Afiliado", fila.get("RUT", ""))),
        "saldo":           _fmt_monto(fila.get("Saldo_Actual", "")),
        "copago":          _fmt_monto(fila.get("Copago", "")),
        "total_pagos":     _fmt_monto(fila.get("Total_Pagos", "")),
        "empresa":         _limpio(fila.get("_empresa", fila.get("Compañía", ""))),
        "nro_expediente":  _limpio(fila.get("Nro_Expediente", "")),
        "ultima_emision":  _limpio(fila.get("MAX_Emision_ok", "")),
        "primera_emision": _limpio(fila.get("MIN_Emision_ok", "")),
    }
