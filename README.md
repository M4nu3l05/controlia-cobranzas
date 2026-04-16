# Controlia Cobranzas - Mini aplicación de escritorio

Primera base auditada y endurecida para pruebas locales.

## Requisitos

- Python 3.11 o 3.12
- Windows recomendado

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Cambios incluidos en esta versión auditada

- Se eliminó la `.venv` del paquete.
- Se eliminaron bases SQLite reales y la configuración SMTP sensible.
- Se movieron rutas de datos, logs y configuración a `%APPDATA%/Controlia Cobranzas/`.
- Se agregó `main.py`, logging central y estructura `core/`.
- La contraseña SMTP ya no se persiste en disco.
- Se endureció la detección de columna email.
- La conciliación ahora usa configuración por empresa y validaciones explícitas.
- Se separó la pestaña de conciliación fuera de `app.py`.

## Carpetas de runtime

Al ejecutar, la app crea estas carpetas:

- `%APPDATA%/Controlia Cobranzas/data`
- `%APPDATA%/Controlia Cobranzas/config`
- `%APPDATA%/Controlia Cobranzas/logs`
- `%APPDATA%/Controlia Cobranzas/exports`

## Siguientes pasos sugeridos

1. Probar todos los flujos con archivos Excel de ejemplo.
2. Agregar tests reales para conciliación, envíos y deudores.
3. Preparar PyInstaller una vez validadas las rutas y assets.


## Refactor adicional incluido

- `deudores/view.py` fue dividido en `deudores/panels.py` y `deudores/ui_components.py` para separar controlador, layout y modelo de tabla.
- `envios/view.py` fue dividido en `envios/view_config.py`, `envios/view_plantillas.py`, `envios/view_envio.py` y `envios/ui_components.py`.
- Se agregó `core/db_migrations.py` para migraciones versionadas de SQLite sin depender de suscripciones ni servicios externos.
- Las migraciones se ejecutan automáticamente al abrir la conexión SQLite; no necesitas ninguna página ni licencia.

## Cómo funcionan las migraciones

Cada base SQLite ahora tiene una tabla `schema_migrations`. Cuando la app abre una conexión, revisa la versión aplicada y ejecuta las migraciones pendientes en orden.

Para agregar una nueva migración:

1. Crea una función que reciba `sqlite3.Connection`.
2. Agrega una entrada `Migration(nueva_version, "descripción", funcion)` en el módulo correspondiente.
3. Nunca reutilices un número de versión anterior.

Ejemplo mínimo:

```python
def migration_3(con):
    con.execute("ALTER TABLE gestiones ADD COLUMN canal TEXT")

MIGRATIONS.append(Migration(3, "Add canal column", migration_3))
```

No necesitas suscripción, web ni herramientas de terceros para esto.


## Probar en VSCode

La forma recomendada es usar un entorno virtual y ejecutar `main.py` desde la terminal integrada de VSCode.

1. Abre la carpeta `Comparador` en VSCode.
2. Abre la terminal integrada.
3. Crea el entorno:

```bash
python -m venv .venv
```

4. Activa el entorno en Windows:

```bash
.venv\Scripts\activate
```

5. Instala dependencias:

```bash
pip install -r requirements.txt
```

6. Ejecuta la app:

```bash
python main.py
```

También puedes ejecutar `python main.py` sin entorno virtual, pero solo si ya tienes instalados globalmente `PyQt6`, `pandas`, `openpyxl` y `XlsxWriter`. No es lo recomendado porque puede mezclar versiones.

## Build .exe con PyInstaller

El proyecto incluye:

- `build.bat`
- `ControliaCobranzas.spec`

Pasos:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
build.bat
```

Salida esperada:

```
dist\ControliaCobranzas\ControliaCobranzas.exe
```

La configuración inicial usa modo `onedir`, que es más estable para una app PyQt en esta etapa.
