---
description: Despliega a producción (PR develop->main) todo lo que está en QA Done y lo pasa a Done
---

Despliegas a **producción** todo lo que está aprobado en **QA Done**. El flujo a prod es **vía Pull
Request** de `develop` → `main` (para que corra el CI como gate); al hacer merge, Railway despliega
producción automáticamente desde `main`. Al confirmar el deploy, mueves esas tarjetas a **Done**.

Lee primero: @.claude/kanban.md · `docs/adr/0001-tech-stack.md` (decisiones de despliegue).

## Pasos
1. **Setup gh** (sección 0) y descubre IDs (sección 1).
2. **Reúne lo aprobado**: lista los items en estado **QA Done** (sección 2). Muéstrame la lista
   (número + título) y **confirma conmigo** que ese es exactamente el lote a producción.
3. **Chequeo de integridad de datos**: por defecto **NO** se tocan los datos existentes. Revisa si el
   lote incluye migraciones Django nuevas (`apps/*/migrations/`). Si alguna es destructiva
   (borrar/renombrar columnas o tablas, `RunPython` que borre datos), **detente y avísame**; sólo sigo
   si me lo autorizas explícitamente.
4. **Sincroniza**: `git checkout develop && git pull origin develop`. Asegúrate de que develop está
   verde en CI y contiene todo lo de QA Done.
5. **Crea el PR** `develop` → `main`:
   `gh pr create --repo Jhond521/MilitaryInventory --base main --head develop --title "Deploy a prod: <fecha>" --body "Tickets: #.. #.."`
   (lista los números del lote en el body).
6. **Espera el CI** del PR: `gh pr checks --watch`. Si falla, detente y repórtamelo.
7. **Merge**: con el CI en verde, `gh pr merge --repo Jhond521/MilitaryInventory --merge`. Esto dispara el
   deploy a Railway **producción** (el `Procfile` corre `python manage.py migrate` en `release`; las
   migraciones se aplican solas).
8. **Verifica producción**: confirma que main avanzó y recuérdame revisar la URL de prod (~1–2 min).
   La siembra `seed_initial` **no** corre sola; sólo si fuese un ambiente nuevo/base recreada haría falta
   `railway run --service MilitaryInventory --environment production python manage.py seed_initial`
   (no la corras salvo que te lo pida).
9. **Mueve a "Done"**: cada tarjeta del lote a `$OPT_DONE` (sección 3).
10. **Resumen**: qué tickets se desplegaron, el estado del deploy, y cualquier acción manual pendiente.

Reglas: nunca fuerces el merge saltando el CI; nunca corras migraciones destructivas ni la siembra sin mi
autorización explícita; los datos de producción no se tocan por defecto.
