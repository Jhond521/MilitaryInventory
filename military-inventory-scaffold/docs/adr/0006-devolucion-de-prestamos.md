# ADR-0006: Devolución de préstamos de munición y saldo pendiente

- **Fecha**: 2026-10-20
- **Estado**: Aceptada
- **Decide**: John Cuervo

## Contexto

Issue #22 (RF-22, feedback de David en el issue #18): un `Prestamo` (RF-15) es
hoy un traslado de una sola vía. `Prestamo.save()` resta la cantidad de la
`Existencia` de origen y la suma a la de destino. Después no queda forma de
devolverlo ni de saber cuánto sigue prestado: la cantidad recibida se mezcla
con la existencia propia de la compañía destino (misma fila
tipo/compañía/depósito/lote). David necesita devolver total o parcialmente
y ver, en Munición, qué parte está prestada, a quién y de dónde viene.

## Opciones consideradas

- **Préstamo inverso** (un `Prestamo` nuevo de destino a origen): no cambia
  el esquema, pero no liga la devolución al préstamo original. No se puede
  calcular el saldo pendiente, y Movimientos lo mostraría como otro préstamo.
- **Separar lo recibido en su propia `Existencia`** (marcar la fila de
  destino como "prestada"): resaltaría la cantidad por construcción, pero
  rompe la unicidad tipo/compañía/depósito/lote en la que se apoyan
  `Prestamo` y `Existencia.entregar()`. Además obliga a elegir de qué fila
  entregar a un soldado. Es demasiado invasivo.
- **Modelo `DevolucionPrestamo` + `Prestamo.cantidad_devuelta`** (elegida):
  cada devolución es una fila propia (préstamo, cantidad, usuario,
  observación, fecha). El préstamo guarda el acumulado devuelto, que se
  actualiza en la misma transacción. Así el saldo pendiente
  (`cantidad - cantidad_devuelta`) se filtra en la base sin agregaciones.

## Decisión

- `Prestamo.cantidad_devuelta` (entero, por defecto 0) y la propiedad
  `Prestamo.saldo`.
- Modelo `DevolucionPrestamo(prestamo, cantidad, usuario, observacion,
  fecha)`, creado solo a través de `Prestamo.devolver(cantidad, usuario,
  observacion)`. Ese método, dentro de una transacción con
  `select_for_update()`:
  - resta de la `Existencia` de destino;
  - suma a la de origen (y la vuelve a crear si se borró);
  - actualiza `cantidad_devuelta`.

  Rechaza una cantidad mayor al saldo o a lo disponible en depósito en la
  compañía destino. Lo que ya se entregó a soldados (RF-18) no está en
  depósito, así que no se puede devolver hasta que los soldados lo regresen.
- La devolución siempre va de destino a origen, por el mismo depósito y
  lote del préstamo.
- Munición no guarda el resaltado en ninguna parte. `existencia_list`
  cruza cada existencia con los préstamos que tienen saldo pendiente: los
  recibidos (la compañía es la destino) y los realizados (la compañía es la
  origen), con el mismo tipo, depósito y lote.
- Movimientos: `DevolucionPrestamo` entra en `_mezclar_por_fecha()` bajo la
  clase "Préstamos", como manda ADR-0005.

## Consecuencias

**Lo que ganamos**:
- Trazabilidad completa (RNF-03): cada devolución tiene su fila y queda
  ligada a su préstamo.
- No cambian `Existencia` ni la regla de una fila por
  tipo/compañía/depósito/lote. `Existencia.entregar()` y `Prestamo.save()`
  siguen igual.

**Lo que aceptamos a cambio**:
- `cantidad_devuelta` es un dato desnormalizado: debe ser igual a la suma de
  las devoluciones. Solo lo escribe `Prestamo.devolver()`, dentro de su
  transacción, y un test lo verifica.
- Lo recibido sigue sumado a la existencia de destino. El resaltado muestra
  cuánto de ese total es prestado, pero no lo separa físicamente.

**Qué haría que revisáramos esta decisión**:
- Que se pida devolver desde la compañía que prestó ("reclamar").
- Que se pida devolver a otro depósito o lote distinto al del préstamo.
- Que el préstamo de armamento (issue #23, RF-23) necesite un modelo de
  préstamo común. Para armas se decidirá en su propia ADR.
