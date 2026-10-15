# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_dir = Path.cwd()
icon_file = project_dir / "assets" / "app_icon.ico"
icon_path = str(icon_file) if icon_file.exists() else None

datas = [
    (str(project_dir / "styles.qss"), "."),
    (str(project_dir / "legal" / "terminos.txt"), "legal"),
    (str(project_dir / "legal" / "privacidad.txt"), "legal"),
]
if icon_file.exists():
    datas.append((str(icon_file), "."))

hiddenimports = [
    "PyQt6.sip",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "tkinter"],
    noarchive=False,
)

# PyInstaller resuelve DLLs usando también el PATH del proceso de compilación.
# Herramientas externas (por ejemplo Poppler) pueden aportar copias privadas de
# ICU/UCRT que no pertenecen a la aplicación. Si esas copias quedan junto al
# ejecutable, Windows las carga antes que las del sistema y Qt falla con error
# 127 ("no se encontró el procedimiento especificado"). Los API sets, UCRT e
# ICU de esta compilación de Qt son componentes del sistema operativo.
system_dll_names = {"ucrtbase.dll", "icuuc.dll"}
system_dll_prefixes = ("api-ms-win-", "ext-ms-win-", "icudt")


def is_external_system_dll(binary):
    bundled_name = Path(binary[0]).name.lower()
    return bundled_name in system_dll_names or bundled_name.startswith(system_dll_prefixes)


a.binaries = [binary for binary in a.binaries if not is_external_system_dll(binary)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ControliaCobranzas",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ControliaCobranzas",
)
