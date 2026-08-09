# ================================================================
#  core/secret_store.py
#  Cifrado en reposo de datos sensibles guardados en el equipo.
#  Usa DPAPI de Windows: la clave la administra el sistema operativo
#  y queda atada a la cuenta del usuario, sin dependencias externas.
# ================================================================

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# Prefijos de formato. Permiten leer registros antiguos sin cifrar y
# reconocer en que modo quedo guardado cada valor.
_PREFIJO_DPAPI = b"DPAPI1:"
_PREFIJO_PLANO = b"PLAIN1:"

# Entropia adicional: ata el dato cifrado a esta aplicacion, de modo que
# otro proceso del mismo usuario no pueda descifrarlo por accidente.
_ENTROPIA = b"ControliaCobranzas.outbox.v1"

_ADVERTENCIA_EMITIDA = False


def _es_windows() -> bool:
    return sys.platform == "win32"


if _es_windows():  # pragma: no cover - depende del sistema operativo
    import ctypes
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    _crypt32 = ctypes.WinDLL("crypt32.dll")
    _kernel32 = ctypes.WinDLL("kernel32.dll")
    _CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def _a_blob(data: bytes):
        buffer = ctypes.create_string_buffer(data, len(data))
        blob = _DataBlob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)),
        )
        # Se devuelve el buffer para que quien llame lo mantenga vivo:
        # si lo recolecta el GC, pbData apuntaria a memoria liberada.
        return blob, buffer

    def _desde_blob(blob) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(blob.pbData)

    def _proteger_dpapi(raw: bytes) -> bytes:
        entrada, _buf_in = _a_blob(raw)
        entropia, _buf_ent = _a_blob(_ENTROPIA)
        salida = _DataBlob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(entrada),
            None,
            ctypes.byref(entropia),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(salida),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptProtectData fallo")
        return _desde_blob(salida)

    def _desproteger_dpapi(raw: bytes) -> bytes:
        entrada, _buf_in = _a_blob(raw)
        entropia, _buf_ent = _a_blob(_ENTROPIA)
        salida = _DataBlob()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(entrada),
            None,
            ctypes.byref(entropia),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(salida),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptUnprotectData fallo")
        return _desde_blob(salida)


def cifrado_disponible() -> bool:
    """Indica si el equipo puede cifrar de verdad los datos en reposo."""
    if not _es_windows():
        return False
    try:
        return _desproteger_dpapi(_proteger_dpapi(b"probe")) == b"probe"
    except OSError:
        return False


def _advertir_sin_cifrado() -> None:
    global _ADVERTENCIA_EMITIDA
    if not _ADVERTENCIA_EMITIDA:
        logger.warning(
            "Cifrado en reposo no disponible en esta plataforma: "
            "los datos locales quedaran en texto plano."
        )
        _ADVERTENCIA_EMITIDA = True


def proteger(texto: str) -> bytes:
    """Cifra un texto para guardarlo en disco."""
    raw = str(texto or "").encode("utf-8")
    if _es_windows():
        try:
            return _PREFIJO_DPAPI + _proteger_dpapi(raw)
        except OSError:
            logger.exception("No se pudo cifrar con DPAPI; se guarda sin cifrar")
    else:
        _advertir_sin_cifrado()
    return _PREFIJO_PLANO + raw


def desproteger(dato: bytes | None) -> str:
    """Recupera un texto guardado con `proteger`.

    Acepta valores antiguos sin prefijo para no perder registros escritos
    por versiones previas.
    """
    if not dato:
        return ""
    if isinstance(dato, str):
        return dato

    if dato.startswith(_PREFIJO_DPAPI):
        cuerpo = dato[len(_PREFIJO_DPAPI):]
        try:
            return _desproteger_dpapi(cuerpo).decode("utf-8", errors="replace")
        except (OSError, NameError):
            logger.exception("No se pudo descifrar un dato local")
            return ""
    if dato.startswith(_PREFIJO_PLANO):
        return dato[len(_PREFIJO_PLANO):].decode("utf-8", errors="replace")

    # Registro anterior a la introduccion del cifrado.
    return dato.decode("utf-8", errors="replace")
