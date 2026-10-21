# ADR-0007: Préstamo temporal de armamento serializado entre compañías

- **Fecha**: 2026-10-20
- **Estado**: Aceptada
- **Decide**: John Cuervo

## Contexto

Issue #23 (RF-23, feedback de David en el issue #18): David quiere prestar
armas desde Inventario a otra compañía, igual que la munición, y que el arma
prestada quede claramente identificada y se pueda devolver. Hasta v1.5, NO-3
lo prohibía ("un arma pertenece a una compañía y solo a esa"), y el código
lo aplica: `Armamento.entregar()` y `Armamento.clean()` exigen que el
soldado sea de `Armamento.compania`. En v1.6 (2026-10-20) John reescribió
NO-3: la compañía **dueña** nunca cambia, pero el arma puede prestarse
temporalmente. Mientras está prestada, la compañía que la recibe puede
entregarla a sus soldados y recibirla de vuelta en depósito.

## Opciones consideradas

- **Reasignar `Armamento.compania` durante el préstamo**: no toca las
  consultas existentes, pero se pierde la compañía dueña, que es justo lo
  que NO-3 protege. Para devolver habría que reconstruirla desde el
  historial.
- **Modelo `PrestamoArmamento` aparte** (préstamo con fecha de devolución,
  como `Prestamo`/`DevolucionPrestamo`): separa bien el préstamo, pero un
  arma es una sola unidad. "Prestada o no" es un estado del arma, no un
  saldo que se va devolviendo, así que un modelo nuevo complica consultar
  el estado actual sin ganar nada.
- **Campo `Armamento.compania_en_prestamo` + tipos de `Movimiento`**
  (elegida):
  - El arma guarda a quién está prestada (`None` = no prestada).
  - `compania_poseedora` = `compania_en_prestamo or compania`: es la
    compañía que la puede usar ahora.
  - El préstamo y su devolución son `Movimiento` del arma, con los tipos
    nuevos `PRESTAMO` y `DEV_PRESTAMO`.

## Decisión

- `Armamento.compania_en_prestamo` (FK nullable a `Compania`) y la propiedad
  `compania_poseedora`. `clean()` y `entregar()` validan el soldado contra
  `compania_poseedora`, no contra `compania`.
- `Armamento.prestar(compania, usuario, observacion)` exige un arma activa,
  en depósito, que no esté prestada y una compañía distinta a la dueña.
  `Armamento.devolver_prestamo(usuario, observacion)` exige el arma en
  depósito. Los dos son transaccionales y dejan un `Movimiento`.
- `Movimiento.compania_en_prestamo` (FK nullable) guarda la compañía que
  tenía el arma prestada **en el momento** del movimiento. Lo llevan el
  `PRESTAMO` y el `DEV_PRESTAMO`, y también las entregas y devoluciones
  hechas durante el préstamo. Así Movimientos muestra a la compañía que
  recibió el arma lo que hizo con ella, aunque `Armamento.compania` sea
  otra.
- `dar_de_baja()` se bloquea mientras el arma está prestada. Tampoco hay
  préstamos en cadena: un arma prestada no se vuelve a prestar.
- Inventario de una compañía: lista sus armas propias y las que tiene
  prestadas, con las etiquetas "Prestada a X" y "Prestada por Y". Los
  contadores cuentan el arma en la compañía que la tiene, no en la dueña.
- Los códigos `PRESTAMO` y `DEV_PRESTAMO` caben en el `max_length=12`
  actual de `Movimiento.tipo`, así que la migración solo agrega columnas.

## Consecuencias

**Lo que ganamos**:
- La compañía dueña nunca se pierde.
- "¿Está prestada y a quién?" se responde con un campo del arma, sin
  consultas extra.
- El préstamo queda en el historial del arma junto a sus entregas y
  devoluciones (RNF-03). `_mezclar_por_fecha()` ya incluye `Movimiento`,
  así que no hace falta otro modelo en Movimientos.

**Lo que aceptamos a cambio**:
- Cada lugar que antes comparaba contra `Armamento.compania` para decidir
  quién puede usar el arma tiene que usar `compania_poseedora`. Hoy son
  `clean()`, `entregar()`, el selector de soldado al entregar, Inventario y
  el filtro de Movimientos.
- Préstamo de munición (`Prestamo`, ADR-0006) y de armas usan modelos
  distintos. Es a propósito: la munición tiene saldo y el arma es una
  unidad.

**Qué haría que revisáramos esta decisión**:
- Que se pida prestar un arma que está en mano.
- Que se pidan préstamos en cadena.
- Que se pida transferir la propiedad de un arma de forma definitiva, que
  NO-3 sigue prohibiendo.
