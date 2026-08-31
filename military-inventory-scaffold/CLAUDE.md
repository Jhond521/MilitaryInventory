# CLAUDE.md

## What this project is

SIGA is a small internal web app to track a battalion's weapons inventory
(Batallón de Selva No. 52). Every weapon is identified by its serial number,
belongs to one company (compañía), and is either "en mano" (assigned to a
soldier) or "en depósito" (stored in a deposit). Six authorized users manage
the data; soldiers are records, not users. Full detail lives in `docs/PRD.md`
— read it before working on anything non-trivial.

## Tech stack

- Language / runtime: Python 3.12+
- Framework: Django 5.2 LTS (no `django.contrib.admin` — see ADR-0004; every screen,
  including login and master-data CRUD, is a purpose-built view)
- Database: PostgreSQL in prod/Docker; SQLite fallback for local dev (no server needed)
- Package manager: pip / venv (deps declared in `pyproject.toml`)
- Testing: pytest + pytest-django (also runnable via `manage.py test`)
- Lint/format: ruff
- Deployment target: Railway (Procfile) or Docker
- Frontend: server-rendered Django templates, responsive (mobile-first), installable as a **PWA** (web app manifest + service worker; app icon = battalion crest)

Decisions and their rationale are in `docs/adr/`. If you think a decision should
change, write a new ADR instead of silently doing something different.

## Commands

```bash
# create/activate a virtual env (Windows: .venv\Scripts\activate)
python -m venv .venv && . .venv/bin/activate

# install dependencies
pip install -e . --group dev      # or: pip install django psycopg[binary] dj-database-url python-dotenv gunicorn whitenoise openpyxl pytest pytest-django ruff

# first-time setup
cp .env.example .env              # then edit values
python manage.py migrate
python manage.py seed_initial     # seeds 1 unidad, 7 compañías, 2 depósitos, 28 pelotones, 29 tipos
python manage.py createsuperuser  # first user, role=ADMIN (email is the login)

# run in development
python manage.py runserver        # http://localhost:8000  (login at /cuenta/login/)

# run tests
python -m pytest                  # or: python manage.py test

# run a single test
python -m pytest apps/inventory/tests.py::ArmamentoRulesTests

# lint / format
ruff check .
ruff check --fix .

# database migrations
python manage.py makemigrations
python manage.py migrate

# import the initial serialized inventory from Excel (RF-13) — validates
# everything first; creates nothing if there's a single conflict
python manage.py importar_armamento ruta/archivo.xlsx --deposito Apiay --dry-run
python manage.py importar_armamento ruta/archivo.xlsx --deposito Apiay

# run everything with Postgres via Docker
docker compose up
```

## Project layout

```
config/            # Django project: settings, urls (incl. /manifest.json, /sw.js), wsgi/asgi — no admin.site
apps/accounts/     # custom User (email login), roles (ADMIN/ENLACE), email allowlist backend
  permissions.py   #   es_administrador/usuario_autorizado + requiere_admin/requiere_autorizado decorators (H-03)
  views.py, urls.py, forms.py # login/logout/password-change (over django.contrib.auth.views) +
                   #   usuario_list/_crear/_editar/_restablecer_password (ADMIN-only) — mounted at /cuenta/
apps/inventory/    # domain: Unidad, Compania, Deposito, Peloton, Soldado, TipoArmamento,
                   #         Armamento, Movimiento, CampoPersonalizado, Existencia, Prestamo
  forms.py         # EntregaForm/DevolucionForm/BajaForm, Armamento*/Soldado/Existencia/Prestamo
                   #   forms, campo_* helpers for custom fields (H-12)
  crud.py          # generic ListView/CreateView/UpdateView/DeleteView for the 6 simple
                   #   master-data models (Unidad, Compania, Deposito, Peloton, TipoArmamento,
                   #   CampoPersonalizado) — ADMIN-only to add/edit/delete, everyone views
  templatetags/inventory_extras.py # valor_campo filter (renders a field or its get_*_display())
  views.py         # everything else: armamento_list/_crear/_editar/_entregar/_devolver/_baja,
                   #   movimiento_list, soldado_list/_crear/_editar, existencia_list/_crear/_editar,
                   #   prestamo_list/_transferir, elegir_compania, ajustes — mounted at "/"
  middleware.py, urls.py, context_processors.py   # compañía de trabajo (RF-02)
  management/commands/seed_initial.py       # idempotent master-data seed
  management/commands/importar_armamento.py # initial Excel load (RF-13, H-13)
static/css/mobile.css # design tokens (Oswald + IBM Plex Sans/Mono, dark/red/cream palette) — the whole UI
static/            # manifest.json, sw.js, icons/ (PWA — RF-17)
templates/accounts/  # login (standalone), password change, cuenta, usuario_* — accounts app screens
templates/inventory/ # base_mobile.html + every other screen (T-06/H-17, ADR-0004) — the entire UI
docs/              # PRD (Spanish), backlog (Spanish), ADRs
.github/workflows/ # CI: ruff + pytest on every push/PR (T-03)
```

## Domain rules that matter

- A weapon (`Armamento`) belongs to exactly one company and is **never** transferred
  between companies (PRD NO-3). Every `TipoArmamento` is either `SERIE` (individual,
  used by `Armamento`) or `CANTIDAD` (stock, used by `Existencia`) — `Armamento.clean()`
  rejects a `CANTIDAD` tipo, `Existencia.clean()` rejects a `SERIE` one.
- Location is a two-state field: `EN_MANO` (needs a `soldado` of the same company)
  or `DEPOSITO` (needs a `deposito`). `Armamento.clean()` enforces both — call
  `full_clean()` before saving from views.
- A soldier belongs to exactly one `Peloton` of their own company (`Soldado.clean()`
  checks this); a weapon has no pelotón of its own — `Armamento.peloton_actual` derives
  it from the soldier currently holding it, and is `None` while in depósito (RF-16).
- Ammunition/quantity stock (`Existencia`) **does** cross companies via `Prestamo`
  (RF-15) — the only exception to the no-transfer rule above, which applies to
  serialized weapons only. `Prestamo.save()` atomically debits the origin
  `Existencia` and credits (or creates) the destination one; `Prestamo.clean()`
  validates the tipo, the quantity and that enough stock exists — always call
  `full_clean()` before `save()`.
- Custom fields (`CampoPersonalizado` + `Armamento.datos_extra` JSON) apply **only**
  to weapons. Soldiers and weapon types have a fixed schema (PRD NO-2).
  `datos_extra` uses `UnicodeJSONEncoder` (not Django's default, which escapes
  accented characters as `\uXXXX`) so `icontains` search over it — RF-12 — actually
  matches Spanish text with tildes as typed. Reuse that encoder on any other
  JSONField that stores user-facing Spanish text.
- `ArmamentoEditarForm.__init__()` (`apps/inventory/forms.py`, RF-08, H-12) dynamically
  adds one form field per `CampoPersonalizado` (named `campo_<pk>`, not real model
  fields); `aplicar_campos_personalizados()` (same file, called from
  `inventory:armamento_editar`) merges those into `Armamento.datos_extra` keyed by the
  field's own `nombre` — read both together before touching custom fields.
  `armamento_editar` is `@requiere_admin`, so there's no read-only variant to keep in
  sync (unlike the old `ArmamentoAdmin`, which had to fake a read-only rendering for
  Enlace — that whole problem went away with the admin, ADR-0004).
- Every entrega/devolución must create a `Movimiento` row (who, when, type) for
  traceability (RNF-03). Never mutate a weapon's location without logging it —
  use `Armamento.entregar()`/`.devolver()` (transactional, validate company match
  and current ubicación) instead of setting `ubicacion`/`soldado`/`deposito` by hand.
- Baja (decommission) keeps the row; it never deletes the weapon (RF-11). Use
  `Armamento.dar_de_baja(motivo, fecha, usuario, observacion="")` — sets `estado=BAJA`,
  logs a `Movimiento` (type `BAJA`), and works from either ubicación (unlike
  entregar/devolver). `clean()` requires `motivo_baja`/`fecha_baja` whenever
  `estado=BAJA`, and `entregar()` refuses a weapon that isn't `ACTIVO`. Only ADMIN can
  do this (RF-11) — unlike H-09's entrega/devolución, which RF-10 authorizes for both
  roles.
- The "compañía de trabajo" (RF-02, session key `apps.inventory.views.SESSION_KEY`) is a
  **default filter, not a permission boundary** (PRD S-2) — every user can still see every
  company. `CompaniaContextMiddleware` sends anyone without it to `/compania/`;
  `_companias_scope(request)` in `apps/inventory/views.py` (used by `armamento_list`,
  `movimiento_list`, `soldado_list`, `existencia_list`, `prestamo_list`) returns
  `(compania_id, ver_todas)` — `ver_todas` is a plain `?todas=1` query param (the
  "ver todas" link in each list template). Don't add a company-scoped list view without
  applying this same filter.
- Access is restricted to `settings.AUTHORIZED_EMAILS`; the `AllowlistModelBackend`
  rejects logins outside the list even if a user row exists.
- Role gates (`apps/accounts/permissions.py`, RF-01/RF-10, H-03) check `user.role`
  directly via `es_administrador(user)`/`usuario_autorizado(user)` — no Django
  groups/permissions are ever assigned. Every view that touches master data or a
  sensitive action must be decorated `@requiere_admin`; every other authenticated view
  must be `@requiere_autorizado` (there is no undecorated view — an undecorated one is a
  bug). The generic CRUD in `apps/inventory/crud.py` uses the class-based equivalents
  (`AdminMixin`/`AutorizadoMixin`, built on `UserPassesTestMixin`). **Don't use
  `django.contrib.auth.decorators.user_passes_test` directly** — it always redirects to
  login on failure, even for an already-authenticated user, which loops forever against
  `LoginView(redirect_authenticated_user=True)`; the decorators here 403 an authenticated
  user who fails the check instead (same behavior as `UserPassesTestMixin`).
  `createsuperuser` always sets `role=ADMIN`, so a superuser and an ADMIN-role user are
  equivalent for these checks; a plain `create_user(..., role=User.Role.ADMIN)` also gets
  full access. `is_staff`/`is_superuser` have no functional meaning left in this app now
  that there's no admin site — don't gate anything on them.
- The UI must stay responsive (mobile-first) and installable as a PWA: keep the web app
  manifest and service worker valid, touch targets ≥ 44px, and a mobile bottom nav. Don't
  ship desktop-only layouts.

## Conventions

- **Language**: code, comments, commit messages and this file in English. Product
  docs (`docs/PRD.md`, `docs/backlog.md`) in Spanish. UI strings in Spanish.
- **Commits**: Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- **Tests**: every behavior change comes with a test. Run the suite before saying you're done.
- **Style**: enforced by ruff — run it rather than hand-formatting.

## Working agreement

- Read `docs/PRD.md` and the relevant part of `docs/backlog.md` before implementing a story.
- Prefer small, reviewable changes over large rewrites.
- When a requirement is ambiguous, ask instead of guessing.
- Update `docs/backlog.md` when a story is completed.
- Record architectural decisions as ADRs in `docs/adr/`.

## Don't

- Don't commit secrets. Config goes in `.env` (git-ignored); `.env.example` documents the keys.
- Don't edit migrations by hand — generate them with `makemigrations`.
- Don't move a weapon's location without writing a `Movimiento`.
- Don't add attributes to soldiers or weapon types (custom fields are weapons-only).
- Don't push directly to the main branch.

## Known gotchas

- **There is no Django admin** (ADR-0003 moved it to `/admin/`; ADR-0004 removed it
  entirely — `/admin/` 404s, `django.contrib.admin` isn't in `INSTALLED_APPS`). Every
  screen — login, compañía de trabajo, inventory, entregar/devolver/dar de baja,
  movimientos, soldados, munición/existencias, préstamos, all master data, and user
  management — is a purpose-built view under `apps/accounts/` or `apps/inventory/`,
  styled with `static/css/mobile.css`. Don't add `django.contrib.admin` back or reference
  `admin:` URL names — they don't exist. The 6 simple master-data models (Unidad,
  Compania, Deposito, Peloton, TipoArmamento, CampoPersonalizado) reuse Django's generic
  `ListView`/`CreateView`/`UpdateView`/`DeleteView` (`apps/inventory/crud.py`) — add a new
  one there, don't hand-roll function views for another simple model. Movimientos/
  Soldados/Munición screens extrapolate the same visual language from a design canvas
  that only mocked Inventario/Entrega — not from an explicit mockup for those specific
  screens.
- `python manage.py importar_armamento` (H-13, RF-13) assumes a **normalized** Excel
  format documented in its own docstring (one worksheet per company, header row with
  Serie/Denominación/Depósito columns) — David's real `ACTIVOS FIJOS COMPAÑIA.xlsx`
  wasn't available while writing it (P-1/P-6 in the PRD are still open), so its real
  sheet-per-company "bloques por denominación" layout is unverified. When the real
  file arrives, either adapt it into this flat shape first or extend the command's
  header-detection to parse the real block structure — the validation/reporting core
  (duplicate series, unknown tipo/depósito, atomic all-or-nothing) should carry over
  either way.
- `/manifest.json` and `/sw.js` are served straight from `static/` via dedicated
  views in `config/urls.py` (not through whitenoise's hashed static pipeline, and
  not under `/static/`) so the service worker's default scope covers the whole
  origin. `templates/inventory/_pwa_head.html` (the manifest `<link>`, theme-color
  meta, and SW registration script) is included from both `base_mobile.html` and the
  standalone `templates/accounts/login.html` — don't duplicate it a third time. The app
  icon is a placeholder (`static/icons/icon.svg`); swap it for the battalion crest
  before shipping RF-17.
- Local dev uses SQLite by default (empty `DATABASE_URL`). To mirror prod, set
  `DATABASE_URL` to Postgres or run `docker compose up`.
- `AUTH_USER_MODEL` is custom (`accounts.User`) — this was set before the first
  migration and must not change without a full reset.
