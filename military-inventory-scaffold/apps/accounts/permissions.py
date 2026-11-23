"""Role-based view permission gates (RF-01, RF-10, H-03).

Replaces `admin_mixins.py` (ModelAdmin-shaped) now that the app's own views —
not the Django admin — are the primary surface. Three roles exist
(`User.Role`): ADMIN has full control over master data; ENLACE can view/
search everything and register movements, but never create/edit/delete
master data; CONSULTA (issue #35) can only view/search. So there are three
gates: `requiere_autorizado` (any active user — read-only screens),
`requiere_operador` (ADMIN or ENLACE — entregar/devolver/prestar) and
`requiere_admin`. `createsuperuser` always sets role=ADMIN (see
`apps.accounts.models.UserManager`), so these checks don't need to
special-case `is_superuser` separately from `role`.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def es_administrador(user) -> bool:
    return bool(user and user.is_authenticated and user.is_admin_role)


def usuario_autorizado(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active)


def puede_operar(user) -> bool:
    """Registrar movimientos (entregar/devolver/prestar): ADMIN o ENLACE,
    nunca CONSULTA (issue #35)."""
    return usuario_autorizado(user) and user.puede_operar


def _requiere(test_func):
    """Como `user_passes_test`, pero con el mismo criterio que
    `UserPassesTestMixin` en vistas basadas en clase (`crud.py`): un usuario
    ya autenticado que no pasa la prueba recibe 403, no un redirect a login
    — redirigirlo generaría un bucle infinito (login ya autenticado -> vuelve
    a la misma URL -> falla la prueba otra vez -> login...)."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if test_func(request.user):
                return view_func(request, *args, **kwargs)
            if request.user.is_authenticated:
                raise PermissionDenied
            return redirect_to_login(request.get_full_path(), "accounts:login")

        return wrapped

    return decorator


requiere_autorizado = _requiere(usuario_autorizado)
requiere_operador = _requiere(puede_operar)
requiere_admin = _requiere(es_administrador)
