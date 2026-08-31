---
description: Pipeline automático para Quick Fixes — de ToDo a Done sin pausas manuales
argument-hint: <numero-de-ticket>
---

Vas a llevar el ticket **#$ARGUMENTS** de **SIGA — Inventario de Armamento** de punta a punta, **sin
pausas para prueba manual humana**, encadenando la misma lógica de `/enriquecer-todo`, `/desarrollar`,
`/publicar-dev` y `/desplegar-prod`. Este comando es para **quick fixes**: cambios pequeños y de bajo
riesgo. Si en cualquier paso detectas que el ticket no es un quick fix (migración destructiva, cambio
grande de alcance, tests que no puedes hacer pasar, ambigüedad real en requisitos), **detente y avísame**
en vez de forzar el flujo.

Lee primero: @.claude/kanban.md · `CLAUDE.md` · `docs/PRD.md` y los `docs/` relevantes al ticket.

## Setup
1. Setup `gh` (sección 0 del helper) y descubre `PNUM/PID/STATUS_FIELD_ID` y las opciones (sección 1).
2. Ubica el item de #$ARGUMENTS en el tablero y confirma su estado actual (sección 2). Si no está en
   **ToDo** ni **Ready**, dime en qué estado está y pregúntame si de todas formas quieres correr el
   pipeline completo desde ahí.

## Paso 1 — Enriquecer (ToDo → Ready)
- Lee el cuerpo actual (`gh issue view $ARGUMENTS`) y el PRD/docs/`design_specs/` relevantes.
- Redacta un cuerpo enriquecido igual que `/enriquecer-todo` (contexto, alcance, criterios de
  aceptación, notas de diseño/técnicas, dependencias, preguntas abiertas).
- **No inventes requisitos.** Si quedan preguntas abiertas *bloqueantes*, detente aquí y pregúntame —
  no sigas el pipeline con un ticket ambiguo.
- Actualiza el issue (`gh issue edit --body-file ...`) y mueve la tarjeta a **Ready**.

## Paso 2 — Desarrollar (Ready → In Progress)
- `git checkout develop && git pull origin develop && git status` (rama limpia, sin trabajo a medias).
- Mueve la tarjeta a **In Progress**.
- Implementa el ticket siguiendo el checklist de `/desarrollar`: migraciones Django versionadas si
  aplica, lógica de dominio respetando las reglas de `CLAUDE.md` (control SERIE vs CANTIDAD; serializado
  no cruza entre compañías; munición se presta; pelotón es dato del soldado; todo movimiento se registra),
  UI mobile-first en español y PWA, sin romper tests existentes.
- Corre `ruff check . && python -m pytest` (vía `docker compose exec web ...` o local).
  **Si algo queda en rojo, detente y repórtamelo** — no continúes al siguiente paso.
- Commits locales referenciando `#$ARGUMENTS`.

## Paso 3 — Publicar a Dev (In Progress → In QA)
- `git push origin develop` (dispara CI + deploy Railway dev).
- Confirma que el push subió (`git log origin/develop -1`) y espera lo necesario (~1–2 min) a que el
  deploy de dev quede disponible.
- Mueve la tarjeta a **In QA**.

## Paso 4 — QA automático (In QA → QA Done)
Como este pipeline no tiene humano probando manualmente, la validación en QA es **automática**:
- Vuelve a correr `ruff check . && python -m pytest` contra el código ya en `develop`.
- Haz un smoke check del ambiente dev desplegado: pega contra la URL de Railway dev (`*.up.railway.app`)
  el endpoint `/health/` o el más directamente afectado por el ticket, y confirma que responde bien
  (status 2xx, forma de datos esperada). Usa `curl` o similar.
- Si el ticket tocó flujos que no se pueden verificar sólo con curl (ej. interacción de UI compleja),
  dilo explícitamente en el resumen final — no lo des por probado si no pudiste verificarlo.
- Si algo falla, **detente y repórtamelo**; no avances a producción con QA en rojo.
- Si todo pasa, mueve la tarjeta a **QA Done**.

## Paso 5 — Desplegar a Producción (QA Done → Done)
- Chequeo de integridad de datos: revisa si hay migraciones Django nuevas en el lote. Si alguna es
  **destructiva** (drop/rename de columnas/tablas, borrado de datos), **detente y pide autorización
  explícita** antes de seguir — no lo hagas por tu cuenta aunque el resto del ticket sea un quick fix.
- `git checkout develop && git pull origin develop`.
- Crea el PR: `gh pr create --repo Jhond521/MilitaryInventory --base main --head develop --title "Quick fix: #$ARGUMENTS" --body "Ticket: #$ARGUMENTS"`.
- Espera CI: `gh pr checks --watch`. Si falla, detente y repórtamelo — nunca fuerces el merge saltando CI.
- Con CI en verde: `gh pr merge --repo Jhond521/MilitaryInventory --merge`.
- Verifica que `main` avanzó y recuérdame revisar la URL de prod (~1–2 min).
- La siembra `seed_initial` **no** corre sola tras el deploy; sólo la corres si te lo pido explícitamente
  (`railway run --service MilitaryInventory --environment production python manage.py seed_initial`).
- Mueve la tarjeta a **Done**.

## Resumen final
Al terminar (o al detenerte por algún gate de seguridad), dame un resumen claro: en qué paso quedó el
ticket, qué se verificó automáticamente y qué NO se pudo verificar sin humano, el estado del deploy, y
cualquier acción manual pendiente.

## Reglas duras (no negociables aunque sea "quick fix")
- Nunca fuerces un merge saltando CI.
- Nunca corras migraciones destructivas ni la siembra sin autorización explícita mía.
- Nunca inventes requisitos ni des por probado algo que no verificaste.
- Ante cualquier duda real sobre alcance o riesgo, para el pipeline y pregúntame — este comando prioriza
  velocidad para cambios chicos, no reemplaza el juicio en casos ambiguos.
