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

1. **Subir la versión** en `core\version.py` (es la única fuente; el `.iss` la recibe
   desde `build_installer.bat`):

   ```
   APP_VERSION = "2.5.0"
   ```

   El `AppId` del `.iss` **no se toca**: es el que hace que el setup actualice la
   instalación existente en vez de dejar una copia paralela.

2. **Compilar ejecutable + instalador** (desde la carpeta del proyecto):

   ```
   build_installer.bat
   ```

   Ese script hace todo en orden:
   - usa `.venv` e instala `requirements.txt` + `requirements-build.txt`;
   - limpia el `PATH` de herramientas externas que puedan contaminar el bundle;
   - borra `build\` y `dist\` y compila con `pyinstaller ControliaCobranzas.spec --noconfirm --clean`;
   - compila `installer\ControliaCobranzas.iss` con Inno Setup;
   - deja el instalador en `installer\output\` y copia una copia al Escritorio.

   La compilación se detiene automáticamente si detecta DLLs de sistema ajenas
   o si el ejecutable no logra cargar PyQt6/QtWidgets.

3. **Verificar** antes de repartirlo:

   ```
   .venv\Scripts\python.exe -m pytest -q
   dist\ControliaCobranzas\ControliaCobranzas.exe
   ```

4. **Publicar la release** para que las apps instaladas se actualicen solas:

   ```
   publish_release.bat notas.md
   ```

   Calcula `SHA256SUMS.txt` y crea la release `v<version>` en el repositorio público
   de binarios (`UPDATE_REPO` en `core\version.py`) con el instalador y el hash. El
   archivo de notas es opcional; su contenido se muestra al usuario antes de actualizar.
   Requiere [GitHub CLI](https://cli.github.com) autenticado (`gh auth login`).

## Actualización desde la aplicación

- Al iniciar, la app consulta la última release de `UPDATE_REPO`. Si es más nueva que
  `APP_VERSION`, aparece el botón **⬆ Actualizar a X** en la barra superior. También
  se puede revisar a mano en *Ayuda → Buscar actualizaciones*.
- Al aceptar, descarga el instalador, verifica su SHA256 y lo ejecuta en modo
  silencioso (`/SILENT`). Windows pide permiso de administrador, la app se cierra, se
  actualiza en el mismo lugar y vuelve a abrirse. Los datos de `%APPDATA%` no se tocan.
- La primera versión que incluye el botón hay que instalarla a mano una vez; desde ahí
  las siguientes se actualizan con el botón.
- Nunca publiques una release con un número menor o igual al ya publicado: la app
  compara números (`2.4.15` > `2.4.9`) y la ignoraría.

## Probar la actualización sin publicar nada

- `tools\simular_actualizacion.py`: abre la app con un "GitHub" falso en `127.0.0.1`,
  datos aislados en una carpeta temporal y un usuario ficticio. Muestra el botón, descarga,
  "instala" y reabre la app como versión nueva. Escenarios con `--escenario`: `ok`,
  `al-dia`, `sin-releases`, `sin-red`, `hash-malo`, `lenta` (para probar Cancelar).
  `--con-login` usa el login real.
- `tools\probar_actualizacion.py`: recorre todos los escenarios anteriores solo y valida
  cada resultado.
- `tools\probar_instalador.py`: compila una variante aislada del `.iss` (otro AppId, sin
  admin) e instala 1.0.0, actualiza a 1.0.1 en silencio como lo hace el botón y desinstala.
  No toca la instalación real.

## Solo el ejecutable (sin instalador)

```
build.bat
```

Genera `dist\ControliaCobranzas\ControliaCobranzas.exe`. Sirve para probar rápido un
cambio sin esperar la compilación del setup.

## Notas

- `installer\output\` está en `.gitignore`: los instaladores no se versionan, solo el `.iss`.
- El `.iss` ya no compila directamente desde el IDE de Inno Setup sin definir
  `MyAppVersion`; usar `build_installer.bat`.
- Si `build_installer.bat` falla con `No se encontro ISCC.exe`, es que falta Inno Setup 6.
- Si falla la instalación de dependencias, revisar conexión a internet: `pip` descarga
  `pyinstaller` y lo declarado en `requirements.txt`.
