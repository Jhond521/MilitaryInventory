# ADR-0004: Retirar el admin de Django por completo

- **Fecha**: 2026-08-30
- **Estado**: Aceptada
- **Decide**: John Cuervo

## Contexto

ADR-0003 movió el admin de Django a `/admin/` y construyó 6 pantallas propias
(Inventario, Entregar, Devolver, Movimientos, Soldados, Munición) como la
superficie principal en `/`, pero dejó todo lo demás en el admin: login/
logout/cambio de contraseña (vistas del `AdminSite`, no algo propio),
compañías, depósitos, pelotones, tipos de armamento, campos personalizados,
alta/edición de soldados y armamento, dar de baja, préstamos y usuarios. El
usuario pidió que nada del aplicativo siga en el diseño del admin — que
"Django era provisional y no debe permanecer" — y, ante la opción, prefirió
retirar `/admin/` por completo en vez de dejarlo montado sin usar.

## Opciones consideradas

### Alcance del retiro

- **Retiro completo: URLs, `admin.py`, `admin_mixins.py`, plantillas,
  `django.contrib.admin` de `INSTALLED_APPS`** (elegida): nada queda
  reachable en `/admin/` (404) ni corriendo en segundo plano; el proyecto ya
  no depende del framework de admin para nada (ni Select2, ni el widget de
  calendario, ni sus plantillas) — todos los formularios nuevos usan
  `<select>`/`<input type="date">` nativos.
- **Dejar `/admin/` montado pero sin enlazar**: más simple de revertir, pero
  es exactamente lo que el usuario pidió evitar — Django "sigue ahí".

### Login/logout/cambio de contraseña

- **Vistas propias sobre `django.contrib.auth.views`** (elegida):
  `LoginView`/`LogoutView`/`PasswordChangeView` de Django ya son genéricas
  (no específicas del admin) — solo hacía falta plantillas propias
  (`templates/accounts/`) y una nueva app de URLs (`apps/accounts/urls.py`,
  montada en `/cuenta/`). `LOGIN_URL` pasa de `"admin:login"` a
  `"accounts:login"`.
- **Reimplementar autenticación a mano**: hubiera descartado maquinaria de
  Django ya correcta (hashing, `AllowlistModelBackend` existente, protección
  CSRF) sin ninguna ganancia.

### CRUD de datos maestros (Compañía, Depósito, Pelotón, TipoArmamento,
   CampoPersonalizado, Unidad)

- **`ListView`/`CreateView`/`UpdateView`/`DeleteView` genéricas de Django +
  3 plantillas compartidas** (elegida, `apps/inventory/crud.py`): estos 6
  modelos son CRUD simple sobre 2-3 campos — las vistas genéricas de Django
  son la herramienta correcta, ya reutilizada 6 veces con casi cero código
  propio por modelo. Un filtro de plantilla nuevo (`valor_campo`, en
  `apps/inventory/templatetags/inventory_extras.py`) resuelve mostrar
  columnas arbitrarias (incluidas de choices, vía `get_<campo>_display`) sin
  una plantilla a mano por modelo.
- **Vistas función a mano por modelo**: 24 vistas casi idénticas (6 modelos ×
  4 acciones) sin ganar nada sobre las genéricas.

### Permisos: mixins de `ModelAdmin` vs. decoradores de vista

- **`apps/accounts/permissions.py` (nuevo) reemplaza `admin_mixins.py`**
  (elegida): mismas reglas (RF-01/RF-10/H-03) expresadas como
  `es_administrador(user)`/`usuario_autorizado(user)` + un decorador propio
  (`_requiere`) para vistas función, y `UserPassesTestMixin` para las CBV de
  `crud.py`. Se encontró y corrigió un bug real al migrar esto: usar
  `django.contrib.auth.decorators.user_passes_test` tal cual redirige a
  login incluso a un usuario ya autenticado que no pasa la prueba —
  combinado con `LoginView(redirect_authenticated_user=True)`, eso es un
  bucle infinito de redirects. El decorador propio replica el criterio de
  `AccessMixin` (autenticado-pero-sin-permiso → 403, no-autenticado →
  redirect a login).

## Decisión

Se implementó todo lo anterior. Los 6 usuarios ahora hacen *todo* — login,
elegir compañía, inventario, entregar/devolver/dar de baja, movimientos,
soldados (con alta/edición), munición/existencias (con alta/edición),
préstamos, y datos maestros — dentro de la superficie móvil. Usuarios
(`apps/accounts/views.py`, solo ADMIN) también se reconstruyó ahí, sin
exponer `is_superuser`/`is_staff` (sin función real ya sin admin).
`config/urls.py` ya no importa `django.contrib.admin`; `apps/inventory/
admin.py`, `apps/accounts/admin.py`, `apps/accounts/admin_mixins.py` y
`templates/admin/` se borraron.

## Consecuencias

**Lo que ganamos**: una sola superficie visual y de código para todo el
aplicativo — nadie necesita saber que alguna vez existió un admin de Django.
`/admin/` responde 404. La suite de tests (~30 tests que golpeaban URLs
`admin:*`) se migró a las URLs nuevas sin perder cobertura de las mismas
reglas de negocio.

**Lo que aceptamos a cambio**: se perdieron gratis varias features del admin
que nadie pidió reconstruir — autocomplete tipo Select2 en selects con muchas
opciones (aceptable: la opción con más entradas, tipos de armamento, tiene
29), acciones masivas sobre selección múltiple (H-09/H-10 ahora son de
"una a la vez", ya así desde ADR-0003), y el log de acciones
(`django.contrib.admin.models.LogEntry` deja de recibir filas nuevas, aunque
las históricas siguen en la base). Ningún cambio de comportamiento nuevo del
lado ADMIN — el rol conserva control total.

**Qué haría que revisáramos esta decisión**: si una futura pantalla de datos
maestros necesita algo que las vistas genéricas de Django no dan gratis
(validación cruzada compleja, wizards de varios pasos, subida de archivos),
conviene evaluar entonces si vale la pena una dependencia de UI más rica en
vez de seguir extendiendo el patrón de `crud.py`.
