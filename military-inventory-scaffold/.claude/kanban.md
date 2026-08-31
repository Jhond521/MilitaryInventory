# Helper Kanban (GitHub Projects) — referencia para los comandos

Este archivo lo incluyen los comandos de `/enriquecer-todo`, `/desarrollar`, `/publicar-dev` y
`/desplegar-prod`. Contiene todo lo necesario para leer y mover tarjetas del GitHub Project vía `gh`.

Repo: `Jhond521/MilitaryInventory` · Ramas: `develop` (dev) / `main` (prod).
Estados del tablero (en orden): **ToDo → Ready → In Progress → In QA → QA Done → Done**.

## 0. Verificar setup (correr una vez; si algo falla, detente y muéstraselo al usuario)

```bash
gh auth status || { echo "Falta login: corre  gh auth login  (elige HTTPS + GitHub.com)"; exit 1; }
# Los Projects v2 necesitan el scope 'project'. Si el siguiente comando falla con 'missing scopes',
# corre:  gh auth refresh -s project,read:project
gh api graphql -f query='{viewer{login}}' >/dev/null || { echo "Token sin acceso a GraphQL"; exit 1; }
```

## 1. Descubrir el Project y los IDs de estado (correr al inicio de cada comando)

Los Projects v2 se manejan por GraphQL. Descubre y guarda estos IDs en variables de shell dentro del
mismo bloque bash donde los uses (cada llamada a bash es independiente, no persisten entre bloques).

```bash
OWNER=Jhond521

# Listar projects del owner para ubicar el número del tablero de MilitaryInventory
gh project list --owner "$OWNER" --format json

# Con el número correcto (ej. 1), guardar el projectId y el campo Status con sus opciones:
PNUM=1   # <-- ajustar al número real del project
PID=$(gh project view "$PNUM" --owner "$OWNER" --format json | jq -r '.id')

# Campo Status y IDs de cada opción (ToDo, Ready, In Progress, In QA, QA Done, Done)
gh project field-list "$PNUM" --owner "$OWNER" --format json \
  | jq '.fields[] | select(.name=="Status") | {fieldId:.id, options:.options}'
```

Guarda de esa salida: `STATUS_FIELD_ID` y el `id` de cada opción. Ejemplo de asignación:

```bash
STATUS_FIELD_ID=PVTSSF_xxx
OPT_TODO=xxxx ; OPT_READY=xxxx ; OPT_INPROGRESS=xxxx
OPT_INQA=xxxx ; OPT_QADONE=xxxx ; OPT_DONE=xxxx
```

> Los IDs son estables; si prefieres no descubrirlos cada vez, pégalos aquí abajo una sola vez y los
> comandos los reutilizan. **Rellenar tras el primer descubrimiento:**
>
> - PNUM=`` · PID=`` · STATUS_FIELD_ID=``
> - OPT_TODO=`` · OPT_READY=`` · OPT_INPROGRESS=`` · OPT_INQA=`` · OPT_QADONE=`` · OPT_DONE=``

## 2. Listar tarjetas por estado

```bash
# Todos los items con su estado, issue asociado, número y título
gh project item-list "$PNUM" --owner "$OWNER" --format json \
  | jq -r '.items[] | [.id, (.status // "-"), (.content.number // "-"), .title] | @tsv'
```

- `.id` = ID del item DENTRO del project (lo que necesita `item-edit`, NO es el número del issue).
- `.content.number` = número del issue de GitHub (para `gh issue view/edit/comment`).
- Filtra por estado con `select(.status=="ToDo")`, etc.

## 3. Mover una tarjeta de estado

```bash
gh project item-edit \
  --project-id "$PID" \
  --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD_ID" \
  --single-select-option-id "$OPT_READY"   # <-- opción destino
```

## 4. Leer / editar el contenido del ticket (es un issue de GitHub)

```bash
gh issue view <numero> --repo Jhond521/MilitaryInventory --json title,body,labels,comments
gh issue edit <numero> --repo Jhond521/MilitaryInventory --body-file /tmp/nuevo-cuerpo.md
gh issue comment <numero> --repo Jhond521/MilitaryInventory --body "..."
```

## Reglas al mover tarjetas
- Antes de mover, confirma que el item está en el estado de origen esperado; si no, avisa y no muevas.
- Si `gh` no está listo o falta el scope `project`, **no inventes**: detente y muestra el paso de setup.
- Nunca borres ni cierres issues salvo que el usuario lo pida; sólo cambias el campo Status.
