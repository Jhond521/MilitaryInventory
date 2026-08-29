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
- Framework: Django 5.2 LTS (uses Django admin for master-data management)
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
pip install -e . --group dev      # or: pip install django psycopg[binary] dj-database-url python-dotenv gunicorn whitenoise pytest pytest-django ruff

# first-time setup
cp .env.example .env              # then edit values
python manage.py migrate
python manage.py seed_initial     # seeds 1 unidad, 7 compañías, 2 depósitos, 28 pelotones, 24 tipos
python manage.py createsuperuser  # first admin (email is the login)

# run in development
python manage.py runserver        # http://localhost:8000  (admin at /)

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

# run everything with Postgres via Docker
docker compose up
```

## Project layout

```
config/            # Django project: settings, urls (incl. /manifest.json, /sw.js), wsgi/asgi
apps/accounts/     # custom User (email login), roles (ADMIN/ENLACE), email allowlist backend
apps/inventory/    # domain: Unidad, Compania, Deposito, Peloton, Soldado, TipoArmamento,
                   #         Armamento, Movimiento, CampoPersonalizado, Existencia, Prestamo
  management/commands/seed_initial.py   # idempotent master-data seed
static/            # manifest.json, sw.js, icons/ (PWA — RF-17)
templates/admin/   # base_site.html override wiring the manifest + service worker into the admin UI
docs/              # PRD (Spanish), backlog (Spanish), ADRs
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
- Every entrega/devolución must create a `Movimiento` row (who, when, type) for
  traceability (RNF-03). Never mutate a weapon's location without logging it.
- Baja (decommission) keeps the row; it never deletes the weapon (RF-11).
- Access is restricted to `settings.AUTHORIZED_EMAILS`; the `AllowlistModelBackend`
  rejects logins outside the list even if a user row exists.
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

- The current build uses the Django admin as the UI. The custom operator screens
  (company selector, guided entrega/devolución, global search) are backlog stories
  H-08…H-11 and are not built yet.
- `/manifest.json` and `/sw.js` are served straight from `static/` via dedicated
  views in `config/urls.py` (not through whitenoise's hashed static pipeline, and
  not under `/static/`) so the service worker's default scope covers the whole
  origin. `templates/admin/base_site.html` links the manifest and registers the
  worker on every admin page — that's the whole PWA story until T-06/H-17 build
  the real mobile-first templates and bottom nav. The app icon is a placeholder
  (`static/icons/icon.svg`); swap it for the battalion crest before shipping RF-17.
- Local dev uses SQLite by default (empty `DATABASE_URL`). To mirror prod, set
  `DATABASE_URL` to Postgres or run `docker compose up`.
- `AUTH_USER_MODEL` is custom (`accounts.User`) — this was set before the first
  migration and must not change without a full reset.
