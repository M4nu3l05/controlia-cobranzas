# Validacion E2E V1

Pauta de validacion final por rol para aprobar salida de version `v1.0.0`.

## Acta de ejecucion

- Fecha de prueba:
- Version app:
- Version backend:
- Probador:
- Equipo (resolucion):

## Convencion de resultado

- `PASS`: cumple resultado esperado.
- `FAIL`: no cumple.
- `N/A`: no aplica por configuracion.

Cada caso debe registrar:

- Resultado (`PASS/FAIL/N/A`)
- Evidencia (captura, video, log o ruta de archivo)
- Observacion corta

## Preparacion

1. Backend encendido y accesible.
2. App de escritorio abre sin error.
3. Usuarios disponibles: `admin`, `supervisor`, `ejecutiva`.
4. Existe al menos una cartera para asignar y una base deudores de prueba.
5. Existen archivos de prueba para gestiones y conciliacion.

## Casos criticos por rol

### Administrador

1. Login correcto y acceso a todos los modulos (`Dashboard`, `Conciliacion`, `Deudores`, `Envios`, `Carteras`, `Usuarios`).
2. Crea usuario nuevo, edita usuario y cambia estado activo/inactivo.
3. Asigna cartera a ejecutiva y guarda; ejecutiva la ve al relogin.
4. Carga base deudores en un solo clic y aparece en tabla.
5. Intenta cargar base duplicada (mismo contenido con otro nombre) y sistema bloquea con mensaje claro.
6. Abre detalle deudor; montos resumen y detalle coinciden.
7. Registra pago y valida recalculo de `Pagos` y `Saldo Actual`.
8. Carga base de gestiones y valida persistencia en detalle.
9. Exporta base de gestiones (completa y por fecha) con datos reales.
10. Dashboard muestra metricas y productividad con datos coherentes.

### Supervisor

1. Login correcto; no ve modulo `Usuarios`.
2. Accede a `Administracion de carteras` y puede asignar/reasignar.
3. Carga base deudores y base de gestiones.
4. Botones de limpieza eliminan datos reales, no solo vista.
5. Puede descargar exportes de gestiones con resultados.
6. Dashboard muestra productividad/sesiones cuando hay actividad.

### Ejecutiva

1. Login correcto; solo ve modulos permitidos (`Dashboard`, `Busqueda de Deudores`).
2. Si tiene cartera: solo ve esa cartera.
3. Si no tiene cartera: mensaje `Sin carteras asignadas`.
4. No puede cargar bases ni ver empresas no asignadas.
5. Puede gestionar deudor y registrar gestion/pago segun permisos del flujo.

## Casos transversales

1. Correos/plantillas: vista previa sin error; montos correctos y en formato CLP (`$` y miles).
2. Mensajes de autenticacion:
   - contraseña incorrecta: `Usuario o contraseña incorrectos.`
   - token/sesion invalida: mensaje de sesion expirada.
3. Cambio/restablecimiento de contraseña funciona contra backend.
4. Conciliacion de nominas finaliza sin error y genera Excel.
5. Responsividad: validar al menos en `1366x768` y en pantalla grande sin cortes de UI.
6. Persistencia: cerrar y reabrir app mantiene deudores, gestiones, pagos, carteras y dashboard.

## Registro de resultados

| ID | Caso | Rol | Resultado | Evidencia | Observacion |
|---|---|---|---|---|---|
| A-01 | Login y modulos completos | Admin |  |  |  |
| A-02 | Gestion de usuarios | Admin |  |  |  |
| A-03 | Asignacion de carteras | Admin |  |  |  |
| A-04 | Carga base deudores | Admin |  |  |  |
| A-05 | Bloqueo base duplicada por contenido | Admin |  |  |  |
| A-06 | Detalle y montos consistentes | Admin |  |  |  |
| A-07 | Registro de pago | Admin |  |  |  |
| A-08 | Carga de gestiones | Admin |  |  |  |
| A-09 | Exportes de gestiones | Admin |  |  |  |
| A-10 | Dashboard/productividad | Admin |  |  |  |
| S-01 | Login y visibilidad por rol | Supervisor |  |  |  |
| S-02 | Asignacion de carteras | Supervisor |  |  |  |
| S-03 | Carga de bases | Supervisor |  |  |  |
| S-04 | Limpieza real de datos | Supervisor |  |  |  |
| S-05 | Exportes de gestiones | Supervisor |  |  |  |
| S-06 | Dashboard/productividad | Supervisor |  |  |  |
| E-01 | Login y modulos permitidos | Ejecutiva |  |  |  |
| E-02 | Restriccion por cartera | Ejecutiva |  |  |  |
| E-03 | Sin cartera asignada | Ejecutiva |  |  |  |
| E-04 | Bloqueo acciones no permitidas | Ejecutiva |  |  |  |
| E-05 | Operacion diaria de deudores | Ejecutiva |  |  |  |
| T-01 | Correos y formato CLP | Transversal |  |  |  |
| T-02 | Mensajes de autenticacion | Transversal |  |  |  |
| T-03 | Reset/cambio contraseña en backend | Transversal |  |  |  |
| T-04 | Conciliacion sin error | Transversal |  |  |  |
| T-05 | Responsividad UI | Transversal |  |  |  |
| T-06 | Persistencia post reinicio | Transversal |  |  |  |

## Criterio de aprobacion V1

Se aprueba V1 si:

1. No hay `FAIL` en casos de seguridad, permisos o persistencia.
2. No hay `FAIL` en montos, pagos, gestiones, exportes ni correos.
3. Responsividad validada en notebook y pantalla grande.
4. Cualquier `N/A` esta justificado en observaciones.
