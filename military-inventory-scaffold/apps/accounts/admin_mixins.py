"""Role-based admin permission gates (RF-01, RF-10, H-03).

Only two roles exist (`User.Role`): ADMIN has full control over master
data; ENLACE can view/search everything and register movements, but never
create/edit/delete master data. `createsuperuser` always sets role=ADMIN
(see `apps.accounts.models.UserManager`), so these checks don't need to
special-case `is_superuser` separately from `role`.
"""


def _es_administrador(request):
    user = request.user
    return bool(user and user.is_authenticated and user.is_admin_role)


def _es_staff_autorizado(request):
    user = request.user
    return bool(user and user.is_active and user.is_staff)


class ViewOnlyForEnlaceMixin:
    """Datos maestros: cualquier usuario autorizado puede ver/buscar, pero
    solo Administrador crea, edita o borra."""

    def has_module_permission(self, request):
        # Django's default delegates to request.user.has_module_perms(),
        # which checks real auth.Permission rows — we don't use those (no
        # groups/permissions are ever assigned), so it would hide every app
        # section from non-superuser users regardless of the overrides
        # below. Base this on the same role check instead.
        return _es_staff_autorizado(request)

    def has_view_permission(self, request, obj=None):
        return _es_staff_autorizado(request)

    def has_add_permission(self, request):
        return _es_administrador(request)

    def has_change_permission(self, request, obj=None):
        return _es_administrador(request)

    def has_delete_permission(self, request, obj=None):
        return _es_administrador(request)


class AdminOnlyMixin(ViewOnlyForEnlaceMixin):
    """Como ViewOnlyForEnlaceMixin, pero Enlace tampoco puede ver — para
    pantallas sensibles como la gestión de usuarios."""

    def has_module_permission(self, request):
        return _es_administrador(request)

    def has_view_permission(self, request, obj=None):
        return _es_administrador(request)


class MovimientoRegistrableMixin(ViewOnlyForEnlaceMixin):
    """Como ViewOnlyForEnlaceMixin, pero crear un registro es *registrar un
    movimiento* (RF-15), no tocar datos maestros — ambos roles pueden."""

    def has_add_permission(self, request):
        return _es_staff_autorizado(request)
