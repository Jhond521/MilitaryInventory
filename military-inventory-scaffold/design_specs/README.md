# Diseño — SIGA (Batallón de Selva N.º 52)

Mockups hechos con Claude Design (dirección sobria/militar utilitaria, paleta del escudo del batallón:
carmesí, azul-negro pantera, dorado, marfil; tipografía Oswald + IBM Plex; serials en mono).

Canvas publicado (editable): https://claude.ai/code/artifact/0a77554e-f1f9-4b5e-9cae-1a66e8cb364f

## Pantallas (`.dc.html`)

Escritorio:
- `Login.dc.html` — ingreso (acceso restringido por correo).
- `CompanySelector.dc.html` — selección de compañía al ingresar (las 7).
- `Main.dc.html` — inventario + búsqueda por serie; columnas: serie, denominación, categoría,
  **Pelotón**, estado, **Responsable**.
- `WeaponDetail.dc.html` — detalle del arma (datos, pelotón, responsable, historial de movimientos,
  campos personalizados).
- `Movimiento.dc.html` — entrega/devolución (soldado de la misma compañía; muestra pelotón).
- `Municion.dc.html` — existencias por lote/cantidad y **préstamo entre compañías** con saldos.

Móvil (responsive + PWA instalable):
- `MobileInventario.dc.html` — inventario en celular con banner de instalación y navegación inferior.
- `MobileEntrega.dc.html` — entrega desde el celular.

Convenciones de UI: español, mobile-first, responsive; app **instalable como PWA** (ícono = escudo);
objetivos táctiles ≥ 44 px. Al implementar la UI, seguir estas pantallas como referencia visual.
