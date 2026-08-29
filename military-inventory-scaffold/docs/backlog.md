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

#### H-03 — Permisos por rol en la interfaz

- **Requerimiento**: RF-01, RF-10
- **Estado**: Pendiente
- **Historia**: Como comandante, quiero que el rol enlace solo vea/busque y registre movimientos, sin tocar datos maestros.
- **Criterios de aceptación**:
  - [ ] El rol enlace no puede crear/editar compañías, depósitos, tipos, usuarios ni dar altas/bajas.
  - [ ] El rol enlace sí puede registrar entregas y devoluciones.
- **Notas técnicas**: mapear `role` a permisos/grupos de Django o gates en las vistas.

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

#### H-08 — Selección de compañía de trabajo

- **Requerimiento**: RF-02
- **Estado**: Pendiente
- **Historia**: Como usuario, al ingresar elijo la compañía con la que trabajo y los listados se filtran a ella.
- **Criterios de aceptación**:
  - [ ] Selector de compañía tras el login; contexto guardado en sesión.
  - [ ] Listados de inventario y soldados filtrados por el contexto; se puede cambiar sin cerrar sesión.

#### H-09 — Entregar y devolver con historial

- **Requerimiento**: RF-10
- **Estado**: Pendiente
- **Historia**: Como administrador o enlace, entrego un arma a un soldado y la recibo de vuelta, dejando rastro.
- **Criterios de aceptación**:
  - [ ] Acción de entrega (depósito → mano) validando que el soldado sea de la compañía del arma.
  - [ ] Acción de devolución (mano → depósito).
  - [ ] Cada acción crea un `Movimiento` con usuario y fecha/hora.
- **Notas técnicas**: el modelo `Movimiento` ya existe; falta el flujo de acción y la transacción.

#### H-10 — Baja de armamento

- **Requerimiento**: RF-11
- **Estado**: Pendiente
- **Criterios de aceptación**:
  - [ ] Solo administrador; registra motivo (dañada/perdida/robada) y fecha.
  - [ ] El arma sale del inventario activo pero conserva su historial.

#### H-11 — Búsqueda global por cualquier dato

- **Requerimiento**: RF-12
- **Estado**: Pendiente (parcial: el admin ya busca por serie/soldado/tipo)
- **Historia**: Como usuario, busco por serie (o cualquier dato) y veo de inmediato tipo, compañía, estado y ubicación.
- **Criterios de aceptación**:
  - [ ] Búsqueda por serie devuelve el estado completo del arma en < 2 s (RNF-01).
  - [ ] Filtros por compañía, depósito y estado.

#### H-12 — Campos personalizados del armamento

- **Requerimiento**: RF-08
- **Estado**: Pendiente (parcial: modelo `CampoPersonalizado` + `datos_extra` ya existen)
- **Criterios de aceptación**:
  - [ ] El administrador define un campo (nombre + tipo texto/número/fecha).
  - [ ] El campo aparece para capturar/ver en cada arma; aplica solo al armamento.

### Épica E-04 — Carga inicial

#### H-13 — Importar el inventario del Excel

- **Requerimiento**: RF-13
- **Estado**: Pendiente
- **Historia**: Como equipo, cargamos el inventario inicial (Excel por compañías) antes de operar.
- **Criterios de aceptación**:
  - [ ] Script/management command que lee el Excel entregado y crea armamento con serie, tipo, compañía y ubicación.
  - [ ] Valida unicidad de serie y reporta conflictos antes de cargar.

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

1. H-09 — Entregar/devolver con historial: es el flujo operativo central y el que más valor da sobre el Excel.
2. H-08 — Selección de compañía: da el marco de trabajo diario a los usuarios.
3. H-11 — Búsqueda global: la pregunta "¿dónde está la serie X?" es la razón de ser del sistema.
4. H-03 — Permisos por rol: cierra el control de acceso antes de abrirlo a los 6 usuarios.
5. H-13 — Carga inicial: para arrancar con datos reales.
