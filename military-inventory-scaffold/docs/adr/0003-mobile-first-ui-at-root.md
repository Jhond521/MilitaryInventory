# ADR-0003: La UI móvil pasa a ser la superficie principal; el admin se muda a /admin/

- **Fecha**: 2026-08-30
- **Estado**: Aceptada
- **Decide**: John Cuervo

## Contexto

Hasta ahora, toda la app *era* el admin de Django, montado en la raíz (`/`) —
H-08 (compañía de trabajo), H-09 (entregar/devolver), H-10 (baja) y H-11
(búsqueda) se implementaron como acciones/formularios intermedios del admin,
per `CLAUDE.md`. T-06/H-17 (PWA mobile-first) seguían pendientes de pantallas
propias.

Un canvas de diseño ("SIGA · Batallón 52") ya mockeaba la dirección visual
mobile-first (Inventario + flujo de Entrega, estilo "sobrio/militar
utilitario": Oswald + IBM Plex Sans/Mono, paleta oscura/roja/crema). Este ADR
documenta la decisión de construir esas pantallas y hacerlas la superficie
principal de uso diario, en vez de un añadido aparte.

## Opciones consideradas

### Dónde vive la nueva UI móvil

- **Toma la raíz `/`; el admin se muda a `/admin/`** (elegida): estándar de
  Django, y hace que lo primero que ve cualquiera de los 6 usuarios al entrar
  sea la pantalla pensada para el uso diario (RF-02, RF-10, RF-12), con el
  admin siempre disponible para datos maestros.
- **UI móvil en una ruta nueva (`/app/`), admin se queda en `/`**: no requiere
  tocar `config/urls.py` ni `CompaniaContextMiddleware`, pero nadie llega ahí
  por accidente — los 6 usuarios seguirían aterrizando en el admin todos los
  días, exactamente lo que se quiere dejar de hacer.

### Alcance de las pantallas nuevas

- **Las 4 del bottom nav (Inventario, Movimientos, Soldados, Munición) +
  Entregar y Devolver** (elegida): el canvas solo mockeó Inventario y Entrega,
  pero un bottom nav con iconos que no llevan a ningún lado sería peor que no
  tenerlo. Devolver no estaba mockeado pero es la otra mitad de RF-10 — dejarlo
  solo en el admin habría sido una asimetría rara apenas se lanza la pantalla
  de Entrega.
- **Solo lo mockeado (Inventario + Entrega)**: más rápido de construir, pero
  deja el bottom nav roto y Devolver como un salto abrupto de vuelta al admin.

## Decisión

`config/urls.py`: `admin.site.urls` se monta en `admin/` (antes en la raíz);
`apps.inventory.urls` toma `""` con las pantallas nuevas. `LOGIN_URL =
"admin:login"` y todo `{% url %}`/`reverse()` existente usan el namespace
`admin:`, así que se resuelven solos con el nuevo prefijo — el único ajuste
manual necesario fue `apps/inventory/middleware.py`
(`EXEMPT_PATH_PREFIXES`: `/login/`, `/logout/` → `/admin/login/`,
`/admin/logout/`).

Se añadieron 6 vistas nuevas en `apps/inventory/views.py` (`armamento_list`,
`armamento_entregar`, `armamento_devolver`, `movimiento_list`, `soldado_list`,
`existencia_list`), todas reutilizando `Armamento.entregar()`/`.devolver()` y
el mismo criterio de compañía-de-trabajo que ya usaba `CompaniaContextoMixin`
del admin — sin duplicar esa lógica de negocio. `EntregaForm`/`DevolucionForm`/
`BajaForm` se movieron de `admin.py` a un `forms.py` nuevo para que ambos
módulos los importen sin que `views.py` dependa de `admin.py`.

## Consecuencias

**Lo que ganamos**: el uso diario (buscar un arma, entregarla, devolverla, ver
el historial) ya no pasa por el admin de Django — tiene su propia superficie
visual, mobile-first, instalable, alineada con RF-17. El admin sigue intacto
para datos maestros (compañías, depósitos, tipos, usuarios, campos
personalizados), solo que ahora en `/admin/`.

**Lo que aceptamos a cambio**: Movimientos/Soldados/Munición se diseñaron
extrapolando el lenguaje visual de Inventario/Entrega (mismo sistema de
tarjetas/chips/colores), no un mockup explícito del canvas — más fiel a "un
sistema visual coherente" que a "una copia literal del canvas". Las listas no
tienen paginación todavía; con compañías de varios cientos de elementos (el
canvas mockeaba 365) esto puede volverse pesado y es candidato a paginar antes
de producción.

**Qué haría que revisáramos esta decisión**: si el admin de Django sigue
siendo necesario para tareas de uso diario (no solo datos maestros), valdría
la pena reconsiderar qué vive en cada superficie.
