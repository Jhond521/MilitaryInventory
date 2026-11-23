---
description: Publica lo desarrollado a develop (Railway dev), pasa el ticket a In review y lanza el QA automático (/probar-dev)
argument-hint: <numero-de-ticket>
---

Publicas el trabajo del ticket **#$ARGUMENTS** al ambiente **Dev** empujando la rama `develop`.
Railway despliega dev automáticamente desde `develop`. Al terminar, mueves la tarjeta a **In review**
(= "In QA") y lanzas el **QA automático** con `/probar-dev`. Si el QA aprueba, ese comando despliega
a producción.

Lee primero: @.claude/kanban.md

## Pasos
1. **Setup gh** (sección 0) y usa los IDs de la sección 1.
2. **Verifica el estado local**:
   - Estás en `develop`: `git branch --show-current`.
   - Revisa `git status` y `git log origin/develop..HEAD` para ver qué se va a subir.
   - Corre la verificación local antes de publicar: `ruff check . && python -m pytest` (o vía
     `docker compose exec web ...`). Si algo falla, **no publiques** y repórtamelo.
3. **Confirma commit**: si hay cambios sin commitear, commitea con un mensaje que referencie `#$ARGUMENTS`.
4. **Push**: `git push origin develop`. Esto dispara el CI y el deploy a Railway **dev**.
5. **Verifica que subió**: `git log origin/develop -1`.
   - Si esta migración creó o recreó la base, o es el primer deploy del ambiente, recuérdame correr la
     siembra: `railway run --service web --environment dev python manage.py seed_initial`. No la corras
     tú salvo que te lo pida.
6. **Mueve la tarjeta a "In review"** (`OPT_INQA`, sección 3 del helper).
7. **QA automático**: ejecuta **`/probar-dev $ARGUMENTS`** (`.claude/commands/probar-dev.md`). Ese
   comando espera el CI y el deploy de dev y prueba cada criterio de aceptación contra dev. Con todo en
   verde despliega a prod y mueve a Done. Si algo falla o requiere humano, se detiene y me lo reporta.
   - Si te digo explícitamente "sin QA automático", sáltate este paso y deja la tarjeta en In review
     para prueba manual.
8. **Resumen**: qué quedó publicado en dev, el veredicto del QA y el estado de producción.

Regla: este comando sólo empuja a `develop`. El paso a `main` lo hace `/probar-dev` con sus gates
(CI, migraciones destructivas, todo o nada).
