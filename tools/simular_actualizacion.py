"""Simulador del botón "Actualizar" sin publicar nada ni tocar la instalación real.

Levanta un "GitHub Releases" falso en 127.0.0.1, abre la app con una versión
ficticia y reemplaza el instalador por uno simulado que, al cerrarse la app, la
vuelve a abrir como si ya estuviera actualizada.

Por defecto usa un entorno aislado: APPDATA temporal, usuario ficticio local y
backend apuntando a un puerto cerrado, así que no toca datos reales.

Uso (desde la carpeta del proyecto):

    .venv\\Scripts\\python.exe tools\\simular_actualizacion.py
    .venv\\Scripts\\python.exe tools\\simular_actualizacion.py --escenario hash-malo

Escenarios:
    ok             Hay versión nueva; descarga, verifica e "instala".
    al-dia         La release publicada es la misma versión: no aparece el botón.
    sin-releases   El repositorio no tiene releases (HTTP 404): no aparece el botón.
    sin-red        No hay conexión: no aparece el botón ni errores.
    hash-malo      El SHA256 publicado no coincide: se descarta y se avisa.
    lenta          Descarga lenta, para probar el botón Cancelar.

--auto ejecuta el escenario solo (sin clics) y escribe el resultado en JSON.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
ESCENARIOS = ("ok", "al-dia", "sin-releases", "sin-red", "hash-malo", "lenta")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--escenario", choices=ESCENARIOS, default="ok")
    p.add_argument("--version-actual", default="2.4.15")
    p.add_argument("--version-nueva", default="9.9.9")
    p.add_argument("--con-login", action="store_true", help="Usa el login real en vez del usuario ficticio.")
    p.add_argument("--auto", action="store_true", help="Recorre el escenario sin intervención.")
    p.add_argument("--resultado", help="Archivo JSON donde --auto deja el resultado.")
    p.add_argument("--sandbox", help=argparse.SUPPRESS)
    p.add_argument("--post-instalacion", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--esperar-pid", type=int, help=argparse.SUPPRESS)
    p.add_argument("--setup", help=argparse.SUPPRESS)
    p.add_argument("--args-setup", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def _log(sandbox: Path, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(sandbox / "simulacion.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ── Servidor falso de GitHub Releases ───────────────────────────────────────
class _FakeGitHub:
    def __init__(self, escenario: str, version_actual: str, version_nueva: str):
        self.escenario = escenario
        self.tag = version_actual if escenario == "al-dia" else version_nueva
        self.setup_name = f"ControliaCobranzas_Setup_{self.tag}.exe"
        size = 8 * 1024 * 1024
        self.setup_bytes = (b"SIMULACION-CONTROLIA-" * (size // 21 + 1))[:size]
        digest = hashlib.sha256(self.setup_bytes).hexdigest()
        if escenario == "hash-malo":
            digest = "0" * 64
        self.sums = f"{digest}  {self.setup_name}\n".encode()
        self.requests: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body: bytes, ctype="application/octet-stream"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.requests.append(self.path)
                base = f"http://127.0.0.1:{fake.port}"
                if self.path.endswith("/releases/latest"):
                    if fake.escenario == "sin-releases":
                        return self._send(404, b'{"message":"Not Found"}', "application/json")
                    payload = {
                        "tag_name": f"v{fake.tag}",
                        "draft": False,
                        "prerelease": False,
                        "body": f"Versión simulada {fake.tag}.\n- Cambio ficticio 1\n- Cambio ficticio 2",
                        "assets": [
                            {
                                "name": fake.setup_name,
                                "browser_download_url": f"{base}/assets/{fake.setup_name}",
                                "size": len(fake.setup_bytes),
                            },
                            {
                                "name": "SHA256SUMS.txt",
                                "browser_download_url": f"{base}/assets/SHA256SUMS.txt",
                                "size": len(fake.sums),
                            },
                        ],
                    }
                    return self._send(200, json.dumps(payload).encode(), "application/json")
                if self.path.endswith("/SHA256SUMS.txt"):
                    return self._send(200, fake.sums, "text/plain")
                if self.path.endswith(f"/{fake.setup_name}"):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(fake.setup_bytes)))
                    self.end_headers()
                    step = 64 * 1024
                    try:
                        for i in range(0, len(fake.setup_bytes), step):
                            self.wfile.write(fake.setup_bytes[i : i + step])
                            # Latencia mínima para que la barra de progreso se vea.
                            time.sleep(0.08 if fake.escenario == "lenta" else 0.012)
                    except (ConnectionError, OSError):
                        pass  # El cliente canceló la descarga.
                    return None
                return self._send(404, b"")

        return Handler

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


# ── Instalador simulado ─────────────────────────────────────────────────────
def _wait_pid(pid: int, timeout_s: float = 60) -> bool:
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return True  # Ya terminó.
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout_s * 1000)) == 0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _post_instalacion(args) -> int:
    sandbox = Path(args.sandbox)
    _log(sandbox, f"[instalador simulado] Recibido: {args.setup}")
    _log(sandbox, f"[instalador simulado] Argumentos: {args.args_setup}")
    _log(sandbox, "[instalador simulado] Esperando a que la app se cierre...")
    cerrada = _wait_pid(args.esperar_pid)
    _log(sandbox, f"[instalador simulado] App cerrada: {cerrada}")
    if not cerrada:
        return 1
    time.sleep(1.5)
    _log(sandbox, f"[instalador simulado] 'Instalación' lista. Reabriendo como versión {args.version_actual}")
    cmd = [
        sys.executable, str(SCRIPT),
        "--sandbox", str(sandbox),
        "--escenario", "al-dia",
        "--version-actual", args.version_actual,
    ]
    if args.con_login:
        cmd.append("--con-login")
    if args.auto:
        cmd += ["--auto", "--resultado", args.resultado]
    subprocess.Popen(cmd, cwd=str(ROOT))
    return 0


# ── Modo automático: responde los diálogos solo ─────────────────────────────
class _AutoPilot:
    def __init__(self, win, escenario: str, sandbox: Path, resultado: dict):
        from PyQt6.QtCore import QTimer

        self.win = win
        self.escenario = escenario
        self.sandbox = sandbox
        self.res = resultado
        self.clicked_update = False
        self.started = time.monotonic()
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)

    def tick(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog

        btn =getattr(self.win, "_btn_update", None)
        if btn is not None and btn.isVisible() and not self.clicked_update:
            self.res["boton_texto"] = btn.text()
            self.clicked_update = True
            _log(self.sandbox, f"[auto] Botón visible: {btn.text()!r}. Clic.")
            # El clic abre un diálogo modal: se hace fuera del tick, porque Qt no
            # vuelve a disparar este timer mientras su slot sigue ejecutándose.
            QTimer.singleShot(0, btn.click)
            return

        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                if w.property("_auto_respondido"):
                    return
                w.setProperty("_auto_respondido", True)
                texto = w.text()
                self.res.setdefault("dialogos", []).append(texto)
                _log(self.sandbox, f"[auto] Diálogo: {texto!r}")
                target = next((b for b in w.buttons() if b.text() == "Actualizar ahora"), None)
                QTimer.singleShot(0, target.click if target else w.accept)
                return
            if isinstance(w, QProgressDialog) and w.isVisible():
                self.res["vio_progreso"] = True
                if self.escenario == "lenta" and w.value() >= 10 and not self.res.get("cancelado"):
                    self.res["cancelado"] = True
                    _log(self.sandbox, f"[auto] Progreso en {w.value()}%. Clic en Cancelar.")
                    from PyQt6.QtWidgets import QPushButton

                    # Igual que el usuario: el botón emite canceled(); cancel() no lo hace.
                    boton = next(b for b in w.findChildren(QPushButton) if b.text() == "Cancelar")
                    QTimer.singleShot(0, boton.click)
                return

        elapsed = time.monotonic() - self.started
        check_done = getattr(self.win, "_update_check_worker", None) is not None and not self.win._update_check_worker.isRunning()
        dl = getattr(self.win, "_update_download_worker", None)
        dl_done = dl is None or not dl.isRunning()
        terminal = {
            "al-dia": check_done and elapsed > 7,
            "sin-releases": check_done and elapsed > 7,
            "sin-red": check_done and elapsed > 7,
            "hash-malo": self.clicked_update and dl_done and bool(self.res.get("dialogos")) and len(self.res["dialogos"]) >= 2,
            "lenta": self.res.get("cancelado") and dl_done and elapsed > 1,
        }.get(self.escenario, False)
        if terminal or elapsed > 90:
            self.res["timeout"] = elapsed > 90
            self.res["boton_visible_final"] = bool(btn is not None and btn.isVisible())
            self.res["titulo"] = self.win.windowTitle()
            self.finish()

    def finish(self):
        from PyQt6.QtWidgets import QApplication

        self.timer.stop()
        _log(self.sandbox, f"[auto] Fin del escenario {self.escenario}: {json.dumps(self.res, ensure_ascii=False)}")
        self.res["terminado"] = True
        QApplication.instance().quit()


# ── Arranque de la app simulada ─────────────────────────────────────────────
def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.sandbox:
        sandbox = Path(args.sandbox)
    else:
        sandbox = Path(tempfile.mkdtemp(prefix="controlia_simulacion_"))
    sandbox.mkdir(parents=True, exist_ok=True)

    if args.post_instalacion:
        return _post_instalacion(args)

    if not args.con_login:
        # Aísla datos y backend: nada de lo que pase aquí llega a la base real.
        os.environ["APPDATA"] = str(sandbox / "appdata")
        os.environ["CONTROLIA_BACKEND_URL"] = "http://127.0.0.1:9"
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    # La versión se fija antes de importar el resto para que todos la vean.
    import core.version

    core.version.APP_VERSION = args.version_actual

    from core import updater

    fake = _FakeGitHub(args.escenario, args.version_actual, args.version_nueva)
    fake.start()
    if args.escenario == "sin-red":
        updater.API_URL = "http://127.0.0.1:9/repos/{repo}/releases/latest"
    else:
        updater.API_URL = f"http://127.0.0.1:{fake.port}/repos/{{repo}}/releases/latest"

    updates_dir = sandbox / "descargas"
    updates_dir.mkdir(exist_ok=True)
    updater.get_updates_dir = lambda: updates_dir
    updater.can_self_update = lambda: True

    resultado_path = Path(args.resultado) if args.resultado else sandbox / "resultado.json"
    resultado: dict = {"escenario": args.escenario, "version_actual": args.version_actual}

    def fake_launch(path):
        path = Path(path)
        ok_hash = hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(fake.setup_bytes).hexdigest()
        resultado["instalador_lanzado"] = str(path)
        resultado["instalador_args"] = updater.INSTALLER_ARGS
        resultado["instalador_hash_ok"] = ok_hash
        _log(sandbox, f"[app] launch_installer({path.name}, {updater.INSTALLER_ARGS}) hash_ok={ok_hash}")
        cmd = [
            sys.executable, str(SCRIPT), "--post-instalacion",
            "--sandbox", str(sandbox),
            "--esperar-pid", str(os.getpid()),
            "--setup", str(path),
            "--args-setup", updater.INSTALLER_ARGS,
            "--version-actual", args.version_nueva,
        ]
        if args.con_login:
            cmd.append("--con-login")
        if args.auto:
            cmd += ["--auto", "--resultado", str(resultado_path.with_name(resultado_path.stem + "_post.json"))]
        flags = 0 if args.auto else subprocess.CREATE_NEW_CONSOLE
        subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags)

    updater.launch_installer = fake_launch

    from PyQt6.QtWidgets import QApplication

    import app as app_module
    from conciliador.utils import load_qss
    from core.paths import ensure_runtime_dirs
    from core.runtime import resource_path

    ensure_runtime_dirs()
    _log(sandbox, f"Escenario={args.escenario} versión={args.version_actual} servidor=127.0.0.1:{fake.port} sandbox={sandbox}")

    qapp = QApplication.instance() or QApplication(sys.argv)
    load_qss(qapp, resource_path("styles.qss"))

    if args.con_login:
        from auth import AuthWindow
        from legal import enforce_legal_acceptance

        auth = AuthWindow()
        if auth.exec() != AuthWindow.DialogCode.Accepted or auth.session is None:
            return 0
        session = auth.session
        if not enforce_legal_acceptance(session):
            return 0
    else:
        from auth.auth_service import UserSession

        session = UserSession(
            user_id=999001,
            email="simulacion@example.test",
            username="usuario.simulacion",
            role="ejecutivo",
            is_active=True,
            must_change_password=False,
            auth_source="local",
        )

    win = app_module.MainWindow(session=session)
    win.setWindowTitle(win.windowTitle() + "  |  SIMULACIÓN")
    win.show()

    pilot = _AutoPilot(win, args.escenario, sandbox, resultado) if args.auto else None
    code = qapp.exec()

    resultado["peticiones"] = fake.requests
    resultado["archivos_descarga"] = sorted(p.name for p in updates_dir.iterdir())
    resultado["boton_visible_final"] = resultado.get("boton_visible_final", bool(win._btn_update.isVisible()))
    resultado["titulo"] = resultado.get("titulo", win.windowTitle())
    resultado_path.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    fake.server.shutdown()
    del pilot
    return code


if __name__ == "__main__":
    raise SystemExit(main())
