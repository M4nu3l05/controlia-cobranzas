@echo off
setlocal

cd /d "%~dp0"

if not exist .venv (
    echo [ERROR] No existe .venv en esta carpeta.
    echo Crea el entorno con: python -m venv .venv
    exit /b 1
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] No se pudo activar el entorno virtual.
    exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias.
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller ControliaCobranzas.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] Fallo la compilacion con PyInstaller.
    exit /b 1
)

echo.
echo Build completado.
echo Ejecutable: dist\Controlia Cobranzas\Controlia Cobranzas.exe
endlocal
