from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

from apps.accounts.admin_mixins import MovimientoRegistrableMixin, ViewOnlyForEnlaceMixin

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
from .views import SESSION_KEY


class CompaniaContextoMixin:
    """Filtra el changelist por la compañía de trabajo en sesión (RF-02) a
    menos que el usuario ya haya elegido un filtro de compañía explícito, o
    haya pedido ver todas (S-2: la selección es un valor por defecto, no una
    restricción). El enlace "ver todas" del header pasa `?ver_todas_companias=1`
    porque el enlace "Todo" del propio filtro de Django, al ser el único
    filtro activo, genera una cadena de consulta vacía indistinguible de una
    visita nueva a la página. Ese parámetro no es un lookup de campo real, así
    que hay que quitarlo de `request.GET` antes de que el propio changelist de
    Django intente validarlo/usarlo como filtro (fallaría con
    `IncorrectLookupParameters`) — se guarda como atributo en `request` para
    que `get_queryset` todavía sepa qué se pidió."""

    def changelist_view(self, request, extra_context=None):
        if "ver_todas_companias" in request.GET:
            request._ver_todas_companias = True
            params = request.GET.copy()
            params.pop("ver_todas_companias")
            request.GET = params
        return super().changelist_view(request, extra_context)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        pidio_ver_todas = getattr(request, "_ver_todas_companias", False)
        if "compania__id__exact" not in request.GET and not pidio_ver_todas:
            compania_id = request.session.get(SESSION_KEY)
            if compania_id:
                qs = qs.filter(compania_id=compania_id)
        return qs


@admin.register(Unidad)
class UnidadAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
    list_display = ("nombre",)


@admin.register(Compania)
class CompaniaAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
    list_display = ("nombre", "unidad")
    list_filter = ("unidad",)
    search_fields = ("nombre",)


@admin.register(Deposito)
class DepositoAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
    list_display = ("nombre", "descripcion")
    search_fields = ("nombre",)


@admin.register(Peloton)
class PelotonAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
    list_display = ("nombre", "compania")
    list_filter = ("compania",)
    search_fields = ("nombre",)
    autocomplete_fields = ("compania",)


@admin.register(Soldado)
class SoldadoAdmin(ViewOnlyForEnlaceMixin, CompaniaContextoMixin, admin.ModelAdmin):
    list_display = ("apellidos_nombres", "compania", "peloton")
    list_filter = ("compania", "peloton")
    search_fields = ("apellidos_nombres",)
    autocomplete_fields = ("compania", "peloton")


@admin.register(TipoArmamento)
class TipoArmamentoAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
    list_display = ("nombre", "control")
    list_filter = ("control",)
    search_fields = ("nombre",)


@admin.register(CampoPersonalizado)
class CampoPersonalizadoAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
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


class BajaForm(forms.Form):
    motivo = forms.ChoiceField(choices=Armamento.MotivoBaja.choices, label="Motivo")
    fecha = forms.DateField(
        label="Fecha de baja",
        initial=timezone.localdate,
        # El input HTML type="date" exige el valor en formato yyyy-mm-dd; el
        # formato de fecha por defecto del locale (es-co) es dd/mm/yyyy, así
        # que sin esto el navegador descarta silenciosamente el valor inicial.
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    observacion = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


def campo_nombre_de_campo(campo):
    """Nombre técnico (HTML) del campo de formulario para un CampoPersonalizado."""
    return f"campo_{campo.pk}"


def campo_a_form_field(campo, valor_inicial):
    """Construye el `forms.Field` para capturar un CampoPersonalizado según su
    tipo (texto/número/fecha) — RF-08. Solo aplica al armamento: no hay
    equivalente para Soldado ni TipoArmamento (NO-2)."""
    if campo.tipo == CampoPersonalizado.Tipo.NUMERO:
        return forms.DecimalField(required=False, label=campo.nombre, initial=valor_inicial)
    if campo.tipo == CampoPersonalizado.Tipo.FECHA:
        return forms.DateField(
            required=False,
            label=campo.nombre,
            initial=valor_inicial,
            widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        )
    return forms.CharField(required=False, label=campo.nombre, initial=valor_inicial)


class MovimientoInline(admin.TabularInline):
    model = Movimiento
    extra = 0
    can_delete = False
    readonly_fields = ("tipo", "soldado", "deposito", "usuario", "observacion", "fecha")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Armamento)
class ArmamentoAdmin(ViewOnlyForEnlaceMixin, CompaniaContextoMixin, admin.ModelAdmin):
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
    # Búsqueda global por cualquier dato (RF-12): serie, soldado, tipo,
    # compañía, depósito y campos personalizados (JSON de datos_extra).
    search_fields = (
        "numero_serie",
        "soldado__apellidos_nombres",
        "tipo__nombre",
        "compania__nombre",
        "deposito__nombre",
        "datos_extra",
    )
    autocomplete_fields = ("tipo", "compania", "deposito", "soldado")
    inlines = [MovimientoInline]
    actions = ["accion_entregar", "accion_devolver", "accion_dar_de_baja"]
    # El JSON crudo no se edita a mano — get_form()/get_fieldsets() abajo
    # generan un campo de formulario propio por cada CampoPersonalizado
    # (RF-08) y save_model() los guarda en datos_extra.
    exclude = ("datos_extra",)

    @admin.display(description="Pelotón")
    def peloton_actual(self, obj):
        return obj.peloton_actual

    def get_form(self, request, obj=None, **kwargs):
        # _changeform_view pasa fields=flatten_fieldsets(get_fieldsets(...)),
        # que incluye los campo_<pk> agregados en get_fieldsets() de abajo —
        # y modelform_factory revienta porque esos no son campos reales del
        # modelo. Basta con quitarlos de la lista ya recibida (NO recalcular
        # llamando a get_fieldsets()/get_fields() aquí: esas, internamente,
        # vuelven a llamar a self.get_form() — con self siempre resuelto a
        # esta clase — y eso es recursión infinita). Cuando `fields` llega
        # como None (llamada interna de Django vía _get_form_for_get_fields,
        # con change=False) se deja tal cual: ese caso no necesita filtro.
        if kwargs.get("fields"):
            kwargs["fields"] = [f for f in kwargs["fields"] if not f.startswith("campo_")]
        form_class = super().get_form(request, obj, **kwargs)
        if not self.has_change_permission(request, obj):
            # Sin permiso de "change" Django ya vuelve todo el form de solo
            # lectura; los campo_<pk> no son campos reales del modelo así que
            # ese mecanismo no los cubre — más simple no agregarlos aquí y
            # mostrarlos en su lugar como un resumen de solo lectura
            # (campos_personalizados_resumen, en get_fieldsets()).
            return form_class
        campos = list(CampoPersonalizado.objects.all())

        class ArmamentoConCamposForm(form_class):
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, **form_kwargs)
                datos_extra = (self.instance.datos_extra or {}) if self.instance else {}
                for campo in campos:
                    self.fields[campo_nombre_de_campo(campo)] = campo_a_form_field(
                        campo, datos_extra.get(campo.nombre)
                    )

        return ArmamentoConCamposForm

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        campos = list(CampoPersonalizado.objects.all())
        if not campos:
            return fieldsets
        if self.has_change_permission(request, obj):
            campo_field_names = [campo_nombre_de_campo(c) for c in campos]
        else:
            # AdminReadonlyField solo sabe leer atributos reales del modelo o
            # métodos del ModelAdmin — no entradas sueltas de form.fields —
            # así que en modo solo-lectura se muestra un único resumen
            # (campos_personalizados_resumen) en vez de un campo por cada uno.
            campo_field_names = ["campos_personalizados_resumen"]
        fieldsets.append(("Campos personalizados", {"fields": campo_field_names}))
        return fieldsets

    @admin.display(description="Campos personalizados")
    def campos_personalizados_resumen(self, obj):
        datos_extra = obj.datos_extra or {}
        campos = CampoPersonalizado.objects.all()
        if not campos:
            return "—"
        return format_html_join(
            mark_safe("<br>"),
            "{}: {}",
            ((campo.nombre, datos_extra.get(campo.nombre, "—")) for campo in campos),
        )

    def save_model(self, request, obj, form, change):
        datos_extra = dict(obj.datos_extra or {})
        for campo in CampoPersonalizado.objects.all():
            nombre_campo = campo_nombre_de_campo(campo)
            if nombre_campo not in form.cleaned_data:
                continue
            valor = form.cleaned_data[nombre_campo]
            if valor in (None, ""):
                datos_extra.pop(campo.nombre, None)
            else:
                datos_extra[campo.nombre] = valor
        obj.datos_extra = datos_extra
        super().save_model(request, obj, form, change)

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
            path(
                "dar-de-baja/",
                self.admin_site.admin_view(self.dar_de_baja_view),
                name="inventory_armamento_dar_de_baja",
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

    @admin.action(description="Dar de baja", permissions=["change"])
    def accion_dar_de_baja(self, request, queryset):
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        return redirect(f"{reverse('admin:inventory_armamento_dar_de_baja')}?ids={ids}")

    @staticmethod
    def _seleccion(request, ubicacion_esperada):
        ids = request.POST.get("ids") or request.GET.get("ids") or ""
        pks = [int(pk) for pk in ids.split(",") if pk.strip()]
        return ids, Armamento.objects.filter(pk__in=pks, ubicacion=ubicacion_esperada)

    def entregar_view(self, request):
        # Administrador y enlace pueden registrar movimientos (RF-10) aunque
        # enlace no tenga permiso de "change" sobre Armamento (H-03) — por
        # eso se valida contra "view", no contra "change".
        if not self.has_view_permission(request):
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
        # Ver la nota en entregar_view: RF-10 autoriza a enlace, que solo
        # tiene permiso de "view" sobre Armamento.
        if not self.has_view_permission(request):
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

    def dar_de_baja_view(self, request):
        # Solo administrador (RF-11) — a diferencia de entregar/devolver,
        # que RF-10 autoriza también para enlace.
        if not self.has_change_permission(request):
            raise PermissionDenied
        ids = request.POST.get("ids") or request.GET.get("ids") or ""
        pks = [int(pk) for pk in ids.split(",") if pk.strip()]
        armamentos = Armamento.objects.filter(pk__in=pks, estado=Armamento.Estado.ACTIVO)
        if not armamentos.exists():
            self.message_user(
                request, "Selecciona al menos un arma activa.", level=messages.ERROR
            )
            return redirect("admin:inventory_armamento_changelist")

        if request.method == "POST":
            form = BajaForm(request.POST)
            if form.is_valid():
                motivo = form.cleaned_data["motivo"]
                fecha = form.cleaned_data["fecha"]
                observacion = form.cleaned_data["observacion"]
                cantidad = armamentos.count()
                for arma in armamentos:
                    arma.dar_de_baja(
                        motivo=motivo, fecha=fecha, usuario=request.user, observacion=observacion
                    )
                self.message_user(request, f"{cantidad} arma(s) dada(s) de baja.")
                return redirect("admin:inventory_armamento_changelist")
        else:
            form = BajaForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Dar de baja",
            "form": form,
            "armamentos": armamentos,
            "ids": ids,
        }
        return render(request, "admin/inventory/armamento/dar_de_baja.html", context)


@admin.register(Movimiento)
class MovimientoAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
    list_display = ("fecha", "tipo", "armamento", "soldado", "deposito", "usuario")
    list_filter = ("tipo", "fecha")
    search_fields = ("armamento__numero_serie", "soldado__apellidos_nombres")
    readonly_fields = ("fecha",)


@admin.register(Existencia)
class ExistenciaAdmin(ViewOnlyForEnlaceMixin, admin.ModelAdmin):
    list_display = ("tipo", "compania", "deposito", "lote", "cantidad")
    list_filter = ("compania", "deposito", "tipo")
    search_fields = ("tipo__nombre", "lote")
    autocomplete_fields = ("tipo", "compania", "deposito")


@admin.register(Prestamo)
class PrestamoAdmin(MovimientoRegistrableMixin, admin.ModelAdmin):
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
    # El usuario que registra el préstamo se asigna solo, al guardar (RNF-03) —
    # no se le pide a quien registra que se busque a sí mismo en una lista.
    exclude = ("usuario",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.usuario = request.user
        super().save_model(request, obj, form, change)
