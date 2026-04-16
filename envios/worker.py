# ================================================================
#  envios/worker.py
#  QThread que envía los correos en segundo plano.
#  Emite progreso, resultado por correo y resumen final.
# ================================================================

import smtplib
import traceback
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass

import pandas as pd
try:
    from PyQt6.QtCore import QThread, pyqtSignal
except Exception:  # pragma: no cover
    class _DummySignal:
        def __init__(self, *args, **kwargs):
            pass
        def emit(self, *args, **kwargs):
            pass
        def connect(self, *args, **kwargs):
            pass

    def pyqtSignal(*args, **kwargs):
        return _DummySignal()

    class QThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            self.run()
        def run(self):
            pass

from .plantillas import renderizar, variables_desde_fila


# Columnas de email a buscar (en orden de prioridad)
COLUMNAS_EMAIL: list[str] = [
    "BN",              # Columna del Excel original (email del afiliado)
    "mail_afiliado",  # Principal (normalizado)
    "email",
    "correo",
]


def obtener_columna_email(df: pd.DataFrame) -> str:
    """Devuelve el nombre de la columna email; si no existe, lanza un error claro."""
    cols_lower = {str(col).lower(): col for col in df.columns}

    for col_buscar in COLUMNAS_EMAIL:
        col_lower = col_buscar.lower()
        if col_lower in cols_lower:
            return cols_lower[col_lower]

    for col_original in df.columns:
        col_lower = str(col_original).lower()
        if any(token in col_lower for token in ("mail", "email", "correo")):
            return col_original

    disponibles = ", ".join(map(str, df.columns.tolist()))
    raise ValueError(
        "No se encontró una columna de email válida. "
        f"Columnas disponibles: {disponibles}"
    )


@dataclass
class EnvioParams:
    """Todo lo necesario para ejecutar un lote de envíos."""
    # SMTP
    host:             str
    port:             int
    tls:              bool
    usuario:          str
    password:         str
    nombre_remitente: str

    # Plantilla seleccionada
    plantilla: dict

    # DataFrame con los destinatarios
    df_destinatarios: pd.DataFrame

    # Columna de email a usar (se determina automáticamente si no se provee)
    col_email: str = ""

    # Pausa entre envíos (segundos) para no saturar el servidor
    pausa_segundos: float = 1.5


@dataclass
class ResultadoEnvio:
    email:   str
    nombre:  str
    ok:      bool
    mensaje: str


class EnvioWorker(QThread):
    """Envía correos uno a uno en un hilo separado."""

    # (enviados, total, email_actual, nombre_actual)
    progreso     = pyqtSignal(int, int, str, str)
    # resultado individual
    resultado    = pyqtSignal(object)
    # resumen final (ok, fallidos, omitidos)
    terminado    = pyqtSignal(int, int, int)
    # error fatal antes de iniciar
    error_fatal  = pyqtSignal(str)

    def __init__(self, params: EnvioParams, parent=None):
        super().__init__(parent)
        self.params = params
        self._cancelar = False

    def cancelar(self):
        self._cancelar = True

    def run(self):
        p = self.params
        ok_count = fallidos = omitidos = 0
        total = len(p.df_destinatarios)

        # Determinar columna de email automáticamente si no se especificó
        col_email = p.col_email
        if not col_email:
            col_email = obtener_columna_email(p.df_destinatarios)
            if not col_email:
                self.error_fatal.emit(
                    "❌ No se encontró columna de email en los destinatarios.\n\n"
                    "El DataFrame debe contener una de estas columnas: "
                    "mail_afiliado, BN, email, Email, correo, Correo"
                )
                return

        # ── 1. Conectar al servidor ──────────────────────────
        try:
            if p.tls:
                servidor = smtplib.SMTP(p.host, p.port, timeout=15)
                servidor.ehlo()
                servidor.starttls()
                servidor.ehlo()
            else:
                servidor = smtplib.SMTP_SSL(p.host, p.port, timeout=15)
            servidor.login(p.usuario, p.password)
        except smtplib.SMTPAuthenticationError:
            self.error_fatal.emit(
                "❌ Error de autenticación.\n\n"
                "Verifica usuario y contraseña.\n"
                "Para Outlook: asegúrate de haber activado SMTP AUTH en "
                "outlook.com → Configuración → Correo → Sincronización → "
                "Opciones POP e IMAP."
            )
            return
        except Exception as e:
            self.error_fatal.emit(
                f"❌ No se pudo conectar al servidor SMTP.\n\n"
                f"{type(e).__name__}: {e}\n\n"
                f"Verifica host ({p.host}), puerto ({p.port}) y conexión a internet."
            )
            return

        # ── 2. Enviar uno a uno ──────────────────────────────
        try:
            for i, (_, fila) in enumerate(p.df_destinatarios.iterrows()):
                if self._cancelar:
                    break

                email = str(fila.get(col_email, "")).strip()
                nombre = str(fila.get("Nombre_Afiliado", fila.get("Nombre", "Deudor"))).strip()

                self.progreso.emit(i, total, email, nombre)

                # Omitir emails vacíos o inválidos
                if not email or email in ("—", "N", "nan", "None") or "@" not in email:
                    omitidos += 1
                    self.resultado.emit(ResultadoEnvio(
                        email=email or "(vacío)", nombre=nombre,
                        ok=False, mensaje="Omitido — email inválido o ausente"
                    ))
                    continue

                # Renderizar plantilla con los datos de esta fila
                variables = variables_desde_fila(dict(fila))
                asunto, cuerpo = renderizar(p.plantilla, variables)

                # Construir mensaje
                msg = MIMEMultipart("alternative")
                msg["Subject"] = asunto
                msg["From"]    = f"{p.nombre_remitente} <{p.usuario}>"
                msg["To"]      = email

                # Parte texto plano
                msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
                # Parte HTML (convierte saltos de línea)
                html_body = cuerpo.replace("\n", "<br>")
                html = f"""
                <html><body style="font-family: Segoe UI, sans-serif; font-size:14px;
                       color:#0f172a; line-height:1.6; max-width:600px; margin:auto;
                       padding:24px;">
                  <p>{html_body}</p>
                  <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
                  <p style="color:#94a3b8; font-size:11px;">
                    Este correo fue generado automáticamente por Controlia Cobranzas.
                  </p>
                </body></html>"""
                msg.attach(MIMEText(html, "html", "utf-8"))

                # Enviar
                try:
                    servidor.sendmail(p.usuario, email, msg.as_string())
                    ok_count += 1
                    self.resultado.emit(ResultadoEnvio(
                        email=email, nombre=nombre, ok=True,
                        mensaje=f"✅ Enviado: {asunto[:60]}"
                    ))
                except Exception as e_send:
                    fallidos += 1
                    self.resultado.emit(ResultadoEnvio(
                        email=email, nombre=nombre, ok=False,
                        mensaje=f"❌ Error: {e_send}"
                    ))

                # Pausa anti-spam
                if i < total - 1 and not self._cancelar:
                    time.sleep(p.pausa_segundos)

        finally:
            try:
                servidor.quit()
            except Exception:
                pass

        self.progreso.emit(total, total, "", "")
        self.terminado.emit(ok_count, fallidos, omitidos)


# ── Función auxiliar: probar conexión ──────────────────────────

def probar_conexion(host: str, port: int, tls: bool,
                    usuario: str, password: str) -> tuple[bool, str]:
    """
    Intenta conectar y autenticar sin enviar nada.
    Devuelve (éxito, mensaje).
    """
    try:
        if tls:
            s = smtplib.SMTP(host, port, timeout=10)
            s.ehlo()
            s.starttls()
            s.ehlo()
        else:
            s = smtplib.SMTP_SSL(host, port, timeout=10)
        s.login(usuario, password)
        s.quit()
        return True, "✅ Conexión exitosa. Credenciales correctas."
    except smtplib.SMTPAuthenticationError:
        return False, (
            "❌ Error de autenticación.\n"
            "Usuario o contraseña incorrectos.\n"
            "Para Outlook: activa SMTP AUTH en la configuración de tu cuenta."
        )
    except Exception as e:
        return False, f"❌ {type(e).__name__}: {e}"

