# SIGA — Armory Inventory

[![CI](https://github.com/Jhond521/MilitaryInventory/actions/workflows/ci.yml/badge.svg)](https://github.com/Jhond521/MilitaryInventory/actions/workflows/ci.yml)

Web app to track a battalion's weapons inventory by serial number, company and
location (assigned to a soldier or stored in a deposit). Internal tool for a
small set of authorized users. Built for Batallón de Selva No. 52. Works on mobile
and is installable as a PWA (add to home screen, opens like an app).

**Status**: v1 MVP domain complete (Django admin as the UI); operator-specific screens
(H-08…H-17's guided UI, mobile-first PWA templates) are still backlog.

## Requirements

- Python 3.12+
- PostgreSQL (production) — SQLite is used automatically for local dev if no `DATABASE_URL` is set
- Docker + Docker Compose (optional, to run with Postgres locally)

## Setup

```bash
git clone <repo-url>
cd armory-inventory
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install django "psycopg[binary]" dj-database-url python-dotenv gunicorn whitenoise openpyxl pytest pytest-django ruff
cp .env.example .env            # fill in the values

python manage.py migrate
python manage.py seed_initial   # 1 unidad, 7 compañías, 2 depósitos, 28 pelotones, 29 tipos
python manage.py createsuperuser
```

## Running

```bash
python manage.py runserver
```

Then open <http://localhost:8000> — the app is served through the Django admin
(login with the email + password of the superuser you created).

Or run it with Postgres via Docker:

```bash
docker compose up
```

## Tests

```bash
python -m pytest          # or: python manage.py test
ruff check .
```

GitHub Actions (`.github/workflows/ci.yml`) runs both on every push and pull request.

## Project layout

```
config/        # Django project (settings, urls)
apps/          # accounts (users/roles) + inventory (domain model)
docs/          # PRD, backlog and architecture decisions
.github/       # CI (tests + ruff on every push)
```

## Documentation

- `docs/PRD.md` — product requirements (Spanish)
- `docs/backlog.md` — epics and user stories (Spanish)
- `docs/adr/` — architecture decision records
- `CLAUDE.md` — working instructions for Claude Code

## Deployment (Railway)

The `Procfile` runs migrations on release and serves via gunicorn. Set
`SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`DATABASE_URL` (Railway Postgres) and `AUTHORIZED_EMAILS` as environment
variables. Run `python manage.py seed_initial` once after the first deploy.

## License

Private — not for public distribution.
