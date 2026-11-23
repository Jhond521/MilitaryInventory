# ADR-0008: Respaldo en Excel y restauración por reemplazo completo, sin lógica de negocio

- **Fecha**: 2026-11-23
- **Estado**: Aceptada
- **Decide**: John Cuervo (decisiones confirmadas por David en los issues #33 y #34)

## Contexto

Issues #33 y #34 (RF-26, RF-27, RNF-06): David quiere un botón, solo para administradores,
que exporte todos los datos a un Excel (una hoja por tabla, relacionadas por ID). Con ese
mismo archivo quiere poder dejar el sistema como estaba. Hoy no hay ningún respaldo que un
administrador pueda bajar por su cuenta (T-04 sigue abierta).

Restaurar choca con dos reglas de la casa:

- Todo cambio de ubicación o saldo pasa por los métodos de dominio y deja un `Movimiento`.
- `Prestamo.save()` mueve existencias de origen a destino al crearse.

Si la restauración pasara por esos métodos, los saldos del archivo se aplicarían dos veces y
aparecerían movimientos que nunca ocurrieron.

## Opciones consideradas

- **Reproducir el historial**: recrear cada movimiento con `entregar()`, `devolver()` y
  `Prestamo.save()`. Respeta las reglas, pero depende del orden exacto, falla con cualquier
  dato histórico que hoy no pase las validaciones y genera fechas nuevas.
- **Fusión (merge) con los datos actuales**: ambigua cuando el mismo registro cambió en los
  dos lados. David pidió volver a un punto en el tiempo, no mezclar.
- **Reemplazo completo, insertando la foto tal cual** (elegida):
  - En una transacción, se borran las tablas de `inventory` y se insertan las filas del
    archivo con sus `id` y sus fechas originales.
  - Se usa `bulk_create`, que no llama a `save()`, y `auto_now`/`auto_now_add` se apagan
    mientras dura.
  - Después se corren los `clean()` que solo miran la fila y sus relaciones: SERIE vs
    CANTIDAD, la ubicación del arma y el pelotón del soldado.
  - Al final se reajustan las secuencias.

## Decisión

Reemplazo completo, todo o nada:

- El archivo es una foto coherente: sus saldos ya son el resultado de sus movimientos. Por
  eso no se recalcula nada ni se escriben movimientos nuevos.
- Es la única excepción a "todo cambio deja un `Movimiento`". La restauración se registra en
  el log de la aplicación: quién, cuándo, de qué respaldo y qué conteos.
- **Usuarios**: se cruzan por correo y nunca se borran ni se modifican. Los que faltan se
  crean inactivos y con contraseña no utilizable, solo para conservar el historial. El
  archivo no lleva contraseñas.
- **Versión**: un respaldo de otra versión de las migraciones se rechaza. Migrar respaldos
  viejos queda fuera de v1.
- **Validación**:
  - en memoria, con errores por hoja, fila y columna;
  - una prueba en seco dentro de una transacción con rollback;
  - confirmación escrita `REESTABLECER`.

## Consecuencias

- Un modelo nuevo de `inventory` debe agregarse a `MODELOS_RESPALDO`
  (`apps/inventory/respaldo.py`). Si no se agrega, un test falla.
- Un campo nuevo entra solo, porque las columnas salen de `concrete_fields`. Pero cambia la
  migración, así que los respaldos anteriores dejan de cargarse.
- Postgres no deshace `setval()` con un rollback. Por eso la prueba en seco no reajusta
  secuencias: solo lo hace la restauración real.
- Apagar `auto_now` toca el estado del campo a nivel de proceso. Es seguro con los workers
  síncronos de gunicorn, que atienden una petición por proceso. Si algún día se usan hilos,
  hay que revisarlo.
