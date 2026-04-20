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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name="ControliaCobranzas",
)
