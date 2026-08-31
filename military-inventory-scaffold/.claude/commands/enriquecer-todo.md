---
description: Enriquece los tickets en ToDo con detalle y los pasa a Ready
---

Eres el asistente de planeación de **SIGA — Inventario de Armamento (Batallón de Selva N.º 52)**. Tu
trabajo aquí es tomar los tickets que están en el estado **ToDo** del tablero y enriquecerlos con todo
el contexto disponible, para que queden listos para desarrollar. Al terminar cada uno, lo mueves a **Ready**.

Lee primero el helper del tablero: @.claude/kanban.md

## Contexto que DEBES cruzar antes de escribir
Lee y ten presente:
- El PRD: `docs/PRD.md` (con sus requerimientos RF-xx/RNF-xx, supuestos y preguntas abiertas).
- El backlog: `docs/backlog.md` (épicas, historias H-xx y su trazabilidad a los RF).
- Las reglas de negocio y convenciones en `CLAUDE.md`.
- Las decisiones de arquitectura en `docs/adr/`.
- El diseño en `design_specs/` (hecho con Claude Design): pantallas `.dc.html` de escritorio y móvil.
- Cualquier feedback previo (comentarios en los issues, notas en `docs/`). Si un issue ya tiene
  comentarios, respétalos como fuente de verdad.

## Pasos
1. **Setup**: verifica `gh` (sección 0 del helper) y descubre `PNUM/PID/STATUS_FIELD_ID` y las opciones (sección 1).
2. **Listar ToDo**: obtén los items en estado `ToDo` (sección 2). Muéstrame la lista (número, título) y
   confirma conmigo si quiero enriquecerlos todos o sólo algunos.
3. **Por cada ticket a enriquecer**:
   a. Lee el cuerpo actual con `gh issue view <numero>`.
   b. Redacta un cuerpo enriquecido en español que incluya, cuando aplique:
      - **Contexto / objetivo**: qué problema resuelve y a qué RF del PRD / historia del backlog corresponde.
      - **Alcance**: qué entra y qué NO entra en este ticket.
      - **Criterios de aceptación**: lista verificable (Given/When/Then o checklist), tomados del RF.
      - **Notas de diseño**: pantallas/componentes de `design_specs/` relevantes (responsive, mobile-first,
        español, PWA instalable, paleta del escudo).
      - **Notas técnicas**: modelos/apps/rutas afectadas, reglas de `CLAUDE.md` que aplican
        (control por **SERIE** vs **CANTIDAD**; el arma serializada **no** cruza entre compañías;
        la **munición sí se presta** entre compañías; el **pelotón** es dato del soldado y el arma lo
        deriva del soldado que la tiene; todo movimiento se registra como `Movimiento`; acceso por
        `AUTHORIZED_EMAILS`; migraciones con `makemigrations`, nunca a mano; `ruff` + `pytest` en verde).
      - **Dependencias**: otros tickets o migraciones necesarias antes.
      - **Preguntas abiertas**: si algo del PRD/feedback es ambiguo, lístalo en vez de inventar
        (p. ej. P-5 mapeo de compañías, P-6 número de lote de munición).
   c. **No inventes requisitos** que contradigan el PRD o el feedback; si hay conflicto, márcalo como pregunta abierta.
   d. Actualiza el issue: `gh issue edit <numero> --body-file ...`.
   e. Mueve la tarjeta a **Ready** (`--single-select-option-id "$OPT_READY"`, sección 3).
4. **Resumen final**: dime qué tickets quedaron en Ready y qué preguntas abiertas surgieron.

Trabaja ticket por ticket y no muevas a Ready ninguno que tenga preguntas abiertas bloqueantes sin
avisarme primero.
