# AGENTS.md

Instrucciones para agentes que trabajen en este proyecto.

## Proyecto

Controlia Cobranzas es una aplicacion de escritorio PyQt6 para gestion de cobranzas, conciliacion, deudores, envios y administracion de carteras. El backend CRM vive en `CRM_Backend/` y la aplicacion principal se inicia desde `main.py`.

## Entorno esperado

- Sistema recomendado: Windows.
- Python recomendado: 3.11 o 3.12.
- Entorno virtual local preferido: `.venv/`.
- Dependencias principales: `PyQt6`, `pandas`, `openpyxl`, `XlsxWriter`.

Comandos habituales:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Para generar el ejecutable:

```powershell
.\build.bat
```

## Rutas de runtime

La aplicacion no debe guardar datos reales dentro del repositorio. Usa las rutas centralizadas en `core/paths.py`:

- `%APPDATA%/Controlia Cobranzas/data`
- `%APPDATA%/Controlia Cobranzas/config`
- `%APPDATA%/Controlia Cobranzas/logs`
- `%APPDATA%/Controlia Cobranzas/exports`

Si se agregan nuevos archivos de datos, configuracion, logs o exportaciones, usar estas funciones:

- `get_data_dir()`
- `get_config_dir()`
- `get_logs_dir()`
- `get_exports_dir()`

## Reglas de edicion

- Mantener los cambios acotados al modulo solicitado.
- No mover credenciales, bases reales ni configuraciones sensibles al repositorio.
- No persistir passwords SMTP ni secretos en texto plano.
- No modificar archivos generados en `build/`, `dist/`, `__pycache__/`, `.venv/` o `venv/` salvo pedido explicito.
- Preferir patrones ya existentes antes de crear nuevas abstracciones.
- Usar comentarios solo cuando aclaren una logica no obvia.
- Mantener compatibilidad con Windows.

## Estructura relevante

- `main.py`: punto de entrada recomendado.
- `app.py`: ventana principal y ensamblado general.
- `core/`: rutas, logging y migraciones compartidas.
- `auth/`: autenticacion y persistencia de usuarios.
- `conciliador/`: logica y vista de conciliacion.
- `deudores/`: vistas, detalle, esquemas y flujos asociados a deudores.
- `envios/`: configuracion SMTP, plantillas y envio de correos.
- `legal/`: documentos legales y copias en configuracion de runtime.
- `CRM_Backend/`: backend FastAPI relacionado.
- `tests/`: pruebas disponibles.

## Migraciones SQLite

Las bases SQLite usan `schema_migrations`. Para agregar una migracion:

1. Crear una funcion que reciba `sqlite3.Connection`.
2. Agregar una entrada `Migration(version, "descripcion", funcion)`.
3. No reutilizar numeros de version anteriores.
4. Mantener las migraciones idempotentes cuando sea razonable.

## Validacion antes de terminar

Segun el cambio realizado, ejecutar una o mas de estas comprobaciones:

```powershell
python main.py
python -m pytest
```

Si no se pueden ejecutar pruebas por dependencias, entorno grafico o datos faltantes, dejarlo informado con claridad.

## Datos sensibles

Este proyecto puede manejar informacion de cobranza, clientes, deudores, correos y configuraciones privadas. No incluir datos reales en ejemplos, fixtures, commits ni documentacion. Usar datos ficticios y anonimizados.
