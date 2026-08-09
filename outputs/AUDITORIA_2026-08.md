# Auditoría técnica — Controlia Cobranzas

**Fecha:** 8 de agosto de 2026
**Rama auditada:** `codex/dashboard-productividad-v2` (con cambios sin commitear)
**Alcance:** aplicación de escritorio PyQt6 + `CRM_Backend` (FastAPI/PostgreSQL) + instalador + manual de usuario
**Volumen:** ~32.000 líneas Python propias, 158 archivos versionados, 13 módulos de test

---

## 1. Resumen ejecutivo

El proyecto está **bastante más maduro de lo habitual** para una app de escritorio de este tamaño: hay separación por módulos, migraciones versionadas en ambas bases, un libro mayor de pagos con idempotencia y reversas, control de aceptación legal, historial de sesiones y un instalador funcional. Eso es mérito real y poco común.

El riesgo principal hoy **no es de funcionalidad, es de arquitectura y de autorización**:

1. El backend **no filtra por cartera** en los endpoints de deudores. La restricción "una ejecutiva solo ve sus carteras" que promete el manual se aplica **solo en el cliente**. Cualquiera con un token válido puede leer la cartera completa (RUT, nombres, correos, teléfonos, montos) con una petición HTTP directa.
2. Conviven **dos fuentes de verdad**: SQLite local por equipo y PostgreSQL en Render. Varias pantallas (Dashboard general, Envíos, Productividad como fallback) leen del SQLite local, que solo tiene lo que ese PC cargó.
3. Los **montos de deuda se guardan como `Float`** en `deudores_resumen`/`deudores_detalle`, mientras que el libro de pagos usa `Integer` CLP. Es una inconsistencia que produce descuadres de centavos en saldos.

Ninguno de los tres es un bug visible hoy, pero los tres se vuelven caros de arreglar a medida que crece la base instalada.

**Prioridad sugerida:** P0 seguridad (§3) → P1 arquitectura de datos (§4) → P2 calidad/proceso (§5) → P3 producto (§7).

---

## 2. Lo que está bien hecho

| Área | Detalle |
|---|---|
| **Libro mayor de pagos** | `payment_transactions` / `allocations` / `receipts` / `reversals` con `idempotency_key` único, `amount_clp` entero, saldo antes/después por asignación y reversa restringida a supervisor. Es diseño de nivel contable, correcto. |
| **Migraciones** | `schema_migrations` en SQLite y `backend_schema_migrations` en Postgres, con versionado explícito y documentación de cómo agregar una. |
| **Hardening de configuración** | `validate_production_safety` en `config.py` bloquea el arranque en producción si `APP_DEBUG=true`, si el JWT tiene <32 caracteres o si la clave del primer admin sigue siendo la inicial. Muy buen patrón. |
| **Contraseñas** | PBKDF2-HMAC-SHA256, 480.000 iteraciones, salt de 32 bytes, `secrets.compare_digest`. Correcto y actualizado. |
| **SMTP** | La contraseña vive solo en memoria (`_SMTP_SESSION`), nunca se persiste. Coherente con lo que promete el manual. |
| **Rutas de runtime** | Nada se escribe dentro del repo; todo va a `%APPDATA%/Controlia Cobranzas/`. `core/paths.py` con fallback si el directorio no es escribible. |
| **Respaldos** | `backup_database.py` / `restore_database.py` con `pg_dump --format=custom`, escritura a `.partial` y manifiesto. |
| **Cumplimiento legal** | Gate de aceptación de Términos y Privacidad versionado, con registro de evento en backend. |
| **Manual de usuario** | Excelente. Cubre roles, procedimientos, acciones irreversibles y glosario. Está por encima del estándar del mercado. |
| **Errores hacia el usuario** | `_friendly_backend_error` / `_friendly_excel_load_error` traducen fallas técnicas a lenguaje operativo. Buen criterio de producto. |

---

## 3. Seguridad — P0

### 3.1 Los endpoints de deudores no aplican el alcance por cartera 🔴

`CRM_Backend/app/api/deudores.py` exige token, pero nunca pasa `current_user` al servicio:

```
GET /deudores                    → list_deudores_service(db, q, empresa, ...)      sin usuario
GET /deudores/{rut}              → get_deudor_detalle_service(db, rut, empresa)    sin usuario
GET /deudores/destinatarios      → list_destinatarios_service(db, empresa, ...)    sin usuario
GET /deudores/{rut}/gestiones    → list_gestiones_service(db, rut, empresa)        sin usuario
```

`list_deudores_service` (`deudor_service.py:311`) filtra por `empresa` **solo si viene el parámetro**. Con `empresa=""` devuelve hasta 5.000 registros de todas las carteras.

Contraste: `GET /dashboard/summary` **sí** lo hace bien —

```python
if getattr(current_user, "role", "") == "ejecutivo":
    empresas_list = get_current_user_carteras_service(db=db, executor=current_user)
```

El módulo `app/core/authorization.py` ya tiene toda la lógica necesaria (`can_operate_company`, incluidos reemplazos temporales vigentes). Solo falta aplicarla en lectura, no únicamente en escritura.

**Impacto concreto:** una ejecutiva de Colmena, con su token legítimo, puede obtener el padrón completo de Consalud/Cruz Blanca/Cart-56 —correos, teléfonos, direcciones, montos— con un `curl`. En datos de salud previsional chilenos eso es un incidente reportable, no una molestia.

**Corrección:**

```python
# app/api/deudores.py
def _scope_empresas(db, user, empresa: str) -> list[str]:
    if is_privileged_operator(user):
        return [empresa] if empresa else []
    permitidas = get_current_user_carteras_service(db=db, executor=user)
    if empresa:
        if not can_operate_company(db, user, empresa):
            raise HTTPException(403, "No tienes acceso a esta cartera.")
        return [empresa]
    return permitidas or ["__sin_carteras__"]   # nunca lista vacía = "todo"
```

El detalle clave: **una lista vacía nunca debe significar "sin filtro"**. Ese es exactamente el error que existe hoy.

### 3.2 Descarga de comprobantes sin verificación de propiedad 🟠

`GET /operations/payments/{transaction_public_id}/receipt` busca la transacción por `public_id` y devuelve el archivo sin comprobar que el usuario pueda operar esa empresa. `public_id` es un UUID (no enumerable), pero eso es seguridad por oscuridad, no control de acceso.

Además, `filename` viene de la BD y se inyecta en la cabecera:

```python
filename = os.path.basename(receipt.filename).replace('"', "") or "comprobante"
headers={"Content-Disposition": f'attachment; filename="{filename}"'}
```

Se limpian comillas pero no `\r\n`. Vale sanitizar a `[A-Za-z0-9._-]` y usar `filename*=UTF-8''...`.

### 3.3 Sin límite de intentos de login 🟠

`POST /auth/login` no tiene rate limiting, backoff ni bloqueo de cuenta. Un atacante puede hacer fuerza bruta contra `admin@controlia.cl` (correo conocido y fijado en `render.yaml`) sin fricción. PBKDF2 con 480k iteraciones ayuda —cada intento cuesta CPU— pero eso también lo convierte en un vector de DoS barato en un plan `starter` de Render.

**Mínimo:** contador de fallos por email + IP, bloqueo temporal a los 5 intentos, y log de auditoría. `slowapi` resuelve el 80% en pocas líneas.

### 3.4 Token de 8 horas sin revocación ni refresh 🟡

`JWT_ACCESS_TOKEN_EXPIRE_MINUTES=480`, sin `jti`, sin lista de revocación, sin refresh token. Desactivar un usuario en la BD **no invalida su token vigente** —bueno: `get_current_user` sí consulta `is_active` en cada request, así que el corte sí funciona. Pero un cambio de rol o de asignación de cartera se refleja igual de bien; el problema real es que el token filtrado sirve 8 horas completas. Reducir a 60–120 min con refresh, o al menos agregar `jti` + tabla de revocación.

### 3.5 `python-jose 3.3.0` con CVEs conocidos 🟡

Esa versión arrastra CVE-2024-33663 (confusión de algoritmos) y CVE-2024-33664 (denegación por "JWT bomb"). El uso actual (HS256 fijo en `decode_token`) mitiga lo principal, pero conviene migrar a `PyJWT` o actualizar. Recomendación adicional: fijar explícitamente `algorithms=["HS256"]` (ya está) y validar `iss`/`aud`.

### 3.6 Código de autenticación local muerto 🟡

`auth/auth_db.py` (375 líneas) mantiene una tabla local de usuarios con PBKDF2, tokens de reset y un archivo `setup_credentials.txt` en texto plano en `%APPDATA%`. El login real ya es 100% backend (`auth_service.login` solo llama `/auth/login`); esas rutas quedaron como legado.

Un camino muerto de autenticación es superficie de ataque sin dueño. Eliminar `auth_db.py` (dejando solo las constantes de rol) y `reset_users_db.py`.

### 3.7 Sin firma de código en el instalador 🟡

`ControliaCobranzas.iss` genera un setup sin firmar y con `PrivilegesRequired=admin`. SmartScreen lo marcará en cada equipo nuevo y los usuarios aprenderán a saltarse la advertencia —justo el hábito que no quieres en un equipo que maneja datos de salud. Un certificado OV de firma de código (~USD 200–400/año) elimina el problema.

---

## 4. Arquitectura de datos — P1

### 4.1 Doble fuente de verdad: SQLite local vs PostgreSQL 🔴

Este es el problema estructural más caro del proyecto.

| Flujo | Escribe en | Lee de |
|---|---|---|
| Carga de base (`deudores/worker.py:85`) | SQLite local **y** backend | — |
| Búsqueda de deudores (`view.py:872`) | — | backend ✅ |
| Dashboard "Vista general" (`dashboard/view.py:1002`) | — | **SQLite local** ❌ |
| Montos por empresa (`view.py:1260`) | — | **SQLite local** ❌ |
| Envío masivo (`view_envio.py:870`) | — | backend, con fallback a **SQLite local** ⚠️ |
| Productividad (`productivity_view.py:703`) | — | backend, con fallback a **SQLite local** ⚠️ |

Consecuencias operativas reales:

- **El Dashboard general muestra números distintos en cada PC.** Solo refleja lo que ese equipo cargó alguna vez. Una supervisora que revisa desde su notebook ve una cartera; desde el PC de la oficina, otra.
- **Los fallbacks son silenciosos.** Si el backend de Render está frío o caído, Envíos y Productividad pasan a datos locales sin avisar. El usuario ve cifras plausibles y desactualizadas —peor que ver un error.
- **Los borrados no se propagan.** "Limpiar empresa" desde `admin_carteras` borra en local y en backend, pero solo en el equipo que ejecuta la acción. Los demás PC conservan la copia local.

**Recomendación:** SQLite pasa a ser **caché explícita de solo lectura**, nunca fuente. Concretamente:

1. Migrar `dashboard/view.py` a `/dashboard/summary` (ya existe y ya aplica el alcance por cartera).
2. Eliminar los fallbacks silenciosos: si el backend no responde, mostrar "Sin conexión — datos no disponibles", no datos viejos.
3. Cuando se sirva desde caché, marcarlo en pantalla con la marca de tiempo del último refresco.
4. Al final, `deudores/database.py` (1.229 líneas) puede reducirse a la capa de caché o desaparecer.

### 4.2 Montos en `Float` 🟠

```python
# models/deudor.py
copago:       Mapped[float] = mapped_column(Float, ...)
total_pagos:  Mapped[float] = mapped_column(Float, ...)
saldo_actual: Mapped[float] = mapped_column(Float, ...)

# models/payment.py — así sí
amount_clp:   Mapped[int]   = mapped_column(Integer, nullable=False)
```

El libro de pagos está bien; las tablas de deuda no. `Float` es binario IEEE-754: sumar 10.000 copagos acumula error. Y ya hay código defensivo que lo delata:

```python
# deudor_service.py:_saldo_pendiente_detalle
if abs(saldo - saldo_calc) > 0.01:
    return saldo_calc
```

Esa tolerancia de 0,01 es la cicatriz del problema. En Chile el peso no tiene decimales: migrar a `Integer` (CLP entero) o `Numeric(15,0)` y eliminar la tolerancia.

### 4.3 Fechas como texto 🟠

`fecha_vencimiento`, `fecha_emision`, `fecha_pago`, `fecha_prestacion` son `String(40)`. Esto significa:

- No se puede filtrar por rango en SQL sin castear.
- Los filtros de antigüedad del Dashboard ("30 días o más") se calculan en Python sobre todo el dataset.
- El formato depende de cómo lo escribió la Isapre en el Excel.

Migrar a `Date` normalizando en la importación. Es la base para cualquier analítica de aging seria.

### 4.4 Comprobantes como BLOB en PostgreSQL 🟡

`PaymentReceipt.content` es `LargeBinary` dentro de la BD, en un plan de 15 GB. Con 200 comprobantes/mes de 500 KB son ~1,2 GB/año, y cada `pg_dump` los arrastra completos. Mover a almacenamiento de objetos (S3/R2/Backblaze) guardando URL + SHA256. El `sha256` ya está modelado, así que la migración es directa.

### 4.5 Sin índices compuestos ni constraints de unicidad 🟡

`deudores_resumen` tiene índices sueltos en `empresa`, `rut_afiliado`, `periodo_carga`, pero la consulta real siempre es `(empresa, periodo_carga)` o `(empresa, rut_afiliado)`. Faltan índices compuestos. Y no hay `UniqueConstraint` sobre `(empresa, rut_afiliado, periodo_carga)`, así que la deduplicación depende enteramente de la lógica de `_detalle_identity_key` en Python.

### 4.6 Normalización de RUT en Python, no en SQL 🟡

`_rut_db_expr` construye `ltrim(replace(replace(trim(col),'.',''),'-',''),'0')` en cada consulta. Eso **impide usar el índice** (`rut_afiliado` indexado no sirve cuando lo envuelves en funciones) y hace un scan completo. Solución: columna generada `rut_normalizado` con índice, poblada en la importación.

---

## 5. Calidad de código y proceso — P2

### 5.1 Suite de tests: 9 de 22 módulos se saltan en silencio 🟠

Verificado en esta auditoría:

```
11 passed, 11 skipped
SKIPPED [9] could not import 'sqlalchemy' / 'pydantic_settings'
```

Toda la cobertura del backend —autorización, migraciones, libro de pagos, importación mensual, birlados— **no se ejecuta** salvo que instales `requirements-dev.txt` completo. Ninguno de los dos `.venv` del proyecto lo tiene. Un `pytest` "verde" hoy no dice nada sobre el backend.

Peor: los skips son de `importorskip`, así que un entorno roto se ve idéntico a un entorno sano.

**Corrección:** marcar los tests de backend con `@pytest.mark.backend` y hacer que fallen (no que se salten) cuando falta la dependencia en un entorno que declara ejecutarlos.

### 5.2 Sin CI, sin linter, sin formateador 🟠

No hay `.github/`, ni `pyproject.toml`, ni `ruff.toml`, ni `.pre-commit-config.yaml`. Todo control de calidad es manual.

Con el tamaño actual (~32k líneas, 3 ramas activas) esto ya cuesta. Un GitHub Actions mínimo:

```yaml
- run: pip install -r requirements-dev.txt
- run: ruff check .
- run: pytest -q --strict-markers
```

### 5.3 Dependencias del cliente sin fijar 🟠

```
requirements.txt:   PyQt6 / pandas / openpyxl / XlsxWriter / requests>=2.31
CRM_Backend/req:    fastapi==0.115.12 / sqlalchemy==2.0.39 / ...
```

El backend está bien fijado; el cliente no. Un `build.bat` ejecutado en dos fechas distintas produce ejecutables con PyQt6 y pandas diferentes. Para un `.exe` que se distribuye a usuarios finales, eso significa builds no reproducibles y bugs imposibles de reproducir. Fijar versiones exactas y considerar `pip-tools` o `uv`.

### 5.4 Archivos monolíticos 🟡

| Archivo | Líneas |
|---|---|
| `deudores/detalle_dialog.py` | **3.072** |
| `deudores/view.py` | 2.116 |
| `dashboard/view.py` | 1.466 |
| `auth/auth_service.py` | 1.423 |
| `envios/view_envio.py` | 1.368 |
| `CRM_Backend/.../deudor_import_service.py` | 1.307 |

`detalle_dialog.py` mezcla layout, lógica de negocio, llamadas HTTP, render de plantillas y envío de correo en una sola clase. Es el archivo que más va a doler en 12 meses. El README ya documenta que se hizo este ejercicio con `deudores/view.py` y `envios/view.py` —conviene repetirlo aquí.

`auth_service.py` no es un servicio de autenticación: es el cliente HTTP completo del backend (46 funciones exportadas, desde login hasta plantillas de correo y notificaciones). Debería llamarse `backend_client.py` y dividirse por dominio.

### 5.5 Llamadas HTTP bloqueando el hilo de UI 🟠

```python
# dashboard/productivity_view.py:801
def refresh(self) -> None:
    debtors, summary = self._load_backend() if self._uses_backend() else self._load_local()
```

`_load_backend` hace 1 + 2N peticiones (summary + deudores + destinatarios por empresa) con timeouts de 15–20 s, **en el hilo de UI**, y hay un `QTimer` que lo dispara periódicamente. Con Render en plan starter (cold start de 30+ s) la app se congela por completo. Lo mismo en `dashboard/view.py:829`.

El proyecto ya usa `QThread` correctamente en `conciliador/`, `deudores/`, `envios/`. Falta aplicarlo en `dashboard/`.

### 5.6 `except Exception` genérico: 124 ocurrencias 🟡

No hay `except:` desnudo (bien), pero 124 `except Exception` sí ocultan errores de programación entre los errores esperados. Especialmente grave en `deudores_import.py`:

```python
except Exception as exc:
    raise HTTPException(500, detail=f"No se pudo importar la base de deudores: {exc}")
```

Eso filtra el mensaje interno de la excepción al cliente —incluidos fragmentos de SQL o rutas del servidor. Loguear completo, devolver genérico.

### 5.7 `.venv` copiado de otra carpeta 🟡

```
# .venv/pyvenv.cfg
executable = ...\Comparador_V1.0.0\Comparador\.venv\Scripts\python.exe
```

El entorno virtual se copió desde la versión anterior del proyecto en vez de recrearse. En Windows esto rompe `pip` de formas sutiles y explica por qué faltan dependencias de desarrollo. Recrear desde cero.

### 5.8 Versión sin fuente única 🟡

| Fuente | Versión |
|---|---|
| `installer/ControliaCobranzas.iss` | 2.0.4 |
| `CRM_Backend/app/main.py` | 2.0.0 |
| Último commit relevante | "Actualiza installer a 2.0.1" |
| Manual (`outputs/`) | v1.0 |

Definir un `__version__` único y derivar el resto. Sin eso, un reporte de soporte que dice "tengo la 2.0" no identifica nada.

### 5.9 Higiene del repositorio 🟡

- Rama actual con **21 archivos modificados sin commitear**, incluidos `legal/privacidad.txt` (documento con versión), `installer/*.iss` y 2 archivos de test nuevos. Los cambios en documentos legales versionados no deberían quedar en el árbol de trabajo.
- `CRM_Backend/uvicorn_test_*.log`, `app_9120.log`, `frontend_test_*.log` en el árbol (ignorados por `.gitignore`, pero conviene limpiarlos).
- `outputs/` contiene tres `.docx` casi idénticos del manual (`_a11y`, `_v1.0`, base) sin criterio claro de cuál es el vigente.
- Archivos Excel con **datos reales de Isapres** (`Carga Deb CB 072026.xlsx`, `Carga Debitia Col 072026.xlsx`) están en la carpeta padre del repo. Fuera de Git, pero a un `git add ../` de distancia. Moverlos a una ubicación separada y cifrada.

---

## 6. Cumplimiento y datos personales

La aplicación procesa datos que en Chile son sensibles: RUT, nombre, domicilio, correo, teléfono, **deuda por prestaciones de salud** y licencias médicas. Eso califica como dato personal, y el vínculo con prestaciones de salud lo acerca a dato sensible.

Puntos a revisar (recomiendo validación legal formal, no solo técnica):

1. **Cifrado en reposo.** El SQLite local en `%APPDATA%` está sin cifrar. Un notebook robado entrega la cartera completa. Evaluar SQLCipher o —mejor— eliminar la copia local (§4.1) y confiar en Postgres con cifrado de disco.
2. **Retención.** No hay política ni purga automática. Los datos de deudores pagados/birlados se acumulan indefinidamente.
3. **Auditoría de lectura.** Se audita el cambio de datos de cliente (`customer_change_audit`) pero no la consulta. Para datos de salud, saber *quién consultó qué* suele ser tan relevante como saber quién modificó.
4. **Derechos ARCO.** No hay flujo para atender solicitudes de acceso/rectificación/supresión de un deudor.
5. **Ley 21.719.** La nueva ley de protección de datos personales chilena entra en vigencia y crea la Agencia de Protección de Datos, con multas sustantivas. Conviene confirmar con asesoría legal la fecha exacta de entrada en vigencia y el plan de adecuación —especialmente los puntos 1, 2 y 4.
6. **`legal/privacidad.txt` modificado sin commit.** Un documento legal versionado que cambia fuera de control de versiones rompe la trazabilidad de qué aceptó cada usuario y cuándo.

---

## 7. Mejoras de producto y roadmap

### Corto plazo (1–2 meses) — corregir lo que ya duele

1. Alcance por cartera en el backend (§3.1). **Bloqueante.**
2. Eliminar fallbacks silenciosos a SQLite y migrar el Dashboard a `/dashboard/summary` (§4.1).
3. Mover las llamadas HTTP del Dashboard a `QThread` (§5.5).
4. Rate limiting en login (§3.3).
5. CI con lint + tests que realmente se ejecuten (§5.1, §5.2).
6. Fijar versiones del cliente y recrear `.venv` (§5.3, §5.7).

### Mediano plazo (3–6 meses) — pagar deuda estructural

7. Migrar montos a entero CLP y fechas a `Date`, con migración de datos (§4.2, §4.3).
8. Dividir `detalle_dialog.py` y renombrar/dividir `auth_service.py` (§5.4).
9. Comprobantes a almacenamiento de objetos (§4.4).
10. Índices compuestos y `rut_normalizado` (§4.5, §4.6).
11. Firma de código del instalador y actualizador automático (§3.7). Hoy cada versión nueva exige reinstalar manualmente en cada PC —con `PrivilegesRequired=admin`, eso implica llamar a TI cada vez.
12. Eliminar `auth_db.py` y `reset_users_db.py` (§3.6).

### Funcionalidades que faltan y el negocio va a pedir

| Funcionalidad | Por qué |
|---|---|
| **Registro de llamadas / click-to-call** | La cobranza real es telefónica. Hoy la llamada se registra a mano como "gestión". Integrar con la central (Asterisk/Twilio) da tiempos de conversación, grabaciones y contactabilidad real. |
| **Convenios de pago en cuotas** | El modelo soporta abonos y pagos totales, pero no un convenio con cuotas programadas, seguimiento de cumplimiento y alerta por cuota vencida. Es el instrumento central de la cobranza prejudicial. |
| **WhatsApp Business API** | Hoy `_enviar_whatsapp` abre `web.whatsapp.com` con el mensaje precargado: manual, no masivo, sin acuse de recibo y sin registro automático. La API oficial permite plantillas aprobadas, envío masivo y estado de entrega. |
| **Reportes programados** | El manual describe descargas manuales de Excel. Un envío automático semanal de productividad al supervisor evita la rutina y da continuidad al indicador. |
| **Métricas de recupero** | Hoy el Dashboard mide *actividad* (gestiones, conexiones, duración de sesión). Falta lo que importa: tasa de recupero por cartera, por ejecutiva, por antigüedad; curva de recuperación; efectividad por canal. Es el paso de "cuánto trabajaron" a "cuánto recuperaron". |
| **Bitácora de auditoría consultable** | Existe `customer_change_audit` pero no hay pantalla para explorarla con filtros y exportación. |
| **Modo offline explícito** | Si se mantiene la caché local, que sea un modo declarado con banner visible y sincronización al reconectar —no un fallback invisible. |
| **Escalamiento judicial** | El proyecto vive bajo `Comparador_Juridicus`. Si el destino es derivar a cobranza judicial, falta el flujo: criterios de derivación, expediente, seguimiento de causa. |

### Apuesta de plataforma (6–12 meses)

El backend FastAPI ya está completo y es multiusuario. La app de escritorio es hoy el cuello de botella para distribuir: instalador con admin, sin firma, sin auto-update, un SQLite por PC.

**Un frontend web (React/Vue) sobre el mismo backend eliminaría de un golpe** la distribución de instaladores, la divergencia de datos locales, el problema de versiones mezcladas y las llamadas HTTP bloqueando la UI. Migración por módulos: Dashboard primero (es el que más sufre hoy), luego Búsqueda de Deudores, y dejar el escritorio solo para Conciliación —que trabaja con archivos locales y ahí sí tiene ventaja.

No es urgente, pero define hacia dónde invertir el esfuerzo de refactor: cada hora puesta en el backend sirve para ambos caminos; cada hora puesta en `detalle_dialog.py` solo sirve para el escritorio.

---

## 8. Tabla de acciones priorizadas

| # | Acción | Impacto | Esfuerzo | Prioridad |
|---|---|---|---|---|
| 1 | Alcance por cartera en endpoints de deudores | Fuga de datos personales | Bajo | 🔴 P0 |
| 2 | Verificación de propiedad en descarga de comprobantes | Acceso indebido | Muy bajo | 🔴 P0 |
| 3 | Rate limiting en login | Fuerza bruta / DoS | Bajo | 🟠 P1 |
| 4 | Eliminar fallbacks silenciosos a SQLite | Decisiones sobre datos falsos | Medio | 🟠 P1 |
| 5 | Dashboard vía backend + `QThread` | App congelada, cifras erróneas | Medio | 🟠 P1 |
| 6 | CI + lint + tests que no se salten | Regresiones invisibles | Bajo | 🟠 P1 |
| 7 | Fijar dependencias del cliente | Builds no reproducibles | Muy bajo | 🟠 P1 |
| 8 | Montos a entero CLP | Descuadres contables | Medio-alto | 🟡 P2 |
| 9 | Fechas a tipo `Date` | Analítica de aging | Medio | 🟡 P2 |
| 10 | Firma de código del instalador | Confianza / SmartScreen | Bajo + costo | 🟡 P2 |
| 11 | Dividir `detalle_dialog.py` | Mantenibilidad | Alto | 🟡 P2 |
| 12 | Eliminar auth local muerto | Superficie de ataque | Bajo | 🟡 P2 |
| 13 | Comprobantes a object storage | Costo y tamaño de BD | Medio | 🟢 P3 |
| 14 | Índices compuestos + `rut_normalizado` | Rendimiento | Bajo | 🟢 P3 |
| 15 | Política de retención y auditoría de lectura | Cumplimiento Ley 21.719 | Medio | 🟢 P3 |

---

## 9. Cierre

La base es sólida y las decisiones difíciles —libro mayor de pagos, migraciones versionadas, validación de configuración productiva, gate legal— ya están tomadas y bien tomadas. Lo que falta no es rehacer: es **cerrar la brecha entre lo que el manual promete y lo que el servidor efectivamente exige**, y **decidir de una vez cuál es la fuente de verdad de los datos**.

Los puntos 1 y 2 de la tabla son de horas, no de semanas, y son los que más reducen riesgo por unidad de esfuerzo. Empezaría por ahí.
