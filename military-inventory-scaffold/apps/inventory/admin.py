from django.contrib import admin

from .models import (
    Armamento,
    CampoPersonalizado,
    Compania,
    Deposito,
    Existencia,
    Movimiento,
    Peloton,
    Prestamo,
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


@admin.register(Peloton)
class PelotonAdmin(admin.ModelAdmin):
    list_display = ("nombre", "compania")
    list_filter = ("compania",)
    search_fields = ("nombre",)
    autocomplete_fields = ("compania",)


@admin.register(Soldado)
class SoldadoAdmin(admin.ModelAdmin):
    list_display = ("apellidos_nombres", "compania", "peloton")
    list_filter = ("compania", "peloton")
    search_fields = ("apellidos_nombres",)
    autocomplete_fields = ("compania", "peloton")


@admin.register(TipoArmamento)
class TipoArmamentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "control")
    list_filter = ("control",)
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
        "peloton_actual",
        "estado",
    )
    list_filter = ("compania", "ubicacion", "estado", "deposito", "tipo")
    search_fields = ("numero_serie", "soldado__apellidos_nombres", "tipo__nombre")
    autocomplete_fields = ("tipo", "compania", "deposito", "soldado")
    inlines = [MovimientoInline]

    @admin.display(description="Pelotón")
    def peloton_actual(self, obj):
        return obj.peloton_actual


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo", "armamento", "soldado", "deposito", "usuario")
    list_filter = ("tipo", "fecha")
    search_fields = ("armamento__numero_serie", "soldado__apellidos_nombres")
    readonly_fields = ("fecha",)


@admin.register(Existencia)
class ExistenciaAdmin(admin.ModelAdmin):
    list_display = ("tipo", "compania", "deposito", "lote", "cantidad")
    list_filter = ("compania", "deposito", "tipo")
    search_fields = ("tipo__nombre", "lote")
    autocomplete_fields = ("tipo", "compania", "deposito")


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "tipo",
        "lote",
        "cantidad",
        "compania_origen",
        "compania_destino",
        "usuario",
    )
    list_filter = ("tipo", "compania_origen", "compania_destino")
    search_fields = ("tipo__nombre", "lote")
    readonly_fields = ("fecha",)
    autocomplete_fields = ("tipo", "deposito", "compania_origen", "compania_destino")
