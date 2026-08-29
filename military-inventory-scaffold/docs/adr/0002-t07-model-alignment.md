# ADR-0002: Domain model alignment with PRD v1.3 (T-07)

- **Fecha**: 2026-08-29
- **Estado**: Aceptada
- **Decide**: John Cuervo

## Contexto

El scaffold inicial (T-01) modelaba un único tipo de material: serializado
(`Armamento`, con serie individual). El PRD avanzó a v1.1–v1.3 con feedback real
de David e introdujo tres conceptos que el scaffold no tenía: pelotones (RF-16),
material controlado por **cantidad** en vez de serie —munición y cascos— (RF-14),
y préstamo de munición **entre compañías** (RF-15), que es la única excepción a la
regla de que el material serializado nunca cruza de compañía (NO-3). Además, v1.3
exige que la app sea instalable como PWA (RF-17), y el scaffold no tenía manifest
ni service worker todavía. T-07 cierra esa brecha en el modelo antes de construir
las pantallas propias (H-08…H-11, H-14…H-17).

## Opciones consideradas

### Pelotón: dato del soldado vs. atributo propio del arma

- **Dato del soldado** (elegida): el arma no tiene pelotón; se deriva por
  propiedad (`Armamento.peloton_actual`) del soldado que la tiene en mano.
- **Atributo propio del arma**: habría que sincronizarlo manualmente en cada
  entrega/devolución y quedaría desactualizado si el soldado cambia de pelotón
  sin que se mueva el arma — justo el problema que David señaló (P-8 / S-8).

### Control por cantidad: reusar `Armamento` con serie opcional vs. modelo nuevo

- **Modelo nuevo (`Existencia`)** (elegida): `TipoArmamento.control` (SERIE/CANTIDAD)
  decide qué modelo aplica; `Armamento.clean()` exige SERIE, `Existencia.clean()`
  exige CANTIDAD. Existencia se identifica por tipo + compañía + depósito + lote
  opcional, con cantidad como entero.
- **`Armamento` con serie nula y cantidad**: habría que relajar la unicidad de
  serie, la ubicación en mano/depósito ya no aplicaría igual (la cantidad no
  "está en mano de un soldado"), y el modelo mezclaría dos formas de control muy
  distintas en una sola tabla — más confuso de mantener y de validar.

### Préstamo entre compañías: transacción en el modelo vs. capa de servicio aparte

- **Lógica en `Prestamo.clean()`/`save()`** (elegida): `clean()` valida tipo,
  cantidad y saldo disponible; `save()` debita la `Existencia` de origen y
  acredita (o crea) la de destino dentro de una única transacción atómica. Sigue
  el mismo patrón que `Armamento.clean()` ya usaba para validar reglas de negocio
  con consultas a la base de datos.
- **Capa de servicio/vista aparte**: el proyecto todavía no tiene vistas propias
  (H-09 sigue pendiente); una capa de servicio quedaría sin nada que la llame
  hoy, y el admin no podría usarla sin escribir una vista intermedia solo para
  esto. Mantener la regla en el modelo permite operar préstamos ya mismo desde
  el admin de Django, igual que el resto de los datos maestros.

### PWA: manifest/service worker servidos vía `/static/` vs. rutas propias en la raíz

- **Rutas propias (`/manifest.json`, `/sw.js`)** (elegida): dos vistas en
  `config/urls.py` leen los archivos de `static/` y los sirven directo, evitando
  el pipeline de hashing de whitenoise (`ManifestStaticFilesStorage`) y dejando
  el service worker en el scope raíz, requisito para que controle toda la app.
- **Servirlos bajo `/static/...`**: whitenoise renombra los archivos con hash de
  contenido en cada `collectstatic` (`sw.abcd123.js`), rompiendo el registro del
  service worker, que necesita una URL estable; además el scope por defecto de
  un service worker es su propio directorio, así que uno servido bajo
  `/static/` no podría controlar rutas fuera de `/static/`.

## Decisión

Se implementó: `Peloton` (4 por compañía, dato editable del soldado);
`TipoArmamento.control` (SERIE/CANTIDAD) con `Armamento` y `Existencia` cada uno
validando su forma de control; `Prestamo` como transacción atómica sobre
`Existencia`; y `manifest.json`/`sw.js` servidos desde rutas propias en la raíz,
enlazados desde `templates/admin/base_site.html` (el admin sigue siendo la única
UI hasta H-08…H-11).

## Consecuencias

**Lo que ganamos**: el modelo ya refleja las reglas reales del PRD v1.3 —
incluida la única excepción real a NO-3 (la munición sí cruza de compañía)— y es
operable desde ya vía el admin de Django (altas de existencias, préstamos,
pelotones) mientras se construyen las pantallas propias. La PWA es instalable
hoy, aunque sin las plantillas mobile-first todavía.

**Lo que aceptamos a cambio**: `Prestamo.save()` hace más que persistir un
registro (muta `Existencia`), lo cual es una excepción al patrón "modelo simple +
vista con la transacción" que se documenta aquí para que no sorprenda a quien
lea el código después. El ícono de la PWA es un placeholder (`static/icons/icon.svg`)
hasta que se reciba el escudo real del batallón.

**Qué haría que revisáramos esta decisión**: si aparece una segunda operación
(además del préstamo) que necesite mutar `Existencia` de forma compleja o con
reglas de aprobación, convendría extraer un servicio de "movimientos de
existencia" en vez de seguir agregando lógica a `save()` de cada modelo.
