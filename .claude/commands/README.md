# Comandos de flujo — SIGA (Inventario de Armamento)

Comandos de Claude Code para el ciclo de trabajo sobre el tablero de GitHub Projects y Railway
(dev/prod). Tablero real: **Backlog (= ToDo) → Ready → In progress → In review (= In QA) → Done**.
"QA Done" no existe: lo aprobado por el QA automático pasa directo a Done al quedar en producción.

| Comando | Qué hace | Mueve la tarjeta |
|---|---|---|
| `/enriquecer-todo` | Enriquece los tickets en **ToDo** con PRD, docs, backlog, feedback y `design_specs/`. Los criterios de aceptación quedan numerados (AC-k) y verificables. | ToDo → **Ready** |
| `/desarrollar <#>` | Desarrolla un ticket sobre `develop` con checklist (un test por AC) y lo deja en local para prueba manual. | Ready → **In progress** |
| `/publicar-dev <#>` | Push a `develop` → deploy Railway **dev**, y lanza `/probar-dev`. | In progress → **In review** |
| `/probar-dev [#...]` | **QA automático**: prueba cada AC con tests y contra el dev desplegado (`.claude/qa/`, con rollback) más la regresión. Si todo pasa, despliega a prod (PR → CI → merge). | In review → **Done** |
| `/desplegar-prod` | PR `develop`→`main` del lote aprobado, merge tras CI → deploy **prod**. Normalmente lo lanza `/probar-dev`. | In review (aprobado) → **Done** |
| `/quick-fix <#>` | Corre todo el pipeline (Enriquecer → Desarrollar → Publicar dev → `/probar-dev`) sin pausas manuales. Sólo para cambios chicos y de bajo riesgo. | ToDo/Ready → **Done** |

## QA automático (`.claude/qa/`)
- `smoke_dev.py` corre **dentro del contenedor de Railway dev**. Usa el test client de Django,
  autenticado como un ADMIN existente, en **una transacción que siempre hace rollback**: puede probar
  pantallas con login e incluso POST sin dejar datos en dev.
- `run_smoke_dev.sh <spec.json>` lo sube por `railway ssh` (en base64 y por trozos, con reintentos) y
  sale 0 sólo si todos los checks pasan.
- `specs/issue-<N>.json` tiene un check por criterio de aceptación (`#N AC-k …`). Cada ticket aprobado
  deja su spec, y todos se vuelven a correr como **regresión** en cada `/probar-dev`.
- Producción **nunca** se prueba por ssh: sólo `curl` a `/health/`.

Gates que frenan el despliegue automático:
- un AC sin evidencia o en rojo;
- AC que requieren humano (pregunta antes);
- commits en `develop` de tickets no aprobados (es todo o nada);
- migraciones destructivas (pide autorización);
- CI en rojo.

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
