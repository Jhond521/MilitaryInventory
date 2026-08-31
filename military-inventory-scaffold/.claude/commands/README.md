# Comandos de flujo — SIGA (Inventario de Armamento)

Comandos de Claude Code para el ciclo de trabajo sobre el tablero de GitHub Projects
(ToDo → Ready → In Progress → In QA → QA Done → Done) y Railway (dev/prod).

| Comando | Qué hace | Mueve la tarjeta |
|---|---|---|
| `/enriquecer-todo` | Enriquece los tickets en **ToDo** con PRD, docs, backlog, feedback y `design_specs/`. | ToDo → **Ready** |
| `/desarrollar <#>` | Desarrolla un ticket sobre `develop` con checklist y lo deja en local para prueba manual. | Ready → **In Progress** |
| `/publicar-dev <#>` | Push a `develop` → deploy Railway **dev** para probar. | In Progress → **In QA** |
| *(manual)* | Pruebas manuales en dev. | In QA → **QA Done** |
| `/desplegar-prod` | PR `develop`→`main` de todo lo de **QA Done**, merge tras CI → deploy **prod**. | QA Done → **Done** |
| `/quick-fix <#>` | Corre todo el pipeline (Enriquecer → Dev → Publicar dev → QA automático → Prod) sin pausas manuales. Sólo para cambios chicos y de bajo riesgo. | ToDo/Ready → **Done** |

`kanban.md` (en `.claude/kanban.md`) es un helper compartido: contiene los snippets de `gh`/GraphQL
para descubrir el project y mover tarjetas. Los comandos lo incluyen con `@.claude/kanban.md`.

## Requisitos
- `gh` CLI autenticado con scope `project`. Primera vez:
  `gh auth login` y, si hace falta, `gh auth refresh -s project,read:project`.
- `railway` CLI configurado (el deploy real lo dispara el push a `develop` / merge a `main`).
- Docker para el desarrollo local (`docker compose up`), o `python manage.py runserver`.

## Nota sobre el primer uso
La primera vez, descubre el número del Project y los IDs de las opciones de estado (sección 1 de
`kanban.md`) y, si quieres, pégalos en la tabla de ese archivo para no redescubrirlos cada vez.
