@echo off
setlocal

cd /d "%~dp0"

echo [1/2] Compilando ejecutable con PyInstaller...
call build.bat
if errorlevel 1 (
    echo [ERROR] Fallo build.bat
    exit /b 1
)

echo.
echo [2/2] Compilando instalador con Inno Setup...

set "ISCC_PATH="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"

if "%ISCC_PATH%"=="" (
    echo [ERROR] No se encontro ISCC.exe (Inno Setup 6).
    echo Instala Inno Setup desde: https://jrsoftware.org/isdl.php
    exit /b 1
)

"%ISCC_PATH%" "installer\ControliaCobranzas.iss"
if errorlevel 1 (
    echo [ERROR] Fallo la compilacion del instalador (.iss).
    exit /b 1
)

for %%F in ("installer\output\ControliaCobranzas_Setup_*.exe") do set "LAST_SETUP=%%~fF"
if not defined LAST_SETUP (
    echo [ERROR] No se encontro el instalador generado en installer\output.
    exit /b 1
)

set "DESKTOP_DIR=%USERPROFILE%\Desktop"
copy /Y "%LAST_SETUP%" "%DESKTOP_DIR%\" >nul
if errorlevel 1 (
    echo [WARN] Instalador compilado, pero no se pudo copiar al escritorio.
    echo [INFO] Ruta instalador: %LAST_SETUP%
) else (
    for %%N in ("%LAST_SETUP%") do set "SETUP_NAME=%%~nxN"
    echo [OK] Instalador copiado al escritorio:
    echo      %DESKTOP_DIR%\%SETUP_NAME%
)

echo.
echo Instalador generado en: installer\output
endlocal
