---
description: Publica lo desarrollado a develop (Railway dev) y pasa el ticket a In QA
argument-hint: <numero-de-ticket>
---

Publicas el trabajo del ticket **#$ARGUMENTS** al ambiente **Dev** empujando la rama `develop`
(Railway despliega dev automáticamente desde `develop`). Al terminar, mueves la tarjeta a **In QA**.

Lee primero: @.claude/kanban.md

## Pasos
1. **Setup gh** (sección 0) y descubre IDs (sección 1).
2. **Verifica el estado local**:
   - Estás en `develop`: `git branch --show-current`.
   - Revisa `git status` y `git log origin/develop..HEAD` para ver qué se va a subir.
   - Corre la verificación local antes de publicar: `ruff check . && python -m pytest`
     (o vía `docker compose exec web ...`). Si algo falla, **no publiques**: repórtamelo.
3. **Confirma commit**: si hay cambios sin commitear, commitea con mensaje que referencie `#$ARGUMENTS`.
4. **Push**: `git push origin develop`. Esto dispara el CI y el deploy a Railway **dev**.
5. **Verifica el deploy**: confirma que el push subió (`git log origin/develop -1`). Recuérdame que
   Railway dev tarda ~1–2 min en quedar disponible en su URL `*.up.railway.app`.
   - Si esta migración creó/recreó la base o es el primer deploy del ambiente, recuérdame correr la
     siembra: `railway run --service MilitaryInventory-dev --environment dev python manage.py seed_initial`
     (no la corras tú salvo que te lo pida).
6. **Mueve la tarjeta a "In QA"** (`$OPT_INQA`, sección 3 del helper).
7. **Resumen**: confirma qué quedó publicado en dev, la URL para probar, y que la tarjeta está en In QA
   esperando mi prueba manual (yo la muevo a QA Done cuando valide).

Regla: sólo publicas a `develop`. Nunca toques `main` desde este comando.
