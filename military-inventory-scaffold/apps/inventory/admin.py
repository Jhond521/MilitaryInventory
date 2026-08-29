from django.contrib import admin

from .models import (
    Armamento,
    CampoPersonalizado,
    Compania,
    Deposito,
    Movimiento,
    Soldado,
    TipoArmamento,
    Unidad,
)


@admin.register(Unidad)
class UnidadAdmin(admin.ModelAdmin):
    list_display = ("nombre",)


@admin.register(Compania)
class CompaniaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "unidad")
    list_filter = ("unidad",)
    search_fields = ("nombre",)


@admin.register(Deposito)
class DepositoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "descripcion")
    search_fields = ("nombre",)


@admin.register(Soldado)
class SoldadoAdmin(admin.ModelAdmin):
    list_display = ("apellidos_nombres", "compania")
    list_filter = ("compania",)
    search_fields = ("apellidos_nombres",)


@admin.register(TipoArmamento)
class TipoArmamentoAdmin(admin.ModelAdmin):
    search_fields = ("nombre",)


@admin.register(CampoPersonalizado)
class CampoPersonalizadoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo")


class MovimientoInline(admin.TabularInline):
    model = Movimiento
    extra = 0
    can_delete = False
    readonly_fields = ("tipo", "soldado", "deposito", "usuario", "observacion", "fecha")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Armamento)
class ArmamentoAdmin(admin.ModelAdmin):
    list_display = (
        "numero_serie",
        "tipo",
        "compania",
        "ubicacion",
        "deposito",
        "soldado",
        "estado",
    )
    list_filter = ("compania", "ubicacion", "estado", "deposito", "tipo")
    search_fields = ("numero_serie", "soldado__apellidos_nombres", "tipo__nombre")
    autocomplete_fields = ("tipo", "compania", "deposito", "soldado")
    inlines = [MovimientoInline]


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo", "armamento", "soldado", "deposito", "usuario")
    list_filter = ("tipo", "fecha")
    search_fields = ("armamento__numero_serie", "soldado__apellidos_nombres")
    readonly_fields = ("fecha",)
