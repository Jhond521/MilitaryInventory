from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path, reverse

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


class EntregaForm(forms.Form):
    soldado = forms.ModelChoiceField(queryset=Soldado.objects.none(), label="Soldado")
    observacion = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, compania_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if compania_id is not None:
            self.fields["soldado"].queryset = Soldado.objects.filter(compania_id=compania_id)


class DevolucionForm(forms.Form):
    deposito = forms.ModelChoiceField(queryset=Deposito.objects.all(), label="Depósito")
    observacion = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


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
    actions = ["accion_entregar", "accion_devolver"]

    @admin.display(description="Pelotón")
    def peloton_actual(self, obj):
        return obj.peloton_actual

    def get_urls(self):
        custom = [
            path(
                "entregar/",
                self.admin_site.admin_view(self.entregar_view),
                name="inventory_armamento_entregar",
            ),
            path(
                "devolver/",
                self.admin_site.admin_view(self.devolver_view),
                name="inventory_armamento_devolver",
            ),
        ]
        return custom + super().get_urls()

    @admin.action(description="Entregar a un soldado")
    def accion_entregar(self, request, queryset):
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        return redirect(f"{reverse('admin:inventory_armamento_entregar')}?ids={ids}")

    @admin.action(description="Devolver a depósito")
    def accion_devolver(self, request, queryset):
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        return redirect(f"{reverse('admin:inventory_armamento_devolver')}?ids={ids}")

    @staticmethod
    def _seleccion(request, ubicacion_esperada):
        ids = request.POST.get("ids") or request.GET.get("ids") or ""
        pks = [int(pk) for pk in ids.split(",") if pk.strip()]
        return ids, Armamento.objects.filter(pk__in=pks, ubicacion=ubicacion_esperada)

    def entregar_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        ids, armamentos = self._seleccion(request, Armamento.Ubicacion.DEPOSITO)
        if not armamentos.exists():
            self.message_user(
                request, "Selecciona al menos un arma en depósito.", level=messages.ERROR
            )
            return redirect("admin:inventory_armamento_changelist")

        companias = set(armamentos.values_list("compania_id", flat=True))
        if len(companias) > 1:
            self.message_user(
                request,
                "Todas las armas seleccionadas deben ser de la misma compañía.",
                level=messages.ERROR,
            )
            return redirect("admin:inventory_armamento_changelist")
        compania_id = companias.pop()

        if request.method == "POST":
            form = EntregaForm(request.POST, compania_id=compania_id)
            if form.is_valid():
                soldado = form.cleaned_data["soldado"]
                observacion = form.cleaned_data["observacion"]
                cantidad = armamentos.count()
                for arma in armamentos:
                    arma.entregar(soldado=soldado, usuario=request.user, observacion=observacion)
                self.message_user(request, f"{cantidad} arma(s) entregada(s) a {soldado}.")
                return redirect("admin:inventory_armamento_changelist")
        else:
            form = EntregaForm(compania_id=compania_id)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Entregar a un soldado",
            "form": form,
            "armamentos": armamentos,
            "ids": ids,
        }
        return render(request, "admin/inventory/armamento/entregar.html", context)

    def devolver_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        ids, armamentos = self._seleccion(request, Armamento.Ubicacion.EN_MANO)
        if not armamentos.exists():
            self.message_user(
                request, "Selecciona al menos un arma en mano.", level=messages.ERROR
            )
            return redirect("admin:inventory_armamento_changelist")

        if request.method == "POST":
            form = DevolucionForm(request.POST)
            if form.is_valid():
                deposito = form.cleaned_data["deposito"]
                observacion = form.cleaned_data["observacion"]
                cantidad = armamentos.count()
                for arma in armamentos:
                    arma.devolver(deposito=deposito, usuario=request.user, observacion=observacion)
                self.message_user(request, f"{cantidad} arma(s) devuelta(s) a {deposito}.")
                return redirect("admin:inventory_armamento_changelist")
        else:
            form = DevolucionForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Devolver a depósito",
            "form": form,
            "armamentos": armamentos,
            "ids": ids,
        }
        return render(request, "admin/inventory/armamento/devolver.html", context)


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
