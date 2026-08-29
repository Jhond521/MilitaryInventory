# PRD — SIGA: Sistema de Inventario y Gestión de Armamento

| | |
|---|---|
| **Estado** | En revisión (v1.3 — móvil e instalable) |
| **Autor** | John Cuervo (para David Bolaños — Batallón de Selva No. 52) |
| **Última actualización** | 2026-08-27 |
| **Versión** | v1.3 |

> **Cambios v1.3**: la aplicación debe **funcionar bien desde el celular** y ser
> **instalable** (PWA — se agrega a la pantalla de inicio y se abre como una app),
> con navegación adaptada a móvil (ver RF-17 y RNF-04).
>
> **Cambios v1.2** (feedback de David al diseño y archivo de munición):
> se agrega el concepto de **Pelotón** (4 por compañía; es un **dato del soldado**,
> editable manualmente porque cambia con frecuencia); el pelotón del arma se **deriva**
> del soldado que la tiene y se muestra en inventario, detalle y entrega. En la UI, la
> columna "Ubicación" del inventario se llama **"Responsable"**. La munición del archivo
> de consumo se lleva por **MATERIAL + cantidad** (columna "CARGOS SAP" = cantidad); el
> **número de lote** está pendiente (David lo agregará).
>
> **Cambios v1.1** (revisión de David y análisis del Excel de inventario):
> la munición se controla **por lote y cantidad** y **sí se presta entre compañías**;
> el material se controla en **dos formas** (por serie individual y por cantidad);
> roles definidos (comandante, auxiliar y bodegueros = administradores; enlaces =
> restringido); no se modelan sub-depósitos; y el catálogo real de material es más
> amplio que la lista inicial (incluye visores nocturnos y cascos).

## 1. Resumen

SIGA es una aplicación web para llevar el inventario de material de guerra de un
batallón. Cada elemento serializado (fusil, ametralladora, mortero, visor, etc.)
se registra por su **número de serie**, sabe a qué **compañía** pertenece y dónde
está (en mano de un soldado o guardado en un depósito). La **munición** y los
elementos sin serie (p. ej. cascos) se controlan **por cantidad**, sabiendo qué
compañía tiene cuánto. Un grupo pequeño y restringido de usuarios busca cualquier
elemento y registra entregas, devoluciones y préstamos. Cuando exista, reemplaza
el control en Excel por una fuente única, buscable y con trazabilidad.

## 2. Problema

Hoy el control del material del batallón vive en hojas de Excel separadas por
compañía (una hoja por cada una: ASPC, A, B, C, D, E, IR), con bloques por tipo de
material. Eso hace lento y frágil responder la pregunta que más importa —*"¿dónde
está la serie X y quién la tiene?"*—, no controla quién modifica la información, no
deja rastro de las entregas/devoluciones, y no refleja bien la munición, que se
presta entre compañías y cambia de cantidad. En una unidad donde el material se
identifica y audita por su serie (o por cantidad, en el caso de munición), esa
opacidad es un riesgo operativo y de responsabilidad.

## 3. Usuarios

Solo **6 personas** usan la aplicación (acceso restringido por lista de correos).
Los soldados **no** son usuarios: son registros a los que se les asigna material.

| Perfil | Descripción | Rol en el sistema |
|---|---|---|
| Comandante | David — mando de todos. | **Administrador** |
| Auxiliar de bodegas | Apoyo en la gestión. | **Administrador** |
| Bodegueros / administradores de depósito (2) | Uno por cada depósito físico (Apiay y Caruru). | **Administrador** |
| Enlaces (2) | Encargados de los movimientos de material. | **Restringido (enlace)** |

- **Administrador**: control total — crear/editar datos maestros (compañías,
  depósitos, tipos, campos personalizados, usuarios), altas y bajas de material,
  y registrar movimientos.
- **Enlace (restringido)**: ver/buscar y **registrar movimientos** (entregas,
  devoluciones y préstamos de munición). No crea ni borra datos maestros.

## 4. Objetivos y criterios de éxito

**Objetivos**

- O-1: Fuente única del inventario del batallón, buscable por número de serie.
- O-2: Saber en todo momento el estado y ubicación de cada elemento serializado, y
  qué compañía tiene qué cantidad de munición.
- O-3: Restringir quién modifica la información y dejar rastro de entregas,
  devoluciones y préstamos.

**Criterios de éxito** (medibles)

- CE-1: Buscar por número de serie devuelve, en < 2 s, tipo, compañía, estado y
  ubicación actual (soldado y compañía, o depósito).
- CE-2: El inventario serializado del Excel (aprox. 1.800 ítems) queda cargado y
  consultable antes de arrancar la operación.
- CE-3: Solo los correos de la lista autorizada pueden ingresar.
- CE-4: Toda entrega, devolución o préstamo queda registrada con elemento/cantidad,
  origen, destino, usuario y fecha/hora.

## 5. No-objetivos

- NO-1: **No** hay gestión de unidades en la interfaz. Existe una sola unidad
  (Batallón de Selva No. 52), sembrada; el modelo queda normalizado para varias
  unidades a futuro, sin configurador ahora.
- NO-2: **No** se agregan atributos personalizados a soldados ni a tipos de material.
  Los campos personalizados solo aplican al material serializado (armamento).
- NO-3: **No** se transfiere material **serializado** entre compañías; un arma
  pertenece a una compañía y solo a esa. (La **munición** sí se presta entre
  compañías — ver RF-15.)
- NO-4: **No** hay app móvil nativa en v1 (la web debe verse bien en celular).
- NO-5: **No** se modelan sub-depósitos por compañía dentro de cada depósito; basta
  con depósito + compañía dueña (decisión de David, P-3).
- NO-6: **No** hay reportes/tableros analíticos avanzados en v1 (más allá de
  búsqueda y listados filtrables).

## 6. Requerimientos funcionales

### RF-01 — Acceso restringido por lista de correos y rol
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Solo los correos de la lista autorizada pueden autenticarse; otro correo se rechaza.
- [ ] Cada usuario tiene un rol: **administrador** o **enlace**.
- [ ] El rol determina qué acciones habilita la interfaz.

### RF-02 — Selección de compañía de trabajo al ingresar
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Tras autenticarse, el usuario elige una compañía como contexto de trabajo.
- [ ] El contexto filtra por defecto los listados a esa compañía.
- [ ] Se puede cambiar de compañía sin cerrar sesión.

### RF-03 — Gestión de compañías
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Arranca con las 7 compañías: ASPC, A (Alcatraz), B (Bisonte), C (Córsega),
  D (Delta), E (Escorpión), IR — *mapeo de nombres a confirmar (P-5)*.
- [ ] Un administrador puede crear/editar una compañía; un enlace no.

### RF-04 — Gestión de depósitos
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Arranca con 2 depósitos: Apiay (cantón) y Caruru (batallón).
- [ ] Los depósitos son agnósticos a la compañía; sin sub-depósitos internos (NO-5).

### RF-05 — Catálogo de tipos de material con dos formas de control
**Prioridad**: Alta
**Descripción**: Como administrador, quiero un catálogo de tipos de material,
ampliable, donde cada tipo se controla **por serie** (individual) o **por cantidad**.
**Criterios de aceptación**:

- [ ] Cada tipo indica su forma de control: **SERIE** (una fila por unidad con serie
  única) o **CANTIDAD** (se lleva por existencias/lote, sin serie individual).
- [ ] El catálogo arranca con las denominaciones reales del Excel (ver Anexo A),
  agrupadas por categoría (fusil, ametralladora, lanzagranadas, mortero, pistola,
  visor nocturno, casco, munición).
- [ ] Un administrador puede crear tipos nuevos y elegir su forma de control.

### RF-06 — Gestión de soldados
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Un soldado tiene, mínimo, Apellidos y Nombres, una sola Compañía y un **Pelotón**.
- [ ] El pelotón del soldado se edita manualmente (cambia con frecuencia).
- [ ] Los soldados no son usuarios y tienen esquema fijo (sin campos personalizados).

### RF-07 — Alta de material serializado con número de serie
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Cada elemento serializado se registra con: número de serie (único), tipo y
  compañía dueña.
- [ ] Un elemento no asignado queda "en depósito" en el depósito indicado.
- [ ] Todo el material serializado de una compañía existe con su serie, esté en mano
  o en depósito.

### RF-08 — Campos personalizados en el material serializado
**Prioridad**: Media
**Criterios de aceptación**:

- [ ] Un administrador define un campo personalizado (texto, número o fecha).
- [ ] Aplica **solo** al material serializado (no a soldados ni a tipos).

### RF-09 — Ubicación y estado del material serializado
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Un elemento serializado está **en mano** (soldado de su misma compañía) o
  **en depósito** (Apiay, Caruru u otro).
- [ ] La búsqueda muestra el soldado y compañía, o el depósito, según el caso.

### RF-10 — Movimientos de material serializado: entregar y devolver
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Entregar mueve un elemento de "en depósito" a "en mano" de un soldado **de la
  misma compañía** dueña del arma.
- [ ] Devolver mueve un elemento de "en mano" a "en depósito".
- [ ] Cada movimiento queda registrado con elemento, soldado, tipo, usuario y fecha/hora.
- [ ] Administrador y enlace pueden registrar movimientos.

### RF-11 — Baja de material
**Prioridad**: Media
**Criterios de aceptación**:

- [ ] Solo administrador; registra motivo (dañado/perdido/robado) y fecha.
- [ ] El elemento sale del inventario activo pero conserva su historial.

### RF-12 — Búsqueda global por cualquier dato (principalmente serie)
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Buscar por serie devuelve tipo, compañía, estado y ubicación.
- [ ] Busca también por tipo, soldado, compañía, depósito y campos personalizados.
- [ ] Resultados filtrables por compañía, depósito y estado.

### RF-13 — Carga inicial del inventario serializado desde Excel
**Prioridad**: Alta
**Criterios de aceptación**:

- [ ] Se cargan los ~1.800 ítems serializados del Excel (una hoja por compañía,
  bloques por denominación), con serie, tipo, compañía y ubicación inicial (depósito).
- [ ] Enfoque v1: John hace la carga con un script de importación; valida unicidad de
  serie y reporta conflictos antes de cargar.

### RF-14 — Existencias por cantidad (munición y elementos sin serie)
**Prioridad**: Alta
**Descripción**: Como usuario, quiero llevar por **cantidad** los elementos que no
tienen serie individual (munición por lote; cascos), sabiendo cuánto tiene cada
compañía y en qué depósito.
**Criterios de aceptación**:

- [ ] Una existencia se identifica por tipo (y **número de lote**, en munición),
  compañía, ubicación (depósito) y **cantidad**.
- [ ] Se puede aumentar/disminuir la cantidad con su registro de movimiento.
- [ ] Los cascos "SIN SERIE" del Excel se cargan como existencias por cantidad por
  compañía.
- [ ] En el archivo de consumo (munición, magazines, cañones de repuesto, etc.) la
  cantidad es la columna **"CARGOS SAP"**; el número de lote se agregará (pendiente, P-6).

### RF-15 — Préstamo de munición entre compañías
**Prioridad**: Alta
**Descripción**: Como usuario, quiero prestar munición de una compañía a otra y saber
en todo momento qué cantidad tiene cada compañía, según cómo se entregó.
**Criterios de aceptación**:

- [ ] Un movimiento de préstamo traslada una **cantidad** de munición (de un lote)
  de la compañía origen a la compañía destino.
- [ ] El sistema refleja la cantidad resultante en cada compañía tras el préstamo.
- [ ] Cada préstamo queda registrado con lote, cantidad, compañía origen, compañía
  destino, usuario y fecha/hora (trazabilidad, RNF-03).
- [ ] A diferencia del material serializado, la munición **sí** cruza entre compañías.

### RF-16 — Pelotones
**Prioridad**: Alta
**Descripción**: Como usuario, quiero manejar el pelotón para saber en qué pelotón está
cada soldado y, por él, cada arma entregada.
**Criterios de aceptación**:

- [ ] Cada compañía tiene 4 pelotones (p. ej. Alcatraz 1, Alcatraz 2, Alcatraz 3, Alcatraz 4).
- [ ] Un soldado pertenece a **exactamente un** pelotón (dentro de su compañía).
- [ ] El **arma no tiene pelotón propio**: su pelotón se **deriva** del soldado que la
  tiene en mano; en depósito no muestra pelotón.
- [ ] El pelotón se muestra en el inventario (columna), en el detalle del arma y en la
  entrega/devolución.

### RF-17 — Acceso móvil e instalable (PWA)
**Prioridad**: Alta
**Descripción**: Como usuario, quiero usar SIGA desde el celular e instalarla como una
app, para operar en terreno sin depender del computador.
**Criterios de aceptación**:

- [ ] La misma aplicación web funciona bien en celular (diseño responsive): búsqueda,
  inventario, detalle, entrega/devolución y munición usables con una mano.
- [ ] Es **instalable** (PWA): se puede "agregar a la pantalla de inicio" y abrir como
  app, con nombre e ícono propios (escudo del batallón).
- [ ] En móvil hay navegación inferior (inventario, munición, soldados, movimientos) y
  las acciones cumplen tamaños táctiles adecuados (mínimo 44 px).
- [ ] No requiere publicarse en tiendas de aplicaciones (se instala desde el navegador).

## 7. Requerimientos no funcionales

| ID | Categoría | Requerimiento | Cómo se verifica |
|---|---|---|---|
| RNF-01 | Rendimiento | Búsqueda por serie < 2 s con ~1.800+ ítems. | Prueba con la carga real. |
| RNF-02 | Seguridad | Acceso solo por lista de correos; acciones por rol; HTTPS. | Correo no autorizado (rechazado); acción de enlace sobre datos maestros (bloqueada). |
| RNF-03 | Trazabilidad | Todo movimiento (entrega/devolución/préstamo/baja) queda con usuario y fecha/hora, sin borrado silencioso. | Revisar historial tras cada tipo de movimiento. |
| RNF-04 | Usabilidad / Móvil | Interfaz en español, responsive (escritorio y celular) e instalable como PWA, usable por personal no técnico. | Prueba en celular por las 6 personas; instalar en pantalla de inicio. |
| RNF-05 | Disponibilidad | Accesible por internet; tolerante a conectividad intermitente (Apiay/Caruru). | Verificar acceso desde ambas sedes. |
| RNF-06 | Respaldo | Respaldo periódico del inventario. | Confirmar respaldo y restauración de prueba. |

## 8. Flujo principal

**Buscar un arma y ver quién la tiene**

1. El usuario ingresa y elige la compañía de trabajo.
2. Escribe el número de serie en la búsqueda.
3. Ve tipo, compañía, estado y ubicación; si está en mano, el soldado y compañía; si
   en depósito, cuál.

**Entregar un arma a un soldado**

1. El usuario ubica el arma por serie (en depósito).
2. Elige "Entregar" y un soldado de la misma compañía del arma.
3. El sistema la pasa a "en mano" y registra el movimiento.

**Prestar munición a otra compañía**

1. El usuario elige el lote de munición y la compañía origen (con existencia).
2. Indica cantidad y compañía destino.
3. El sistema descuenta de origen, suma a destino y registra el préstamo.

## 9. Datos

Fuente inicial: el Excel `ACTIVOS FIJOS COMPAÑIA.xlsx`, con **7 hojas** (una por
compañía) y bloques por denominación. Contiene ~1.800 ítems, casi todos con número
de serie individual; los **cascos** figuran "SIN SERIE" (se llevan por cantidad). La
**munición no está** en ese archivo y se incorporará aparte (por lote y cantidad).
El sistema maneja material de guerra (series, tipos, ubicaciones, cantidades) y datos
personales básicos de soldados (nombres y compañía) y de los 6 usuarios (correo). Por
la naturaleza militar, el acceso es restringido, los movimientos son trazables y la
información se respalda. Los elementos dados de baja se conservan (no se eliminan).

## 10. Restricciones y dependencias

- **Técnicas**: web accesible desde dos sedes remotas con conectividad limitada;
  escala pequeña (6 usuarios, ~2.000 ítems serializados + existencias de munición).
- **De negocio / plazos**: reemplazar el Excel y arrancar con la data cargada. Falta
  la lista completa de 6 correos con su rol, y el archivo/fuente de munición.
- **Integraciones externas**: carga inicial desde Excel.

## 11. Alcance por fases

| Fase | Contenido | Requerimientos |
|---|---|---|
| v1 (MVP) | Acceso + roles, selección de compañía, CRUD de datos maestros, pelotones, material serializado (alta/ubicación/estado/movimientos/baja), existencias por cantidad y préstamo de munición, búsqueda, campos personalizados, carga inicial serializada, y app **móvil responsive e instalable (PWA)**. | RF-01 a RF-17 |
| Siguiente | Importador de Excel autoservicio, carga de munición inicial, reportes/exportes, tablero de resumen por compañía, acuse de entrega. | — |
| Algún día | Multi-unidad con configurador, app móvil, escaneo de serie. | — |

## 12. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Series duplicadas/inconsistentes en el Excel. | Carga sucia. | Validar unicidad e informar conflictos antes de cargar. |
| Denominaciones escritas distinto entre hojas (p. ej. "VOSIRES"/"VISORES", "AMETRALALDORAS"). | Catálogo con duplicados. | Normalizar denominaciones al cargar; mapa de equivalencias. |
| Falta la fuente de munición y la lista completa de correos/roles. | Bloquea parte del v1. | David entrega ambos antes del despliegue (P-1, P-6). |
| Conectividad limitada en Apiay/Caruru. | Uso interrumpido. | Hosting confiable; UI liviana. |

## 13. Supuestos

- S-1: "Unidad" del soldado = su **compañía**. Una sola unidad (Batallón de Selva No. 52).
- S-2: La selección de compañía al ingresar es **contexto de trabajo**, no restricción
  de permisos: los 6 usuarios ven todas las compañías.
- S-3: **Administrador** = comandante, auxiliar y bodegueros; **enlace** = los 2 de
  movimientos (confirmado por David, P-2).
- S-4: La munición se controla por **lote + cantidad** y **se presta entre compañías**
  (confirmado por David, P-4). El material serializado no se presta entre compañías.
- S-5: Las bajas son poco frecuentes (daño, pérdida o robo).
- S-6: La carga inicial serializada la hace John con un script desde el Excel.
- S-7: Los cascos "SIN SERIE" se llevan por cantidad por compañía (no se prestan entre
  compañías salvo indicación contraria).
- S-8: El **pelotón** es un dato del soldado (4 por compañía), editable manualmente; el
  arma no tiene pelotón propio, se deriva del soldado que la tiene (confirmado por David).

## 14. Preguntas abiertas

| # | Pregunta | Quién decide | Para cuándo |
|---|---|---|---|
| P-1 | Los 6 correos completos y su rol. Hasta ahora: Davidbg91, Jhon1991losada, Pololuis500. | David | Antes del despliegue |
| P-5 | Confirmar el mapeo de códigos a nombres: A=Alcatraz, B=Bisonte, C=Córsega, D=Delta, E=Escorpión (ASPC e IR igual). | David | Antes de la carga |
| P-6 | Munición: el archivo trae MATERIAL + cantidad (CARGOS SAP), falta el **número de lote** por cada material/compañía. David lo agregará. | David | Antes de la carga de munición |
| P-7 | ¿Los cascos y otros elementos sin serie se prestan entre compañías, o solo la munición? | David | Fase siguiente |

## Anexo A — Catálogo real de material (del Excel), por categoría

- **Fusiles** (serie): GALIL AR, GALIL AR PLUS, ACE-23, FUSIL AR.
- **Ametralladoras** (serie): M-60 E-4, M-249, M-2 HB QCB (.50).
- **Lanzagranadas** (serie): TIPO MK1, MK-19 MOD-3, TIPO MGL.
- **Morteros** (serie): 81 mm (C-576 T/C), SOLTAN, B-500, C-06 L/A, tipo comando.
- **Pistolas** (serie): PX4 STORM, PRIETO BERETTA.
- **Visores nocturnos** (serie): AN PVS 14, AN PVS 7B, duales/dobles.
- **Cascos** (cantidad): BALISTICO HELMET KEVLAR N. III (SIN SERIE).
- **Munición y consumibles** (cantidad, columna CARGOS SAP; lote pendiente): munición
  5.56 mm, 5.56 eslabonada, 7.62 mm, 7.62 eslabonada, 12.7×99 (.50), 9 mm; granadas
  40 mm (40×46 / 40×53 HE), IMC 60 mm y 81 mm, de mano M26, de humo, de práctica;
  además magazines (MAGAZINE,CARTRIDGE), compás magnético y cañones de repuesto (M60/.50).
