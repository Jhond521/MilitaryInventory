from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .admin_mixins import AdminOnlyMixin
from .models import User


@admin.register(User)
class UserAdmin(AdminOnlyMixin, BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "role", "is_active", "is_superuser")
    list_filter = ("role", "is_active", "is_superuser")
    search_fields = ("email", "first_name", "last_name")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Datos personales", {"fields": ("first_name", "last_name")}),
        ("Rol y permisos", {"fields": (
            "role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions",
        )}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
        }),
    )
