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

rem Evita que PyInstaller encuentre DLLs de herramientas externas heredadas
rem en PATH (Poppler, libheif, etc.) y las copie dentro de la aplicacion.
set "PATH=%~dp0.venv\Scripts;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem"

"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt
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

for %%F in (ucrtbase.dll icuuc.dll) do (
    if exist "dist\ControliaCobranzas\_internal\%%F" (
        echo [ERROR] El build contiene una DLL de sistema incompatible: %%F
        exit /b 1
    )
)
for %%F in (dist\ControliaCobranzas\_internal\api-ms-win-*.dll dist\ControliaCobranzas\_internal\icudt*.dll) do (
    if exist "%%F" (
        echo [ERROR] El build contiene una DLL de sistema incompatible: %%~nxF
        exit /b 1
    )
)

echo Verificando arranque de Qt...
set "QT_QPA_PLATFORM=offscreen"
"dist\ControliaCobranzas\ControliaCobranzas.exe" --smoke-test
if errorlevel 1 (
    echo [ERROR] El ejecutable compilado no pudo cargar PyQt6/QtWidgets.
    exit /b 1
)
set "QT_QPA_PLATFORM="

echo.
echo Build completado.
echo Ejecutable: dist\ControliaCobranzas\ControliaCobranzas.exe
endlocal
