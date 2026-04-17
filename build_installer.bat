@echo off
setlocal
cd /d "%~dp0"

echo [1/2] Compilando ejecutable con PyInstaller...
call build.bat
if errorlevel 1 goto :build_error

echo.
echo [2/2] Compilando instalador con Inno Setup...

set "ISCC_A=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set "ISCC_B=C:\Program Files\Inno Setup 6\ISCC.exe"
set "ISCC_PATH="

if exist "%ISCC_A%" set "ISCC_PATH=%ISCC_A%"
if not defined ISCC_PATH if exist "%ISCC_B%" set "ISCC_PATH=%ISCC_B%"
if not defined ISCC_PATH goto :iscc_missing

"%ISCC_PATH%" "installer\ControliaCobranzas.iss"

if errorlevel 1 goto :iss_error

set "LAST_SETUP="
for %%F in (installer\output\ControliaCobranzas_Setup_*.exe) do set "LAST_SETUP=%%~fF"
if "%LAST_SETUP%"=="" (
  echo [ERROR] No se encontro el instalador generado en installer\output.
  exit /b 1
)

set "DESKTOP_DIR=%USERPROFILE%\Desktop"
copy /Y "%LAST_SETUP%" "%DESKTOP_DIR%\" >nul
if errorlevel 1 (
  echo [WARN] Instalador compilado, pero no se pudo copiar al escritorio.
  echo [INFO] Ruta instalador: %LAST_SETUP%
) else (
  echo [OK] Instalador copiado al escritorio:
  echo      %DESKTOP_DIR%
)

echo.
echo Instalador generado en: installer\output
echo [OK] Ruta: %LAST_SETUP%
exit /b 0

:build_error
echo [ERROR] Fallo build.bat
exit /b 1

:iscc_missing
echo [ERROR] No se encontro ISCC.exe (Inno Setup 6).
echo Instala Inno Setup desde: https://jrsoftware.org/isdl.php
exit /b 1

:iss_error
echo [ERROR] Fallo la compilacion del instalador (.iss).
exit /b 1
