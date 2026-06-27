# Resultados de validación — Etapa 5

Fecha: 22 de junio de 2026.

Todas las comprobaciones se realizaron localmente. No se conectó ni modificó Render, GitHub o la base productiva.

## Pruebas automáticas

- Resultado: `31 passed`.
- Migraciones repetibles verificadas.
- Permisos por rol, derivaciones, auditoría, reemplazos, pagos, reversas, idempotencia y Birlados cubiertos.
- Verificación de sintaxis: 125 archivos Python válidos.

## Respaldo y restauración PostgreSQL

- Herramientas: PostgreSQL 18.3 (`pg_dump` y `pg_restore`).
- Formato: respaldo Custom con manifiesto SHA-256.
- Restauración realizada en una base PostgreSQL local aislada.
- Resultado: respaldo íntegro y datos ficticios recuperados correctamente.

## Ensayo con la base local heredada

Se respaldó `crm_backend_corredora_local` y se restauró una copia en `controlia_stage5_restore`. Las migraciones se aplicaron solamente sobre la copia.

| Tabla | Antes | Después |
|---|---:|---:|
| cartera_asignaciones | 0 | 0 |
| deudores_detalle | 1 | 1 |
| deudores_gestiones | 6 | 6 |
| deudores_resumen | 1 | 1 |
| email_templates | 3 | 3 |
| user_session_history | 5 | 5 |
| users | 1 | 1 |

- Tablas antes: 11.
- Tablas después: 22.
- Migraciones aplicadas: 1, 2, 3, 4 y 5.
- Pérdida de registros: ninguna.
- Columnas opcionales nuevas: verificadas.
- Tablas de pagos, auditoría y cargas mensuales: verificadas.

Durante la preparación funcional se detectaron campos históricos obligatorios que no estaban representados en el modelo actual. Se incorporó la migración 5 para conservar esos campos y mantener compatibilidad tanto con bases antiguas como nuevas. La suite completa volvió a aprobarse después de la corrección.

## Aceptación funcional automatizada

- 26 comprobaciones reales contra PostgreSQL aprobadas.
- Visibilidad transversal de carteras: aprobada.
- Gestión propia y bloqueo de gestión ajena: aprobados.
- Derivación, plazo de 24 horas y cierre exclusivo por destinataria: aprobados.
- Edición ajena con auditoría y notificación: aprobada.
- Pago, idempotencia, bloqueo ajeno y reversa exclusiva del supervisor: aprobados.
- Reemplazo temporal y revocación al finalizar: aprobados.
- Carga mensual viva con vista previa y transición a Birlado: aprobada.
- Interfaz por rol: módulos, carga de bases y envío masivo verificados en modo gráfico aislado.

## Decisión sobre la base heredada

`crm_backend_corredora_local` debe conservarse sin cambios hasta terminar la validación funcional de la etapa 6. Ya existe un respaldo independiente en formato Custom. Una vez aprobado el nuevo sistema, podrá eliminarse si se confirma que no es utilizada por ningún proceso local.
