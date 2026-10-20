"""Prueba real del instalador Inno Setup en modo actualización silenciosa.

Compila una variante aislada de installer\\ControliaCobranzas.iss (otro AppId,
sin permisos de administrador, carpeta temporal y un ejecutable "marcador" en
lugar de la app) y verifica:

  1. Instalación silenciosa nueva (v1.0.0) con los mismos argumentos del botón.
  2. Actualización v1.0.0 -> v1.0.1 lanzada igual que la app (os.startfile),
     en el mismo lugar, sin desinstalar, limpiando _internal y reabriendo la app.
  3. Desinstalación limpia.

No toca la instalación real de Controlia Cobranzas.

Uso: .venv\\Scripts\\python.exe tools\\probar_instalador.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.updater import INSTALLER_ARGS  # noqa: E402

ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]
REAL_APP_ID = "{{1D6E7720-33C0-4745-BFB7-C1EC5A46A57C}"
TEST_APP_ID = "{{7A1C0F3E-5B2D-4E8A-9C11-0D2E3F4A5B6C}"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{7A1C0F3E-5B2D-4E8A-9C11-0D2E3F4A5B6C}_is1"

MARKER_SRC = r'''
import ctypes, json, os, sys, time
exe_dir = os.path.dirname(sys.executable)
try:
    version = open(os.path.join(exe_dir, "version.txt"), encoding="utf-8").read().strip()
except OSError:
    version = "?"
log = os.environ.get("CONTROLIA_PRUEBA_MARCADOR")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"version": version, "argv": sys.argv[1:],
                             "admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
                             "t": time.time()}) + "\n")
'''

resultados: list[tuple[str, bool, str]] = []


def check(nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append((nombre, bool(ok), detalle))
    print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}{f'  ({detalle})' if detalle and not ok else ''}", flush=True)
    return bool(ok)


def reg_version() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "DisplayVersion")[0]
    except OSError:
        return None


def reg_location() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0]
    except OSError:
        return None


def marcas(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def esperar(cond, timeout: float) -> bool:
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.5)
    return cond()


def build_iss(work: Path, install_dir: Path, payload: Path, out: Path) -> Path:
    src = (ROOT / "installer" / "ControliaCobranzas.iss").read_text(encoding="utf-8-sig")
    reemplazos = [
        ('#define MyAppName "Controlia Cobranzas"', '#define MyAppName "Controlia Cobranzas Prueba"'),
        (f'#define MyAppId "{REAL_APP_ID}"', f'#define MyAppId "{TEST_APP_ID}"'),
        ("PrivilegesRequired=admin", "PrivilegesRequired=lowest"),
        (r"DefaultDirName={autopf}\{#MyAppName}", f"DefaultDirName={install_dir}"),
        ("OutputDir=output", f"OutputDir={out}"),
        (r'Source: "..\dist\ControliaCobranzas\*"', f'Source: "{payload}\\*"'),
    ]
    for viejo, nuevo in reemplazos:
        if viejo not in src:
            raise SystemExit(f"El .iss cambió y la prueba no encontró: {viejo}")
        src = src.replace(viejo, nuevo)
    src = src.replace('"..\\', f'"{ROOT}\\').replace("=..\\", f"={ROOT}\\")
    iss = work / "ControliaCobranzas_prueba.iss"
    iss.write_text(src, encoding="utf-8-sig")
    return iss


def main() -> int:
    iscc = next((p for p in ISCC_CANDIDATES if p.exists()), None)
    if not iscc:
        print("[ERROR] No se encontró Inno Setup 6 (ISCC.exe).")
        return 2
    if reg_version():
        print("[ERROR] Quedó una instalación de prueba anterior; desinstala 'Controlia Cobranzas Prueba'.")
        return 2

    work = Path(tempfile.mkdtemp(prefix="controlia_prueba_instalador_"))
    install_dir = work / "instalado"
    payload = work / "payload"
    out = work / "setups"
    marker_log = work / "marcas.jsonl"
    env = {**os.environ, "CONTROLIA_PRUEBA_MARCADOR": str(marker_log)}
    os.environ["CONTROLIA_PRUEBA_MARCADOR"] = str(marker_log)  # Heredado por os.startfile.
    print(f"Carpeta de trabajo: {work}\n")

    print("== Preparación")
    (work / "marcador.py").write_text(MARKER_SRC, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole", "--name", "ControliaCobranzas",
         "--distpath", str(work / "marcador_dist"), "--workpath", str(work / "marcador_build"),
         "--specpath", str(work), str(work / "marcador.py")],
        capture_output=True, text=True,
    )
    marker_exe = work / "marcador_dist" / "ControliaCobranzas.exe"
    if not check("ejecutable marcador compilado", r.returncode == 0 and marker_exe.exists(), r.stderr[-300:]):
        return 1

    iss = build_iss(work, install_dir, payload, out)

    def compilar(version: str, extra_internal: str) -> Path:
        if payload.exists():
            shutil.rmtree(payload)
        (payload / "_internal").mkdir(parents=True)
        shutil.copy2(marker_exe, payload / "ControliaCobranzas.exe")
        (payload / "version.txt").write_text(version, encoding="utf-8")
        (payload / "_internal" / extra_internal).write_text(version, encoding="utf-8")
        r = subprocess.run([str(iscc), "/Q", f"/DMyAppVersion={version}", str(iss)], capture_output=True, text=True)
        setup = out / f"ControliaCobranzas_Setup_{version}.exe"
        check(f"setup {version} compilado", r.returncode == 0 and setup.exists(), (r.stdout + r.stderr)[-300:])
        return setup

    setup_v1 = compilar("1.0.0", "lib_v1.txt")
    setup_v2 = compilar("1.0.1", "lib_v2.txt")

    try:
        print("\n== 1. Instalación silenciosa nueva (v1.0.0)")
        log1 = work / "setup_v1.log"
        r = subprocess.run(f'"{setup_v1}" {INSTALLER_ARGS} /LOG="{log1}"', env=env, timeout=180)
        check("el setup terminó con código 0", r.returncode == 0, f"código {r.returncode}")
        check("registrada versión 1.0.0", reg_version() == "1.0.0", str(reg_version()))
        check("archivos instalados", (install_dir / "ControliaCobranzas.exe").exists()
              and (install_dir / "_internal" / "lib_v1.txt").exists())
        check("documentos legales copiados", (install_dir / "legal" / "privacidad.txt").exists())
        check("la página de privacidad no bloqueó el modo silencioso", reg_version() == "1.0.0")
        check("abrió la app al terminar ([Run] sin skipifsilent)",
              esperar(lambda: any(m["version"] == "1.0.0" for m in marcas(marker_log)), 20))

        print("\n== 2. Actualización 1.0.0 -> 1.0.1 lanzada como lo hace la app")
        (install_dir / "_internal" / "obsoleto.dll").write_text("viejo", encoding="utf-8")
        ubicacion_antes = reg_location()
        log2 = work / "setup_v2.log"
        os.startfile(str(setup_v2), "open", f'{INSTALLER_ARGS} /LOG="{log2}"')
        ok = esperar(lambda: log2.exists() and "Log closed." in log2.read_text(encoding="utf-8", errors="ignore"), 180)
        check("el setup lanzado con os.startfile terminó", ok)
        texto_log = log2.read_text(encoding="utf-8", errors="ignore") if log2.exists() else ""
        check("el log indica instalación exitosa", "Installation process succeeded" in texto_log)
        check("registrada versión 1.0.1 (sin desinstalar)", reg_version() == "1.0.1", str(reg_version()))
        check("misma carpeta de instalación", reg_location() == ubicacion_antes, f"{ubicacion_antes} -> {reg_location()}")
        check("detectó la instalación previa", "Previous" in texto_log or "previous" in texto_log)
        check("[InstallDelete] limpió _internal antiguo",
              not (install_dir / "_internal" / "obsoleto.dll").exists()
              and not (install_dir / "_internal" / "lib_v1.txt").exists())
        check("instaló los archivos nuevos", (install_dir / "_internal" / "lib_v2.txt").exists()
              and (install_dir / "version.txt").read_text(encoding="utf-8") == "1.0.1")
        check("reabrió la app ya actualizada",
              esperar(lambda: any(m["version"] == "1.0.1" for m in marcas(marker_log)), 20))
        reabierta = [m for m in marcas(marker_log) if m["version"] == "1.0.1"]
        check("la app reabierta no corre como administrador", bool(reabierta) and not reabierta[-1]["admin"])
        check("una sola entrada en Programas instalados", len(list((install_dir).glob("unins*.exe"))) == 1)
    finally:
        print("\n== 3. Desinstalación")
        unins = install_dir / "unins000.exe"
        if unins.exists():
            subprocess.run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=120)
            esperar(lambda: reg_version() is None, 30)
        check("desinstalación limpia del registro", reg_version() is None)
        check("eliminó el ejecutable", esperar(lambda: not (install_dir / "ControliaCobranzas.exe").exists(), 30))

    fallas = sum(1 for _, ok, _ in resultados if not ok)
    print(f"\nResultado: {'TODO OK' if not fallas else f'{fallas} comprobación(es) fallida(s)'}")
    print(f"Logs en: {work}")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
