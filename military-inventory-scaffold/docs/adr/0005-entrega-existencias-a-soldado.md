# ADR-0005: Modelo para entrega/devolución de existencias a un soldado

- **Fecha**: 2026-09-30
- **Estado**: Aceptada
- **Decide**: John Cuervo

## Contexto

Issue #12 (RF-18, feedback de David en el issue #11): el módulo de Municiones
(Existencias) debe permitir entregar una cantidad a un soldado y devolverla,
igual que `Armamento.entregar()`/`.devolver()` (RF-10). A diferencia de un
arma serializada (una fila, un soldado a la vez, `ubicacion` EN_MANO/
DEPOSITO), la cantidad de una existencia es **fraccionable**: varios
soldados pueden tener, al mismo tiempo, una porción de la misma
`Existencia` (mismo tipo/compañía/depósito/lote). El modelo de `Armamento`
no generaliza directamente.

## Opciones consideradas

- **Generalizar `Existencia`** con una `ubicacion` EN_MANO/DEPOSITO y un
  `soldado` opcional, permitiendo varias filas "en mano" por existencia:
  más simétrico con `Armamento` a primera vista, pero exige volver nulable
  `deposito` (rompe el `UniqueConstraint` actual y el criterio de búsqueda
  de `Prestamo`, que asume una fila de depósito por tipo/compañía/lote) y
  constraints condicionales para no permitir dos filas de depósito
  duplicadas. Más invasivo sin necesidad real.
- **Nuevo modelo `ExistenciaAsignada`, FK a `Existencia`** (elegida): una
  fila por `(existencia, soldado)` con su propia `cantidad`, sin tocar el
  esquema de `Existencia`. Mismo espíritu que `Prestamo`: un modelo nuevo
  para un movimiento de cantidad entre dos partes, en vez de forzar al
  modelo de saldo a representar ambos lados. `Existencia.entregar()` resta
  de `self.cantidad` y suma (o crea) la `ExistenciaAsignada`;
  `ExistenciaAsignada.devolver()` hace lo inverso y borra la fila si queda
  en 0 (un saldo de 0 en mano no aporta nada). Reusa el mismo patrón
  transaccional (`select_for_update()`) que `Prestamo.save()`.
- **Historial**: nuevo modelo `MovimientoExistencia` (FK a `Existencia` +
  `soldado` + tipo ENTREGA/DEVOLUCION), en vez de reusar `Movimiento` — su
  FK a `armamento` es obligatoria, mismo motivo por el que `Prestamo`
  tampoco lo reusa.

## Decisión

`ExistenciaAsignada` (existencia, soldado, cantidad) + `MovimientoExistencia`
(existencia, tipo, soldado, cantidad, usuario, observación, fecha), con
`Existencia.entregar()` y `ExistenciaAsignada.devolver()` como los métodos
de dominio (ver `apps/inventory/models.py`).

## Consecuencias

**Lo que ganamos**: no se toca el esquema ni las queries existentes de
`Existencia`/`Prestamo` — cero riesgo de regresión ahí. El nuevo modelo es
simple (3 campos) y la restricción de unicidad es directa (sin condiciones
parciales).

**Lo que aceptamos a cambio**: dos modelos nuevos en vez de generalizar uno
existente — algo más de superficie, pero cada uno con una sola
responsabilidad clara, igual que `Prestamo` ya separado de `Existencia`.

**Qué haría que revisáramos esta decisión**: si a futuro se pide un
"historial unificado" de todos los movimientos (armamento + existencias) en
una sola vista, convendría evaluar entonces una interfaz común en vez de
dos modelos de movimiento paralelos.
