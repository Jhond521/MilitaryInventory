---
description: Desarrolla un ticket (Ready) sobre develop y lo deja en local para prueba manual
argument-hint: <numero-de-ticket>
---

Vas a desarrollar el ticket **#$ARGUMENTS** de **SIGA — Inventario de Armamento** de principio a fin,
trabajando **directamente sobre la rama `develop`** (sin ramas feature), y lo dejas corriendo en local
para que yo lo pruebe manualmente antes de publicar.

Lee primero: @.claude/kanban.md · `CLAUDE.md` · `docs/PRD.md` y los `docs/` relevantes al ticket.

## Antes de tocar código
1. **Setup gh** (sección 0 del helper) y descubre IDs (sección 1).
2. **Lee el ticket**: `gh issue view $ARGUMENTS --repo Jhond521/MilitaryInventory --json title,body,labels,comments`.
   Si el ticket está pobre (no pasó por `/enriquecer-todo`), avísame antes de seguir.
3. **Rama limpia**: asegúrate de estar en `develop`, sin cambios sin commitear y actualizada:
   `git checkout develop && git pull origin develop && git status`. Si no existe `develop`, créala desde
   `main` (`git checkout -b develop main`). Si hay trabajo a medias, pregúntame.
4. **Mueve la tarjeta a "In Progress"** (`$OPT_INPROGRESS`, sección 3 del helper).

## Checklist de desarrollo (créalo con la lista de tareas y ve marcándolo)
Genera un checklist concreto para ESTE ticket a partir de sus criterios de aceptación y las reglas del
repo, típicamente:
- [ ] Modelo/migración Django si aplica: `python manage.py makemigrations && python manage.py migrate`.
      Versionadas; **nunca** editar una migración ya aplicada.
- [ ] Lógica de dominio en `apps/inventory/` y `apps/accounts/`, respetando las reglas de `CLAUDE.md`:
      control **SERIE** vs **CANTIDAD**; serializado no cruza entre compañías; **munición se presta**
      entre compañías con saldo y trazabilidad; **pelotón** es dato del soldado (el arma lo deriva);
      **todo movimiento** (entrega/devolución/préstamo/baja) se registra en `Movimiento`.
- [ ] Vistas/URLs con permisos por rol (`administrador` vs `enlace`) y acceso por `AUTHORIZED_EMAILS`.
- [ ] UI responsive **mobile-first** y en español, siguiendo `design_specs/`; mantener la **PWA**
      (manifest + service worker) e íconos válidos; objetivos táctiles ≥ 44 px.
- [ ] **Tests** nuevos (pytest) y no romper los existentes.
- [ ] `ruff check .` y `python -m pytest` en verde (o vía `docker compose exec web ...`).
- [ ] Levantar en local (`docker compose up` o `python manage.py runserver`) y verificar el flujo manualmente.

Trabaja el checklist paso a paso, marcando cada ítem al completarlo. No pases al siguiente si el actual
dejó tests o el linter en rojo.

## Al terminar
- **NO** hagas push ni deploy todavía. Deja el entorno local levantado (`docker compose up`, web en :8000).
- Haz commits locales con mensajes claros que referencien `#$ARGUMENTS`, pero **quédate en local**.
- Dame un resumen: qué se implementó, qué archivos cambiaron, cómo probarlo manualmente (pasos/URL),
  y qué revisar. La tarjeta queda en **In Progress** hasta que yo pruebe y luego corra `/publicar-dev`.
