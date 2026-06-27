from __future__ import annotations


_TEXT_REPLACEMENTS = {
    "Gesti?n": "Gestión",
    "gesti?n": "gestión",
    "Derivaci?n": "Derivación",
    "derivaci?n": "derivación",
    "Notificaci?n": "Notificación",
    "notificaci?n": "notificación",
    "recuperaci?n": "recuperación",
    "Recuperaci?n": "Recuperación",
    "contrase?a": "contraseña",
    "Contrase?a": "Contraseña",
    "Tel?fono": "Teléfono",
    "tel?fono": "teléfono",
    "M?vil": "Móvil",
    "m?vil": "móvil",
    "N? Licencia": "N° Licencia",
    "N?": "N°",
    "gestin": "gestión",
    "Gestin": "Gestión",
    "â€¦": "…",
    "â€”": "—",
    "â€“": "–",
    "âœ•": "✕",
    "âœ…": "✅",
    "ðŸ“¥": "📥",
    "ðŸ“‹": "📋",
    "ðŸ”": "🔍",
    "ðŸ”„": "🔄",
}


def fix_mojibake_text(value: object) -> str:
    """Repara textos frecuentes que llegan mal codificados desde Excel o BD."""
    txt = str(value or "")
    if not txt:
        return ""

    for _ in range(2):
        if not any(marker in txt for marker in ("Ã", "Â", "â", "ð", "�")):
            break
        try:
            fixed = txt.encode("latin1").decode("utf-8")
        except Exception:
            break
        if fixed == txt:
            break
        txt = fixed

    for wrong, right in _TEXT_REPLACEMENTS.items():
        txt = txt.replace(wrong, right)

    return txt
