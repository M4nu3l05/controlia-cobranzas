@echo off
setlocal

cd /d "%~dp0"

if not exist .venv (
    echo [ERROR] No existe .venv en esta carpeta.
    echo Crea el entorno con: python -m venv .venv
    exit /b 1
)

rem Se usa el interprete del entorno virtual de forma explicita: asi el build
rem siempre sale de .venv aunque activate.bat no altere el PATH de esta consola.
set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] No se encontro %VENV_PY%.
    echo Recrea el entorno con: python -m venv .venv
    exit /b 1
)

"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias.
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

"%VENV_PY%" -m PyInstaller ControliaCobranzas.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] Fallo la compilacion con PyInstaller.
    exit /b 1
)

echo.
echo Build completado.
echo Ejecutable: dist\ControliaCobranzas\ControliaCobranzas.exe
endlocal
