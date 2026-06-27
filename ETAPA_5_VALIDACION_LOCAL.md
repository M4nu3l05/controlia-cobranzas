# Etapa 5 — validación, migraciones y respaldos

Este procedimiento prepara Controlia Cobranzas para una validación segura antes de cualquier despliegue. No requiere conectarse a la base productiva para las pruebas normales.

## Protecciones incorporadas

- El backend registra cada cambio estructural en `backend_schema_migrations`.
- Las migraciones son incrementales e idempotentes: reiniciar el backend no duplica tablas ni registros.
- `/health/ready` comprueba que el backend realmente puede consultar la base de datos.
- Producción rechaza `APP_DEBUG=true`, claves JWT cortas y la contraseña administrativa inicial.
- Los respaldos usan `pg_dump`, generan SHA-256 y nunca incluyen la contraseña en el comando visible.
- La restauración exige confirmar el nombre exacto de la base y bloquea producción por defecto.

## 1. Pruebas automáticas locales

Desde la raíz del proyecto:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest
```

Las pruebas utilizan una base SQLite desechable configurada en `tests/conftest.py`. Nunca deben apuntar a `DATABASE_URL` productiva.

## 2. Base PostgreSQL de ensayo

El archivo `CRM_Backend/docker-compose.staging.yml` crea una base local aislada en el puerto `55432`. Requiere Docker Desktop:

```powershell
docker compose -f CRM_Backend/docker-compose.staging.yml up -d
Copy-Item CRM_Backend/.env.staging.example CRM_Backend/.env.staging
```

Las credenciales incluidas son solamente locales. No deben reutilizarse en un servidor.

Antes de iniciar el backend, cargar las variables de `.env.staging` en la terminal o configurarlas en el entorno de ejecución. El backend aplicará las migraciones pendientes y las registrará automáticamente.

## 3. Respaldo verificable

Se requieren las herramientas cliente de PostgreSQL (`pg_dump` y `pg_restore`). La URL debe entregarse mediante una variable de entorno para que la contraseña no quede en el historial de comandos.

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://usuario:clave@servidor:5432/base"
.\venv\Scripts\python.exe CRM_Backend/scripts/backup_database.py --output-dir "D:\Respaldos\Controlia"
```

Se generan dos archivos: el respaldo `.backup` y su manifiesto `.backup.json`. El manifiesto contiene tamaño, fecha y SHA-256, pero no credenciales.

## 4. Restauración solamente en ensayo

```powershell
$env:APP_ENV = "staging"
$env:STAGING_DATABASE_URL = "postgresql+psycopg2://controlia_stage:local_staging_only@127.0.0.1:55432/controlia_staging"
.\venv\Scripts\python.exe CRM_Backend/scripts/restore_database.py "D:\Respaldos\Controlia\archivo.backup" --confirm-database controlia_staging
```

Después de restaurar:

1. Iniciar el backend de ensayo.
2. Consultar `http://127.0.0.1:8000/health/ready` y comprobar `status: ready`.
3. Ingresar con usuarios ficticios de cada rol.
4. Probar permisos, derivaciones, pagos, reversas, cargas y Birlados.
5. Confirmar que los totales y registros coinciden con el respaldo de ensayo.

## 5. Lista mínima de aceptación

- Ejecutivo propio: registra gestión y pago en su cartera.
- Ejecutivo ajeno: consulta y edita contacto, pero solo deriva la gestión.
- Destinataria: completa su derivación; otros roles no pueden cerrarla.
- Supervisor: realiza envíos masivos, carga bases y revierte pagos.
- Administrador: exporta respaldos funcionales, pero no revierte pagos.
- Pago distribuido: conserva fecha efectiva, comprobante y asignaciones exactas.
- Repetición de pago: la misma clave no descuenta dos veces.
- Carga mensual: muestra vista previa y permite exportar futuros Birlados.
- Registro ausente: queda visible como Birlado y conserva su historial.
- Respaldo: se restaura correctamente en una base separada.

## Regla para la etapa 6

No desplegar ni ejecutar migraciones productivas hasta contar con un respaldo verificado, una restauración exitosa en ensayo y aprobación funcional. La base productiva se respalda **antes** de arrancar por primera vez el backend actualizado.
