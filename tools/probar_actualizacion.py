"""Ejecuta todos los escenarios del simulador en modo automático y valida el resultado.

Uso: .venv\\Scripts\\python.exe tools\\probar_actualizacion.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "tools" / "simular_actualizacion.py"
NUEVA = "9.9.9"


def _run(escenario: str, base: Path) -> tuple[dict, dict | None, Path]:
    sandbox = base / escenario
    resultado = sandbox / "resultado.json"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    subprocess.run(
        [sys.executable, str(SIM), "--escenario", escenario, "--auto", "--sandbox", str(sandbox),
         "--version-nueva", NUEVA, "--resultado", str(resultado)],
        cwd=ROOT, env=env, timeout=180, check=False,
    )
    res = json.loads(resultado.read_text(encoding="utf-8"))
    post = None
    if escenario == "ok":
        post_path = sandbox / "resultado_post.json"
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if post_path.exists():
                try:
                    post = json.loads(post_path.read_text(encoding="utf-8"))
                    break
                except json.JSONDecodeError:
                    pass
            time.sleep(0.5)
    return res, post, sandbox


def _checks(escenario: str, res: dict, post: dict | None, sandbox: Path) -> list[tuple[str, bool]]:
    dialogos = res.get("dialogos", [])
    c = [("terminó sin timeout", not res.get("timeout"))]
    if escenario == "ok":
        c += [
            ("botón visible con la versión nueva", res.get("boton_texto") == f"⬆ Actualizar a {NUEVA}"),
            ("pidió confirmación al usuario", any("Hay una nueva versión" in d for d in dialogos)),
            ("mostró barra de progreso", bool(res.get("vio_progreso"))),
            ("descargó y verificó el SHA256", bool(res.get("instalador_hash_ok"))),
            ("lanzó el setup con /SILENT /CLOSEAPPLICATIONS",
             "/SILENT" in res.get("instalador_args", "") and "/CLOSEAPPLICATIONS" in res.get("instalador_args", "")),
            ("no quedaron archivos .part", not any(n.endswith(".part") for n in res.get("archivos_descarga", []))),
            ("la app se cerró y se reabrió", post is not None and bool(post.get("terminado"))),
            ("reabrió mostrando la versión nueva", post is not None and f"Controlia Cobranzas {NUEVA}" in post.get("titulo", "")),
            ("tras actualizar ya no aparece el botón", post is not None and not post.get("boton_visible_final")),
        ]
        log = (sandbox / "simulacion.log").read_text(encoding="utf-8")
        c.append(("el instalador esperó el cierre de la app", "App cerrada: True" in log))
    elif escenario in {"al-dia", "sin-releases", "sin-red"}:
        c += [
            ("no aparece el botón", not res.get("boton_visible_final") and "boton_texto" not in res),
            ("no muestra errores al usuario", not dialogos),
            ("no descargó nada", not res.get("archivos_descarga")),
            ("no lanzó instalador", "instalador_lanzado" not in res),
        ]
        if escenario == "sin-releases":
            c.append(("consultó la API", any("releases/latest" in p for p in res.get("peticiones", []))))
    elif escenario == "hash-malo":
        c += [
            ("botón visible", "boton_texto" in res),
            ("avisó que el archivo no coincide", any("no coincide" in d for d in dialogos)),
            ("NO lanzó el instalador", "instalador_lanzado" not in res),
            ("borró la descarga inválida", not res.get("archivos_descarga")),
        ]
    elif escenario == "lenta":
        c += [
            ("mostró barra de progreso", bool(res.get("vio_progreso"))),
            ("se pudo cancelar", bool(res.get("cancelado"))),
            ("NO lanzó el instalador", "instalador_lanzado" not in res),
            ("no dejó archivos a medias", not res.get("archivos_descarga")),
        ]
    return c


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="controlia_pruebas_update_"))
    total_fail = 0
    for escenario in ("ok", "al-dia", "sin-releases", "sin-red", "hash-malo", "lenta"):
        try:
            res, post, sandbox = _run(escenario, base)
            checks = _checks(escenario, res, post, sandbox)
        except Exception as exc:
            checks = [(f"ejecución ({exc})", False)]
        print(f"\n== Escenario: {escenario}")
        for nombre, ok in checks:
            total_fail += not ok
            print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}")
    print(f"\nResultado: {'TODO OK' if not total_fail else f'{total_fail} comprobación(es) fallida(s)'}")
    print(f"Registros en: {base}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
