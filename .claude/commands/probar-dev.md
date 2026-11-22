---
description: QA automático en dev de los tickets en In review contra sus criterios de aceptación; si todo pasa, despliega a producción
argument-hint: "[numeros-de-ticket...] (vacío = todo lo que está en In review)"
---

Eres el **QA automático** de **SIGA — Inventario de Armamento**. Tomas los tickets que están en
**In review** (= "In QA"; ya están publicados en Railway **dev**). Pruebas cada **criterio de
aceptación** del ticket enriquecido contra el código en `develop` y contra el ambiente dev
desplegado. Si **todo** pasa, despliegas el lote a **producción** sin esperar a un humano.

Tickets: `$ARGUMENTS`. Si viene vacío, son todos los items en **In review**.

Lee primero: @.claude/kanban.md · `CLAUDE.md` · `docs/PRD.md`. Las herramientas de QA están en
`.claude/qa/` en la **raíz del repo**: usa `ROOT=$(git rev-parse --show-toplevel)`, porque el
directorio de trabajo puede ser `military-inventory-scaffold/`.

> Este comando reemplaza la prueba manual de "In QA". El estado **QA Done** no existe en el tablero.
> Lo que este comando aprueba pasa directo a **Done** cuando queda en producción.

## 0. Setup
1. Corre la sección 0 del helper (`gh`) y usa los IDs ya descubiertos en la sección 1.
2. Verifica `railway whoami`. El CLI está enlazado a **production**: **siempre** pasa
   `--environment dev --service web` para dev. En Git Bash exporta `MSYS_NO_PATHCONV=1`.
3. Ambientes:
   - Dev: `https://web-dev-62b1.up.railway.app`, servicio `web`, sigue a `develop`.
   - Prod: `https://web-prod-production-f6b5.up.railway.app`, servicio `web-prod`, sigue a `main`.

## 1. Armar el lote y la regla de "todo o nada"
1. Lista los items en **In review** (sección 2 del helper). Si pasaron números, quédate con esos y
   confirma que cada uno **está** en In review. Si alguno no está, avisa y detente.
2. `git checkout develop && git pull origin develop && git status`. El árbol debe estar limpio. Si hay
   trabajo sin commitear, **detente**: no es tuyo.
3. **Gate de alcance.** El deploy a prod es un PR `develop → main`, así que se lleva **todo** lo que
   haya en `develop`, no solo el lote. Revisa `git log --no-merges --format='%h %s' origin/main..origin/develop`:
   - Cada commit debe referenciar (`#N`) un ticket del lote, o ser `chore`/`docs`/`test(qa)` sin
     impacto en la app.
   - Si hay commits de un ticket que **no** está en el lote (sigue en In progress, o no pasó QA),
     **detente y repórtalo**: no se puede desplegar parcialmente.
   - Si `origin/main..origin/develop` está vacío, no hay nada que desplegar. Dilo y termina.

## 2. ¿Dev tiene exactamente este código?
1. CI verde en el HEAD de `develop`:
   `gh run list --repo Jhond521/MilitaryInventory --branch develop --limit 1 --json headSha,status,conclusion`.
   El `headSha` debe ser igual a `git rev-parse origin/develop` y la `conclusion` debe ser `success`.
   Si sigue corriendo, usa `gh run watch <id> --exit-status`.
2. Deploy de dev: en `railway deployment list --environment dev --service web` el más reciente debe
   estar en `SUCCESS` y ser **posterior** al commit HEAD (`git log -1 --format=%cI origin/develop`).
   Si está `BUILDING`/`DEPLOYING`, espera y reintenta, hasta ~5 min. Si falla, detente.
3. `curl -s -w '%{http_code}' https://web-dev-62b1.up.railway.app/health/` debe devolver 200 y
   `{"status": "ok"}`.
4. Confirma por `railway ssh --environment dev --service web -- "grep -c <texto> <archivo>"` que una
   línea nueva del lote está en el contenedor. Pasa todo el comando remoto como **un solo string**.

## 3. Verificación local (regresión completa)
En `military-inventory-scaffold/`: `ruff check . && python -m pytest -q`, más
`python manage.py makemigrations --check --dry-run`. Debe decir "No changes detected"; si no, falta
una migración y el ticket falla. Usa `.venv/Scripts/python.exe` si existe, o `docker compose exec web ...`.
Si algo queda en rojo, **detente**.

## 4. Criterios de aceptación → evidencia (por ticket)
1. Lee el ticket con `gh issue view <N> --json title,body,comments` y extrae la lista de la sección
   **"Criterios de aceptación"**. Numera cada criterio como **AC-1, AC-2…** en el orden del ticket.
   - Si el ticket **no tiene** criterios de aceptación verificables, **falla el gate**. Repórtalo para
     que pase por `/enriquecer-todo`: nunca inventes criterios para poder aprobar.
   - Los comentarios del issue (aclaraciones del usuario) mandan sobre el cuerpo.
2. Clasifica cada criterio y consigue **evidencia real**. Cada criterio que se pueda observar por HTTP
   o en la BD debe tener evidencia **en dev**, no solo en local:
   - **TEST**: un test de pytest que pruebe exactamente ese criterio. Búscalo (`grep -n "#N"` en
     `apps/*/tests.py`, docstrings) y **léelo**: confirma que asierta lo que dice el criterio. Ya
     corrió en verde en el paso 3.
   - **DEV**: un check del spec de dev (abajo) que lo pruebe contra el ambiente desplegado.
   - **HUMANO**: solo para lo que de verdad no se puede observar por HTTP ni en la BD, como la
     apariencia visual fina, un dispositivo real, instalar la PWA o un correo externo. Si se puede
     reducir a algo observable (una clase CSS del sistema de diseño presente, un atributo `max`,
     un `<select>` con N opciones), hazlo y clasifícalo como DEV.
3. **Spec de dev**: escribe o actualiza `.claude/qa/specs/issue-<N>.json`. Usa los ejemplos
   `issue-29.json` e `issue-31.json` y el formato documentado en `.claude/qa/smoke_dev.py`.
   - Nombra cada check `#N AC-k <qué prueba>`, para que cada criterio tenga su check.
   - `setup` crea sus propios datos con prefijo `QA-` (dev puede estar vacío, ver memoria "dev wipe"):
     tipos, pelotones, soldados con cédula `99…`, existencias. No dependas de datos que ya existan.
   - Para flujos de escritura usa checks `post` con `status` esperado y un `assert` sobre la BD.
     **Todo se deshace**: el script corre dentro de una transacción que siempre hace rollback, así que
     dev queda igual.
   - Córrelo: `bash "$ROOT/.claude/qa/run_smoke_dev.sh" "$ROOT/.claude/qa/specs/issue-<N>.json"`.
     Sale 0 solo si pasan todos los checks. Si sale 2, falló la conexión: reintenta una vez antes de
     dar por fallido.
4. **Regresión en dev**: corre también **todos** los demás `specs/issue-*.json`. Un spec viejo que
   falle bloquea el deploy igual que uno nuevo, porque se rompió algo que ya estaba en prod.
   - Excepción: si el ticket del lote cambió a propósito ese comportamiento, actualiza el spec viejo
     y explica por qué.
5. **Nunca** corras `smoke_dev.py` ni ningún script por `railway ssh` contra **production**.

## 5. Veredicto
Arma una tabla por ticket: `AC | criterio | evidencia (test::nombre y/o check dev) | resultado`.

- **APROBADO**: todos los AC tienen evidencia TEST o DEV y pasaron, y la regresión está en verde.
- **FALLA**: algún AC falló, o la regresión, CI, el deploy de dev o el gate de alcance.
  - Comenta en el issue la tabla y el detalle del fallo (`gh issue comment`).
  - Deja la tarjeta en **In review**.
  - **No despliegues nada**: es todo o nada por el gate de alcance. Repórtamelo.
- **REQUIERE HUMANO**: todo lo automatizable pasó, pero quedan AC clasificados HUMANO.
  - Comenta la tabla en el issue.
  - Pregúntame explícitamente si despliego igual, listando esos AC.
  - No despliegues hasta que yo diga que sí.

Si todo el lote está **APROBADO**:
1. Commitea los specs nuevos o cambiados:
   `git add "$ROOT/.claude/qa/specs" && git commit -m "test(qa): specs de aceptación #N ..."`.
   Termina el mensaje con las líneas de atribución. Haz `git push origin develop` y espera el CI de
   ese commit. No toca la app, pero Railway redespliega dev: no hace falta re-probar.
2. Comenta en cada issue el informe de QA:
   - la tabla de criterios;
   - el SHA probado;
   - el id del deploy de dev;
   - "Aprobado por QA automático".

## 6. Despliegue a producción (automático si el lote quedó APROBADO)
Sigue `/desplegar-prod` (`.claude/commands/desplegar-prod.md`) con este lote, con estas diferencias:
- **No** pidas confirmación del lote: el gate de QA la reemplaza.
- **Los gates duros siguen**:
  - Si hay migraciones nuevas en `origin/main..origin/develop` (`git diff --stat origin/main origin/develop -- '*/migrations/*'`),
    léelas. Si alguna es **destructiva** (`RemoveField`, `DeleteModel`, `RenameField`/`RenameModel`,
    `AlterField` que reduzca o cambie tipo con pérdida, `RunPython`/`RunSQL` que borre o reescriba
    datos), **detente y pide autorización explícita**.
  - Nunca hagas merge saltando CI.
  - Nunca corras `seed_initial`.
- PR: `gh pr create --base main --head develop --title "Deploy a prod: #N #M (QA automático)"`. El
  body lleva la lista de tickets con su resultado de QA y termina con la línea de atribución de PR.
  Luego `gh pr checks <url> --watch` y `gh pr merge --merge`.
- Verifica que `main` avanzó. En `railway deployment list --environment production --service web-prod`
  espera a que el deploy más reciente quede en `SUCCESS` (hasta ~5 min). En prod `/health/` debe dar
  200. En prod **solo** `curl` de lectura.
- Mueve cada tarjeta del lote a **Done** (`OPT_DONE`). Si el issue sigue abierto, no lo cierres: el
  tablero lo hace solo.

## 7. Resumen final
Dime:
- qué tickets se probaron y su veredicto;
- la tabla AC → evidencia;
- qué quedó como HUMANO;
- el estado de CI, dev y prod (SHAs, deploys);
- lo que quedó pendiente.

No des por probado nada que no tenga evidencia.

## Reglas duras
- Sin criterios de aceptación verificables no hay deploy. No se inventan criterios ni se relajan
  para que pase.
- Todo o nada: si `develop` trae algo que no está aprobado, no se despliega.
- Nunca se fuerza un merge sin CI, ni se corren migraciones destructivas o la siembra sin mi
  autorización explícita.
- En dev solo se escribe dentro de la transacción con rollback de `smoke_dev.py`. En prod solo se lee
  `/health/` por `curl`.
- Ante una falla, se detiene y reporta. No arregles código desde este comando: eso es `/desarrollar`.
