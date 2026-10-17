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
from datetime import date, datetime
from numbers import Number

from auth.auth_service import backend_list_email_templates
from core.paths import get_data_dir
from core.text_utils import fix_mojibake_text

# ────────────────────────────────────────────────────────────────
#  Variables disponibles (se muestran como ayuda en el editor)
# ────────────────────────────────────────────────────────────────
VARIABLES_DISPONIBLES = {
    "{nombre}":          "Nombre completo del deudor",
    "{rut}":             "RUT del deudor",
    "{saldo}":           "Saldo actual pendiente ($)",
    "{copago}":          "Monto copago original ($)",
    "{total_pagos}":     "Total de pagos realizados ($)",
    "{empresa}":         "Compañía (Colmena o Cruz Blanca)",
    "{nro_expediente}":  "Número de expediente (si aplica)",
    "{ultima_emision}":  "Fecha última emisión",
    "{primera_emision}": "Fecha primera emisión",
    "{detalle_deudas}":  "Detalle individualizado de las deudas de Colmena o Cruz Blanca",
}

VARIABLES_PERMITIDAS = frozenset(token[1:-1] for token in VARIABLES_DISPONIBLES)

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


def variables_no_soportadas(plantilla: dict) -> list[str]:
    texto = f"{plantilla.get('asunto', '')}\n{plantilla.get('cuerpo', '')}"
    encontradas = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", texto))
    return [f"{{{nombre}}}" for nombre in sorted(encontradas - VARIABLES_PERMITIDAS)]


def _fmt_monto(val: object) -> str:
    """Formatea número como $ 1.112.838"""
    try:
        if isinstance(val, Number) and not isinstance(val, bool):
            return f"{int(round(float(val))):,}".replace(",", ".")
        txt = str(val).strip()
        if not txt or txt in ("—", "â€”", "nan", "None"):
            return "—"

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


def _fmt_fecha(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%d/%m/%Y")
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "—", "-"}:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return text


def _first_value(row: dict, *keys: str):
    for key in keys:
        value = row.get(key, "")
        if str(value or "").strip().lower() not in {"", "nan", "none", "n/a", "—", "-"}:
            return value
    return ""


def formatear_detalle_deudas(deudas: list[dict] | tuple[dict, ...] | None) -> str:
    bloques: list[str] = []
    campos = (
        ("ID / expediente", ("ID_Deuda", "id_deuda", "Nro_Expediente", "N° Expediente", "No Licencia", "_expediente_pago"), False),
        ("Fecha de emisión", ("Fecha_Emision", "fecha_emision", "Fecha Emisión"), False),
        ("Fecha de vencimiento", ("Fecha_Vencimiento", "fecha_vencimiento", "Fecha Vencimiento"), False),
        ("Fecha de prestación", ("Fecha_Prestacion", "fecha_prestacion", "Fecha Prestación"), False),
        ("Fecha de prestación 2", ("Fecha_Prestacion2", "fecha_prestacion2", "Fecha Prestación 2"), False),
        ("Prestador", ("Prestador", "prestador"), False),
        ("Monto total", ("Monto_Total", "monto_total", "Mto Pagar"), True),
        ("Monto a cobrar", ("Monto_Cobrar", "monto_cobrar"), True),
        ("Monto facturado", ("Monto_Facturado", "monto_facturado"), True),
        ("Monto liquidado", ("Monto_Liquidado", "monto_liquidado"), True),
        ("Monto pagado parcial", ("Monto_Pagado_Parcial", "monto_pagado_parcial"), True),
        ("Monto condonado", ("Monto_Condonado", "monto_condonado"), True),
        ("Monto gestionado", ("Monto_Gestionado", "monto_gestionado"), True),
        ("Cuota acordada", ("Cuota_Acordada", "cuota_acordada"), True),
        ("Copago", ("Copago", "copago", "Copago ($)"), True),
        ("Total pagos", ("Total_Pagos", "total_pagos", "Pagos", "Total Pagos ($)"), True),
        ("Saldo", ("Saldo_Actual", "saldo_actual", "Saldo Actual", "Saldo Actual ($)"), True),
    )
    for indice, deuda in enumerate(deudas or [], start=1):
        if not isinstance(deuda, dict):
            continue
        lineas = [f"Deuda {indice}"]
        for etiqueta, keys, es_monto in campos:
            value = _first_value(deuda, *keys)
            if value == "":
                continue
            if es_monto:
                try:
                    if float(str(value).replace(".", "").replace(",", ".")) == 0:
                        continue
                except (TypeError, ValueError):
                    pass
                value = f"$ {_fmt_monto(value)}"
            elif etiqueta.startswith("Fecha"):
                value = _fmt_fecha(value)
            lineas.append(f"- {etiqueta}: {value}")
        if len(lineas) > 1:
            bloques.append("\n".join(lineas))
    return "\n\n".join(bloques) if bloques else "—"


def variables_desde_fila(fila: dict) -> dict:
    """
    Construye el dict de variables desde una fila del DataFrame de deudores.
    Las claves del dict deben coincidir con las variables sin llaves.
    """
    def _limpio(val):
        v = fix_mojibake_text(val).strip()
        return v if v not in ("", "nan", "None", "—") else "—"

    return {
        "nombre":          _limpio(fila.get("Nombre_Afiliado", fila.get("Nombre", ""))),
        "rut":             _limpio(fila.get("Rut_Afiliado", fila.get("RUT", ""))),
        "saldo":           _fmt_monto(fila.get("Saldo_Actual", "")),
        "copago":          _fmt_monto(fila.get("Copago", "")),
        "total_pagos":     _fmt_monto(fila.get("Total_Pagos", "")),
        "empresa":         _limpio(fila.get("_empresa", fila.get("Compañía", ""))),
        "nro_expediente":  _limpio(fila.get("Nro_Expediente", fila.get("nro_expediente", ""))),
        "ultima_emision":  _fmt_fecha(fila.get("MAX_Emision_ok", "")) or "—",
        "primera_emision": _fmt_fecha(fila.get("MIN_Emision_ok", "")) or "—",
        "detalle_deudas":  formatear_detalle_deudas(
            fila.get("_detalle_deudas", fila.get("detalle_deudas_items", []))
        ),
    }
