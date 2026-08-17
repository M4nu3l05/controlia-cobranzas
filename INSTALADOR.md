# Cómo generar / actualizar el instalador

Guía corta para reconstruir `ControliaCobranzas_Setup_<version>.exe` después de un cambio en el código.

## Requisitos (una sola vez)

- Python 3.12 con el entorno virtual creado en la carpeta del proyecto:
  ```
  python -m venv .venv
  ```
- [Inno Setup 6](https://jrsoftware.org/isdl.php) instalado (el script lo busca en
  `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` o en `C:\Program Files\Inno Setup 6\ISCC.exe`).

## Pasos para publicar una nueva versión

1. **Subir la versión** en `installer\ControliaCobranzas.iss`:

   ```
   #define MyAppVersion "2.3.0"
   ```

   El `AppId` **no se toca**: es el que hace que el setup actualice la instalación
   existente en vez de dejar una copia paralela.

2. **Compilar ejecutable + instalador** (desde la carpeta del proyecto):

   ```
   build_installer.bat
   ```

   Ese script hace todo en orden:
   - activa `.venv` e instala `requirements.txt` + `pyinstaller`;
   - borra `build\` y `dist\` y compila con `pyinstaller ControliaCobranzas.spec --noconfirm --clean`;
   - compila `installer\ControliaCobranzas.iss` con Inno Setup;
   - deja el instalador en `installer\output\` y copia una copia al Escritorio.

3. **Verificar** antes de repartirlo:

   ```
   .venv\Scripts\python.exe -m pytest -q
   dist\ControliaCobranzas\ControliaCobranzas.exe
   ```

## Solo el ejecutable (sin instalador)

```
build.bat
```

Genera `dist\ControliaCobranzas\ControliaCobranzas.exe`. Sirve para probar rápido un
cambio sin esperar la compilación del setup.

## Notas

- `installer\output\` está en `.gitignore`: los instaladores no se versionan, solo el `.iss`.
- Si `build_installer.bat` falla con `No se encontro ISCC.exe`, es que falta Inno Setup 6.
- Si falla la instalación de dependencias, revisar conexión a internet: `pip` descarga
  `pyinstaller` y lo declarado en `requirements.txt`.
