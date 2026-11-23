---
description: Pipeline automático para Quick Fixes — de ToDo a Done sin pausas manuales
argument-hint: <numero-de-ticket>
---

Vas a llevar el ticket **#$ARGUMENTS** de **SIGA — Inventario de Armamento** de punta a punta, **sin
pausas para prueba manual humana**. Encadenas la misma lógica de `/enriquecer-todo`, `/desarrollar`,
`/publicar-dev` y `/probar-dev`; este último hace el QA automático en dev y despliega a prod. Este
comando es para **quick fixes**: cambios pequeños y de bajo riesgo. Si en cualquier paso detectas que
el ticket no es un quick fix, **detente y avísame** en vez de forzar el flujo. Ejemplos: migración
destructiva, cambio grande de alcance, tests que no puedes hacer pasar, ambigüedad real en requisitos.

Lee primero: @.claude/kanban.md · `CLAUDE.md` · `docs/PRD.md` y los `docs/` relevantes al ticket.

Tablero real: **Backlog (= ToDo) → Ready → In progress → In review (= In QA) → Done**.
**QA Done no existe**: lo que aprueba `/probar-dev` pasa a Done al quedar en producción.

## Setup
1. Setup `gh` (sección 0 del helper) y usa los IDs de la sección 1.
2. Ubica el item de #$ARGUMENTS en el tablero y confirma su estado actual (sección 2). Si no está en
   **Backlog/ToDo** ni en **Ready**, dime en qué estado está y pregúntame si de todas formas quieres
   correr el pipeline desde ahí.

## Paso 1 — Enriquecer (ToDo → Ready)
- Lee el cuerpo actual (`gh issue view $ARGUMENTS`) y el PRD, los docs y los `design_specs/` relevantes.
- Redacta un cuerpo enriquecido igual que `/enriquecer-todo`: contexto, alcance, criterios de
  aceptación, notas de diseño y técnicas, dependencias y preguntas abiertas.
- **Los criterios de aceptación son el contrato del QA automático.** Cada uno debe ser observable,
  numerable (AC-1, AC-2…) y llevar cómo se verifica: `(verificación: test | dev | humano)`. Reglas en
  `/enriquecer-todo`.
- **No inventes requisitos.** Si quedan preguntas abiertas *bloqueantes*, detente aquí y pregúntame:
  no sigas el pipeline con un ticket ambiguo. Las respuestas que te dé quedan escritas en el cuerpo
  del issue.
- Actualiza el issue (`gh issue edit --body-file ...`) y mueve la tarjeta a **Ready**.

## Paso 2 — Desarrollar (Ready → In progress)
- `git checkout develop && git pull origin develop && git status`: rama limpia, sin trabajo a medias.
- Mueve la tarjeta a **In progress**.
- Implementa el ticket siguiendo el checklist de `/desarrollar`:
  - migraciones Django versionadas si aplica;
  - lógica de dominio respetando las reglas de `CLAUDE.md`: control SERIE vs CANTIDAD; el serializado
    no cruza entre compañías; la munición se presta; el pelotón es dato del soldado; todo movimiento se
    registra;
  - UI mobile-first en español y PWA;
  - sin romper los tests existentes.
- **Un test por criterio de aceptación** con `test` en su verificación, con docstring
  `#$ARGUMENTS AC-k`.
- Corre `ruff check . && python -m pytest` (vía `docker compose exec web ...` o local).
  **Si algo queda en rojo, detente y repórtamelo**: no continúes al siguiente paso.
- Commits locales referenciando `#$ARGUMENTS`.

## Paso 3 — Publicar a Dev (In progress → In review)
- `git push origin develop`. Esto dispara CI y el deploy de Railway dev.
- Confirma que el push subió (`git log origin/develop -1`).
- Mueve la tarjeta a **In review**.

## Paso 4 — QA automático y despliegue a producción (In review → Done)
Ejecuta **`/probar-dev $ARGUMENTS`** completo (`.claude/commands/probar-dev.md`):
- espera CI y el deploy de dev;
- corre la regresión local;
- arma el spec `.claude/qa/specs/issue-$ARGUMENTS.json`, con un check por AC, y lo corre en dev junto
  con la regresión de specs anteriores;
- emite el veredicto;
- si queda **APROBADO**, hace PR `develop → main`, espera CI, hace merge, verifica prod y mueve a **Done**.

Sus gates detienen también este pipeline:
- QA en rojo;
- AC sin evidencia;
- AC que requieren humano (te pregunta);
- commits en `develop` de otros tickets no aprobados;
- migraciones destructivas (pide autorización).

## Resumen final
Al terminar, o al detenerte por algún gate de seguridad, dame un resumen claro:
- en qué paso quedó el ticket;
- la tabla AC → evidencia;
- qué **no** se pudo verificar sin humano;
- el estado de CI, dev y prod;
- cualquier acción manual pendiente.

## Reglas duras (no negociables aunque sea "quick fix")
- Nunca fuerces un merge saltando CI.
- Nunca corras migraciones destructivas ni la siembra sin autorización explícita mía.
- Nunca inventes requisitos ni des por probado algo que no verificaste.
- Ante cualquier duda real sobre alcance o riesgo, para el pipeline y pregúntame. Este comando prioriza
  velocidad para cambios chicos; no reemplaza el juicio en casos ambiguos.
