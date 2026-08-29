# ADR-0001: Tech stack for SIGA

- **Fecha**: 2026-08-26
- **Estado**: Aceptada
- **Decide**: John Cuervo (con David Bolaños como solicitante)

## Contexto

SIGA es una herramienta interna para ~6 usuarios que administra el inventario de
armamento de un batallón: datos maestros (compañías, depósitos, tipos, soldados),
armamento identificado por serie, movimientos con trazabilidad, roles y una lista
blanca de correos. El corazón del producto es CRUD con administración y permisos,
no una interfaz muy dinámica. Debe desplegarse en internet y ser accesible desde
dos sedes remotas, mantenerse en el tiempo (probablemente con Claude Code) y
arrancar rápido. El autor tiene base en Python y experiencia previa en desarrollo.

## Opciones consideradas

### Opción A — Django + Postgres

- A favor: panel de administración, autenticación y permisos resueltos de fábrica
  (el admin sirve directo para cargar el Excel inicial y gestionar datos maestros);
  un solo proyecto; ecosistema enorme y estable; ORM y migraciones sólidas; fácil
  de sostener con Claude Code. Django 5.2 es LTS (soporte hasta abril 2028).
- En contra: menos flexible para interfaces muy dinámicas tipo SPA.

### Opción B — Next.js + Postgres (TypeScript)

- A favor: un solo lenguaje de punta a punta; UI moderna muy dinámica; despliegue
  trivial en plataformas gestionadas.
- En contra: hay que construir a mano el admin, la autenticación y los permisos que
  Django trae listos; más código para el mismo CRUD interno.

### Opción C — FastAPI + React + Postgres

- A favor: máxima flexibilidad y escalabilidad; frontend desacoplado.
- En contra: dos proyectos que coordinar; sobredimensionado para una herramienta
  interna de 6 usuarios.

## Decisión

Escogimos **Django 5.2 LTS + PostgreSQL** porque el producto es esencialmente CRUD
con administración, roles y permisos, y Django resuelve justo eso con el menor
código posible, dejando una base que las futuras sesiones de Claude Code sostienen
con facilidad. El panel de administración cubre desde ya la gestión de datos
maestros y la carga inicial.

Decisiones que acompañan:

- **Base de datos**: PostgreSQL en producción; SQLite como fallback automático en
  desarrollo local (sin servidor) para que el proyecto corra de una.
- **Autenticación**: correo + contraseña (usuario propio `accounts.User` con el
  correo como identificador), reforzado por una lista blanca de correos
  (`AllowlistModelBackend`). Se descartó login con Google en v1 para no depender de
  configurar OAuth; queda como posible mejora futura.
- **Hosting**: Railway (Procfile + Postgres gestionado); el autor ya tiene la CLI.
- **Tests**: pytest + pytest-django, con test de humo desde el primer commit.
- **Lint/format**: ruff.
- **Gestor de paquetes**: pip + venv, dependencias declaradas en `pyproject.toml`.
- **Desarrollo con Docker**: `docker-compose` (app + Postgres) para reproducir prod.
- **Móvil / PWA**: la interfaz es responsive y la app es **instalable como PWA**
  (web app manifest + service worker servidos por Django — p. ej. `django-pwa` o un
  manifest/SW propios). No hay app nativa ni publicación en tiendas; se instala desde
  el navegador ("agregar a pantalla de inicio").
- **Licencia**: privada.

Se descartó CI en GitHub Actions y la convención de commits automatizada para el
arranque (se pueden agregar después); Docker sí se incluyó por pedido explícito.

## Consecuencias

**Lo que ganamos**: admin, auth y permisos listos; velocidad para llegar a un v1
operable; una base estable y muy documentada; LTS con soporte hasta 2028.

**Lo que aceptamos a cambio**: para pantallas de operador muy pulidas (selector de
compañía, flujo guiado de entrega/devolución, búsqueda a medida) habrá que escribir
vistas y plantillas propias por encima del admin.

**Qué haría que revisáramos esta decisión**: que el producto crezca hacia una
interfaz muy interactiva (tiempo real, mucho JavaScript) o hacia una API pública
consumida por otras apps; ahí un frontend desacoplado (Opción B o C) empezaría a
pagar su costo.
