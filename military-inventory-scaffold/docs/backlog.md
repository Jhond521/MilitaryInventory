# Backlog — SIGA

Derivado de `docs/PRD.md`. Cada historia apunta al requerimiento que la origina.

**Convención de estado**: `Pendiente` → `En curso` → `Hecho`.

> Estado del scaffold: el modelo de dominio, el usuario por correo con roles, la
> lista blanca de correos, la siembra de datos maestros y el panel de
> administración de Django ya están construidos y con tests. Las historias
> marcadas ✅ quedaron cubiertas por el esqueleto inicial; el resto está pendiente.

## Fase 1 — v1 (MVP)

### Épica E-01 — Acceso y usuarios

Controlar quién entra y qué puede hacer.

#### H-01 — Usuario por correo con dos roles ✅

- **Requerimiento**: RF-01
- **Estado**: Hecho (scaffold)
- **Historia**: Como comandante, quiero que cada usuario tenga correo y un rol (administrador/enlace).
- **Criterios de aceptación**:
  - [x] Modelo `User` con login por correo y campo `role` (ADMIN/ENLACE).
  - [x] Panel de admin para crear/editar usuarios y asignar rol.

#### H-02 — Lista blanca de correos ✅

- **Requerimiento**: RF-01
- **Estado**: Hecho (scaffold)
- **Criterios de aceptación**:
  - [x] `AllowlistModelBackend` rechaza correos fuera de `AUTHORIZED_EMAILS`.
  - [x] Test que verifica correo autorizado (pasa) y no autorizado (rechazado).

#### H-03 — Permisos por rol en la interfaz ✅

- **Requerimiento**: RF-01, RF-10
- **Estado**: Hecho
- **Historia**: Como comandante, quiero que el rol enlace solo vea/busque y registre movimientos, sin tocar datos maestros.
- **Criterios de aceptación**:
  - [x] El rol enlace no puede crear/editar compañías, depósitos, tipos, usuarios ni dar altas/bajas.
  - [x] El rol enlace sí puede registrar entregas y devoluciones.
- **Notas técnicas**: `apps/accounts/admin_mixins.py` define los gates por rol (no grupos/permisos
  de Django — con solo 2 roles fijos, comprobar `user.role` directamente es más simple y evita
  depender de `auth.Permission`/grupos que este proyecto nunca asigna):
  - `ViewOnlyForEnlaceMixin` (Unidad, Compañía, Depósito, Pelotón, Soldado, Tipo de armamento,
    Campo personalizado, Armamento, Movimiento, Existencia): cualquier usuario autorizado ve;
    solo Administrador agrega/edita/borra.
  - `MovimientoRegistrableMixin` (Préstamo): agregar también es "registrar un movimiento"
    (RF-15) — ambos roles pueden; editar/borrar sigue siendo solo Administrador.
  - `AdminOnlyMixin` (Usuarios): Enlace ni siquiera ve la sección — gestión de cuentas es
    sensible y el PRD no pide que Enlace la vea.
  - Las acciones de entrega/devolución de `ArmamentoAdmin` (H-09) se validan contra
    `has_view_permission`, no `has_change_permission` — RF-10 autoriza a Enlace a registrar
    movimientos aunque no tenga permiso de edición sobre Armamento; Django ya sirve el
    detalle de solo lectura cuando hay `view` pero no `change`.
  - Al implementar esto se corrigieron dos brechas reales: `has_module_permission` (por
    defecto usa permisos reales de Django, que este proyecto nunca asigna, así que ocultaría
    toda la app hasta a un Administrador no-superusuario) se sobreescribió con la misma
    lógica de rol; y `PrestamoAdmin` pedía elegir "usuario" en una lista al registrar un
    préstamo — ahora se asigna solo con `request.user` (RNF-03).
  - **Supuesto**: "datos maestros" se interpretó en sentido amplio (incluye Soldado y
    Pelotón, agrupados como tal en la Épica E-02 del backlog, aunque el PRD no los nombra
    en la lista literal de RF-01/sección 3) — a confirmar con David si Enlace necesita poder
    reasignar el pelotón de un soldado directamente (cambia con frecuencia, S-8).

### Épica E-02 — Datos maestros

Compañías, depósitos, tipos y soldados.

#### H-04 — CRUD de compañías, depósitos y tipos ✅

- **Requerimiento**: RF-03, RF-04, RF-05
- **Estado**: Hecho (scaffold, vía admin)
- **Criterios de aceptación**:
  - [x] Modelos y admin para Compañía, Depósito y TipoArmamento; se pueden crear nuevos.

#### H-05 — Siembra de datos iniciales ✅

- **Requerimiento**: RF-03, RF-04, RF-05
- **Estado**: Hecho (scaffold)
- **Criterios de aceptación**:
  - [x] `seed_initial` crea 1 unidad, 7 compañías, 2 depósitos y 23 tipos, de forma idempotente.

#### H-06 — Registro de soldados ✅

- **Requerimiento**: RF-06
- **Estado**: Hecho (scaffold, vía admin)
- **Criterios de aceptación**:
  - [x] Soldado con apellidos/nombres y una sola compañía; no es usuario.

### Épica E-03 — Armamento y movimientos

El corazón del sistema.

#### H-07 — Alta de armamento con serie ✅

- **Requerimiento**: RF-07
- **Estado**: Hecho (scaffold, vía admin)
- **Criterios de aceptación**:
  - [x] Arma con serie única, tipo y compañía; ubicación por defecto "en depósito".
  - [x] Validación de coherencia ubicación/soldado/depósito en `clean()`.

#### H-08 — Selección de compañía de trabajo ✅

- **Requerimiento**: RF-02
- **Estado**: Hecho
- **Historia**: Como usuario, al ingresar elijo la compañía con la que trabajo y los listados se filtran a ella.
- **Criterios de aceptación**:
  - [x] Selector de compañía tras el login; contexto guardado en sesión.
  - [x] Listados de inventario y soldados filtrados por el contexto; se puede cambiar sin cerrar sesión.
- **Notas técnicas**: `CompaniaContextMiddleware` (`apps/inventory/middleware.py`) manda a
  `/compania/` (`apps/inventory/views.py::elegir_compania`) a quien no tiene compañía en
  sesión; `CompaniaContextoMixin` (`admin.py`) filtra por defecto el changelist de
  Armamento y Soldado. Header ("Compañía: X — ver todas — cambiar compañía") vía
  `templates/admin/base_site.html` + `context_processors.compania_actual`. Es solo un
  valor por defecto (S-2): "ver todas" y el filtro explícito de compañía lo desactivan.

#### H-09 — Entregar y devolver con historial ✅

- **Requerimiento**: RF-10
- **Estado**: Hecho (vía acciones del admin)
- **Historia**: Como administrador o enlace, entrego un arma a un soldado y la recibo de vuelta, dejando rastro.
- **Criterios de aceptación**:
  - [x] Acción de entrega (depósito → mano) validando que el soldado sea de la compañía del arma.
  - [x] Acción de devolución (mano → depósito).
  - [x] Cada acción crea un `Movimiento` con usuario y fecha/hora.
- **Notas técnicas**: `Armamento.entregar()`/`.devolver()` (transaccionales, en `models.py`) hacen el
  cambio de ubicación y crean el `Movimiento`; expuestos como acciones masivas del admin
  ("Entregar a un soldado" / "Devolver a depósito") con una página intermedia
  (`templates/admin/inventory/armamento/`) para elegir soldado/depósito y observación.
  Falta una pantalla guiada propia (H-08…H-11) y el filtrado de permisos por rol (H-03).

#### H-10 — Baja de armamento ✅

- **Requerimiento**: RF-11
- **Estado**: Hecho (vía acción del admin)
- **Criterios de aceptación**:
  - [x] Solo administrador; registra motivo (dañada/perdida/robada) y fecha.
  - [x] El arma sale del inventario activo pero conserva su historial.
- **Notas técnicas**: `Armamento.dar_de_baja(motivo, fecha, usuario, observacion="")` (transaccional,
  en `models.py`) marca `estado=BAJA` y crea un `Movimiento` tipo BAJA (RNF-03) — funciona sin
  importar si el arma está en mano o en depósito, a diferencia de entregar/devolver. `clean()`
  exige motivo y fecha siempre que `estado=BAJA` (aunque se edite por el form crudo del admin,
  no solo por esta acción), y `entregar()` ahora rechaza un arma que no esté `ACTIVO`. Expuesta
  como acción masiva del admin ("Dar de baja") con página intermedia
  (`templates/admin/inventory/armamento/dar_de_baja.html`); a diferencia de H-09, esta acción
  declara `permissions=["change"]` para que ni siquiera aparezca en el desplegable de Enlace
  (RF-11 es "solo administrador", no ambos roles como RF-10).

#### H-11 — Búsqueda global por cualquier dato ✅

- **Requerimiento**: RF-12
- **Estado**: Hecho (vía el buscador del admin)
- **Historia**: Como usuario, busco por serie (o cualquier dato) y veo de inmediato tipo, compañía, estado y ubicación.
- **Criterios de aceptación**:
  - [x] Búsqueda por serie devuelve el estado completo del arma en < 2 s (RNF-01).
  - [x] Filtros por compañía, depósito y estado.
- **Notas técnicas**: `ArmamentoAdmin.search_fields` (RF-12: "por cualquier dato") cubre
  serie, soldado, tipo, compañía, depósito y campos personalizados (`datos_extra`, JSON).
  `numero_serie` ya tenía índice de BD (RNF-01) y el changelist ya muestra tipo, compañía,
  ubicación, depósito, soldado, pelotón y estado en cada fila. Al arreglar la búsqueda en
  `datos_extra` se encontró y corrigió un bug real: `JSONField` escapa por defecto los
  acentos como `\uXXXX` (`ensure_ascii=True`), lo que rompía la búsqueda de texto en
  español con tildes — se agregó `UnicodeJSONEncoder` (`models.py`) para guardarlos tal
  cual.

#### H-12 — Campos personalizados del armamento ✅

- **Requerimiento**: RF-08
- **Estado**: Hecho
- **Criterios de aceptación**:
  - [x] El administrador define un campo (nombre + tipo texto/número/fecha).
  - [x] El campo aparece para capturar/ver en cada arma; aplica solo al armamento.
- **Notas técnicas**: `ArmamentoAdmin.get_form()`/`get_fieldsets()` (`apps/inventory/admin.py`)
  generan un campo de formulario propio (texto/número/fecha según `CampoPersonalizado.tipo`)
  por cada `CampoPersonalizado` sembrado, agrupados en una sección "Campos personalizados";
  `save_model()` los guarda/quita de `Armamento.datos_extra`. El primer diseño (un campo de
  formulario por cada uno, sea o no editable) chocó con una limitación real de Django: cuando
  Enlace solo tiene permiso de "view", el admin excluye TODOS los campos reales del modelo y
  cambia a un modo de solo lectura que solo sabe leer atributos reales o métodos del
  ModelAdmin — nunca entradas sueltas de `form.fields` — así que esos campos dinámicos se
  veían como "Campo 1: None" en vez del valor real. La solución: cuando el usuario no tiene
  permiso de "change", en vez de los campos por uno se muestra un único método de solo lectura
  (`campos_personalizados_resumen`) con el resumen real. De paso, otro intento de arreglar el
  formulario ("fields=None" para que `ModelAdmin.get_form()` no derive `fields` desde
  `get_fieldsets()`, que incluye los campo\_&lt;pk&gt; y no son campos reales) causó
  recursión infinita: `get_fieldsets()`/`get_fields()` internamente llaman a `self.get_form()`,
  que siempre resuelve al método sobreescrito — la solución fue filtrar la lista de `fields`
  ya recibida en vez de recalcularla llamando a esos métodos.

### Épica E-04 — Carga inicial

#### H-13 — Importar el inventario del Excel ✅

- **Requerimiento**: RF-13
- **Estado**: Hecho (a falta del Excel real para verificar contra él)
- **Historia**: Como equipo, cargamos el inventario inicial (Excel por compañías) antes de operar.
- **Criterios de aceptación**:
  - [x] Script/management command que lee el Excel entregado y crea armamento con serie, tipo, compañía y ubicación.
  - [x] Valida unicidad de serie y reporta conflictos antes de cargar.
- **Notas técnicas**: `python manage.py importar_armamento archivo.xlsx [--deposito NOMBRE] [--dry-run]`
  (`apps/inventory/management/commands/importar_armamento.py`). Valida el archivo completo
  antes de crear nada — todo o nada: si hay un solo conflicto (serie repetida en el archivo
  o ya existente en la base, tipo/depósito no reconocido, serie o denominación vacía), no crea
  ningún registro y reporta todos los conflictos encontrados. Todo lo importado queda "en
  depósito" (asignar soldados es un paso posterior, RF-10).
  - **Supuesto (a confirmar contra el Excel real, P-1/P-6 aún pendientes)**: David todavía no
    ha entregado `ACTIVOS FIJOS COMPAÑIA.xlsx`, así que el comando asume una estructura
    normalizada razonable (documentada en su docstring) en vez del layout real de "bloques
    por denominación" del archivo — una hoja por compañía, fila de encabezados con columnas
    Serie/Denominación/Depósito. Cuando llegue el archivo real, validar contra él y, si el
    layout no calza, adaptar la detección de encabezados/bloques del comando (el núcleo de
    validación y reporte de conflictos debería servir igual).
  - Al escribir esto se notó que el catálogo sembrado (`seed_initial`) no tenía Pistolas ni
    Visores nocturnos pese a estar en el Anexo A del PRD — se agregaron 5 tipos nuevos (todos
    por SERIE): PISTOLA PX4 STORM, PISTOLA PRIETO BERETTA, VISOR NOCTURNO AN PVS 14, VISOR
    NOCTURNO AN PVS 7B, VISOR NOCTURNO DUAL/DOBLE (24 → 29 tipos).

## Fase 2 — Siguiente

- H-20 — Módulo de importación de Excel autoservicio (que David suba y cargue) (RF-13)
- H-21 — Reportes/exportes por compañía y depósito
- H-22 — Sub-depósitos por compañía con responsable (P-3)
- H-23 — Tablero de resumen (conteos por compañía/estado/ubicación)

## Fase 3 — Algún día

- Multi-unidad con configurador de unidades
- App móvil / vista optimizada para celular
- Firma o acuse de entrega del soldado
- Escaneo de código o serie con la cámara

## Trabajo técnico

- [x] T-01 — Scaffold Django, modelos, migraciones, tests, siembra, admin
- [ ] T-02 — Configurar despliegue en Railway (variables, Postgres, primer deploy + seed)
- [ ] T-03 — CI (tests + ruff en cada push) — opcional, no incluido en el scaffold
- [ ] T-04 — Definir política de respaldo del Postgres (RNF-06)
- [ ] T-05 — Cerrar la lista de 6 correos y el rol de cada persona (P-1, P-2)
- [ ] T-06 — Habilitar PWA: web app manifest + service worker, íconos (escudo), responsive mobile-first, navegación inferior (RF-17, RNF-04)

## Actualizaciones v1.1–v1.3 (nuevas historias)

Derivadas del PRD actualizado. T-07 (Hecho) alineó el modelo del scaffold; las
historias H-14…H-17 siguen pendientes en su parte de interfaz/UI.

- H-14 — Pelotones: 4 por compañía; pelotón como dato del soldado (editable), mostrado en inventario/detalle/entrega; el arma deriva su pelotón del soldado (RF-16)
  - **Estado**: modelo listo (T-07) — `Peloton`, `Soldado.peloton` (validado contra su compañía) y `Armamento.peloton_actual` (derivado, `None` en depósito). Falta mostrarlo en pantallas propias (H-08…H-11).
- H-15 — Existencias por cantidad: munición y cascos por cantidad; carga desde "CARGOS SAP" (RF-14)
  - **Estado**: modelo listo (T-07) — `Existencia` (tipo + compañía + depósito + lote opcional + cantidad), gestionable desde el admin. Falta el importador desde "CARGOS SAP" (fase siguiente) y una pantalla de ajuste guiado.
- H-16 — Préstamo de munición entre compañías con saldos y trazabilidad (RF-15)
  - **Estado**: modelo listo (T-07) — `Prestamo` ajusta atómicamente las existencias de origen/destino y valida tipo, cantidad y saldo disponible; gestionable desde el admin. Falta la pantalla guiada de préstamo.
- H-17 — App móvil responsive e instalable (PWA): manifest, service worker, íconos, navegación móvil (RF-17)
  - **Estado**: parcialmente cubierto por T-07 (manifest + service worker servidos y enlazados desde el admin, ícono placeholder). Faltan las plantillas mobile-first y la navegación inferior.
- T-07 — Ajustar modelos del scaffold: separar control por SERIE vs CANTIDAD, agregar Pelotón, existencias y préstamos
  - **Estado**: Hecho — ver detalle de estado en cada historia (H-14…H-17) arriba.

## Orden sugerido para arrancar

Las 5 completadas (✅ arriba). Siguiente candidato natural: H-10 (baja de
armamento, cierra la Épica E-03) o H-12 (campos personalizados, ya tiene el
modelo listo desde el scaffold).

1. H-09 — Entregar/devolver con historial: es el flujo operativo central y el que más valor da sobre el Excel. ✅
2. H-08 — Selección de compañía: da el marco de trabajo diario a los usuarios. ✅
3. H-11 — Búsqueda global: la pregunta "¿dónde está la serie X?" es la razón de ser del sistema. ✅
4. H-03 — Permisos por rol: cierra el control de acceso antes de abrirlo a los 6 usuarios. ✅
5. H-13 — Carga inicial: para arrancar con datos reales (a falta del Excel real de David). ✅
