@echo off
setlocal
cd /d "%~dp0"

rem Publica el instalador ya generado por build_installer.bat como release de
rem GitHub. Las apps instaladas la detectan y ofrecen el boton "Actualizar".
rem Uso: publish_release.bat [archivo_de_notas.md]

set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] No se encontro %VENV_PY%.
    exit /b 1
)

where gh >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Falta GitHub CLI. Instalala desde https://cli.github.com y ejecuta: gh auth login
    exit /b 1
)

set "APP_VERSION="
set "UPDATE_REPO="
for /f "usebackq delims=" %%V in (`"%VENV_PY%" -c "from core.version import APP_VERSION; print(APP_VERSION)"`) do set "APP_VERSION=%%V"
for /f "usebackq delims=" %%R in (`"%VENV_PY%" -c "from core.version import UPDATE_REPO; print(UPDATE_REPO)"`) do set "UPDATE_REPO=%%R"
if not defined APP_VERSION (
    echo [ERROR] No se pudo leer APP_VERSION desde core\version.py.
    exit /b 1
)

set "SETUP_NAME=ControliaCobranzas_Setup_%APP_VERSION%.exe"
set "SETUP_PATH=installer\output\%SETUP_NAME%"
set "SUMS_PATH=installer\output\SHA256SUMS.txt"
if not exist "%SETUP_PATH%" (
    echo [ERROR] No existe %SETUP_PATH%. Ejecuta primero build_installer.bat.
    exit /b 1
)

"%VENV_PY%" -c "import hashlib,sys; p=sys.argv[1]; h=hashlib.sha256(open(p,'rb').read()).hexdigest(); open(sys.argv[2],'w',newline='\n').write(h+'  '+sys.argv[3]+'\n')" "%SETUP_PATH%" "%SUMS_PATH%" "%SETUP_NAME%"
if errorlevel 1 (
    echo [ERROR] No se pudo calcular el SHA256.
    exit /b 1
)

set "NOTES_ARG=--notes "Controlia Cobranzas %APP_VERSION%""
if not "%~1"=="" (
    if not exist "%~1" (
        echo [ERROR] No existe el archivo de notas %~1.
        exit /b 1
    )
    set "NOTES_ARG=--notes-file "%~1""
)

echo Publicando v%APP_VERSION% en %UPDATE_REPO%...
gh release create "v%APP_VERSION%" "%SETUP_PATH%" "%SUMS_PATH%" --repo "%UPDATE_REPO%" --title "Controlia Cobranzas %APP_VERSION%" %NOTES_ARG%
if errorlevel 1 (
    echo [ERROR] Fallo la publicacion. Si la version ya existe, sube APP_VERSION en core\version.py.
    exit /b 1
)

echo.
echo [OK] Release v%APP_VERSION% publicada. Las apps instaladas la veran al iniciar.
endlocal
