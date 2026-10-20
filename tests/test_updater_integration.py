"""Updater contra un servidor HTTP real en 127.0.0.1 (sin mocks de requests)."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core import updater

SETUP = b"setup-ficticio-" * 50_000
NAME = "ControliaCobranzas_Setup_99.0.0.exe"


@pytest.fixture
def servidor(monkeypatch):
    estado = {"sums": f"{hashlib.sha256(SETUP).hexdigest()}  {NAME}\n", "status": 200, "headers": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            estado["headers"] = dict(self.headers)
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            if self.path.endswith("/releases/latest"):
                if estado["status"] != 200:
                    return self._send(estado["status"], b"{}", "application/json")
                payload = {
                    "tag_name": "v99.0.0",
                    "body": "notas",
                    "assets": [
                        {"name": NAME, "browser_download_url": f"{base}/{NAME}", "size": len(SETUP)},
                        {"name": "SHA256SUMS.txt", "browser_download_url": f"{base}/SHA256SUMS.txt", "size": 1},
                    ],
                }
                return self._send(200, json.dumps(payload).encode(), "application/json")
            if self.path.endswith("SHA256SUMS.txt"):
                return self._send(200, estado["sums"].encode(), "text/plain")
            if self.path.endswith(NAME):
                return self._send(200, SETUP)
            return self._send(404, b"")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(
        updater, "API_URL", f"http://127.0.0.1:{srv.server_address[1]}/repos/{{repo}}/releases/latest"
    )
    yield estado
    srv.shutdown()
    srv.server_close()


def test_flujo_completo_busca_descarga_y_verifica(servidor, tmp_path):
    release = updater.find_update()
    assert release is not None and release.version == "99.0.0"
    assert servidor["headers"].get("User-Agent", "").startswith("ControliaCobranzas/")

    progreso = []
    path = updater.download_update(release, progress_cb=lambda d, t: progreso.append((d, t)), dest_dir=tmp_path)

    assert path.read_bytes() == SETUP
    assert progreso[-1] == (len(SETUP), len(SETUP))
    # Una segunda descarga reutiliza el archivo ya verificado.
    assert updater.download_update(release, dest_dir=tmp_path) == path


def test_hash_publicado_incorrecto_no_deja_archivo(servidor, tmp_path):
    servidor["sums"] = f"{'f' * 64}  {NAME}\n"
    release = updater.find_update()

    with pytest.raises(updater.UpdateError, match="no coincide"):
        updater.download_update(release, dest_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_error_del_servidor_se_propaga_para_el_log(servidor):
    servidor["status"] = 500
    with pytest.raises(updater.requests.HTTPError):
        updater.find_update()
