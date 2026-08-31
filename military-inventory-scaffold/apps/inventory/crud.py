"""Generic CRUD for the small master-data models (Unidad, Compañía, Depósito,
Pelotón, TipoArmamento, CampoPersonalizado) — everyone can view, only ADMIN
can add/edit/delete (RF-01, H-03; same rule as the old `ViewOnlyForEnlaceMixin`
in `apps/accounts/admin_mixins.py`, ported here as view-shaped mixins now that
these screens are plain Django views instead of `ModelAdmin`s).

Django's own generic `ListView`/`CreateView`/`UpdateView`/`DeleteView` are the
right tool for "simple form over one model" — reused here instead of hand-
rolling function views, with three shared templates styled to match the rest
of the mobile UI.
"""
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.accounts.permissions import es_administrador, usuario_autorizado

from .models import CampoPersonalizado, Compania, Deposito, Peloton, TipoArmamento, Unidad


class AutorizadoMixin(UserPassesTestMixin):
    login_url = "accounts:login"

    def test_func(self):
        return usuario_autorizado(self.request.user)


class AdminMixin(UserPassesTestMixin):
    login_url = "accounts:login"

    def test_func(self):
        return es_administrador(self.request.user)


class MasterListView(AutorizadoMixin, ListView):
    template_name = "inventory/master_list.html"
    titulo = ""
    campos = ()  # [(etiqueta, nombre_de_campo), ...]
    url_base = ""  # p.ej. "inventory:compania" -> _crear/_editar/_borrar

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "titulo": self.titulo,
                "campos": self.campos,
                "crear_url": f"{self.url_base}_crear",
                "editar_url": f"{self.url_base}_editar",
                "borrar_url": f"{self.url_base}_borrar",
            }
        )
        return context


class MasterFormMixin:
    template_name = "inventory/master_form.html"

    def get_success_url(self):
        return reverse_lazy(f"{self.url_base}_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["titulo"] = self.titulo
        context["cancelar_url"] = f"{self.url_base}_list"
        return context


class MasterCreateView(AdminMixin, MasterFormMixin, CreateView):
    pass


class MasterUpdateView(AdminMixin, MasterFormMixin, UpdateView):
    pass


class MasterDeleteView(AdminMixin, DeleteView):
    template_name = "inventory/master_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy(f"{self.url_base}_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancelar_url"] = f"{self.url_base}_list"
        return context

    def form_valid(self, form):
        # PROTECT es la regla en todas las FK de datos maestros (nunca se
        # quiere perder historial borrando en cascada) — sin esto, borrar
        # algo referenciado (p.ej. una compañía con soldados) revienta con
        # un ProtectedError sin manejar (500) en vez de un mensaje claro.
        try:
            return super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f'No se puede borrar "{self.object}" porque otros registros dependen de él.',
            )
            return redirect(f"{self.url_base}_list")


# --- Unidad --------------------------------------------------------------

class UnidadListView(MasterListView):
    model = Unidad
    titulo = "Unidades"
    campos = (("Nombre", "nombre"),)
    url_base = "inventory:unidad"


class UnidadCreateView(MasterCreateView):
    model = Unidad
    fields = ["nombre"]
    titulo = "Añadir unidad"
    url_base = "inventory:unidad"


class UnidadUpdateView(MasterUpdateView):
    model = Unidad
    fields = ["nombre"]
    titulo = "Editar unidad"
    url_base = "inventory:unidad"


class UnidadDeleteView(MasterDeleteView):
    model = Unidad
    url_base = "inventory:unidad"


# --- Compañía --------------------------------------------------------------

class CompaniaListView(MasterListView):
    model = Compania
    titulo = "Compañías"
    campos = (("Nombre", "nombre"), ("Unidad", "unidad"))
    url_base = "inventory:compania"


class CompaniaCreateView(MasterCreateView):
    model = Compania
    fields = ["nombre", "unidad"]
    titulo = "Añadir compañía"
    url_base = "inventory:compania"


class CompaniaUpdateView(MasterUpdateView):
    model = Compania
    fields = ["nombre", "unidad"]
    titulo = "Editar compañía"
    url_base = "inventory:compania"


class CompaniaDeleteView(MasterDeleteView):
    model = Compania
    url_base = "inventory:compania"


# --- Depósito --------------------------------------------------------------

class DepositoListView(MasterListView):
    model = Deposito
    titulo = "Depósitos"
    campos = (("Nombre", "nombre"), ("Descripción", "descripcion"))
    url_base = "inventory:deposito"


class DepositoCreateView(MasterCreateView):
    model = Deposito
    fields = ["nombre", "descripcion"]
    titulo = "Añadir depósito"
    url_base = "inventory:deposito"


class DepositoUpdateView(MasterUpdateView):
    model = Deposito
    fields = ["nombre", "descripcion"]
    titulo = "Editar depósito"
    url_base = "inventory:deposito"


class DepositoDeleteView(MasterDeleteView):
    model = Deposito
    url_base = "inventory:deposito"


# --- Pelotón --------------------------------------------------------------

class PelotonListView(MasterListView):
    model = Peloton
    titulo = "Pelotones"
    campos = (("Nombre", "nombre"), ("Compañía", "compania"))
    url_base = "inventory:peloton"


class PelotonCreateView(MasterCreateView):
    model = Peloton
    fields = ["nombre", "compania"]
    titulo = "Añadir pelotón"
    url_base = "inventory:peloton"


class PelotonUpdateView(MasterUpdateView):
    model = Peloton
    fields = ["nombre", "compania"]
    titulo = "Editar pelotón"
    url_base = "inventory:peloton"


class PelotonDeleteView(MasterDeleteView):
    model = Peloton
    url_base = "inventory:peloton"


# --- TipoArmamento ----------------------------------------------------------

class TipoArmamentoListView(MasterListView):
    model = TipoArmamento
    titulo = "Tipos de armamento"
    campos = (("Nombre", "nombre"), ("Control", "control"))
    url_base = "inventory:tipoarmamento"


class TipoArmamentoCreateView(MasterCreateView):
    model = TipoArmamento
    fields = ["nombre", "control"]
    titulo = "Añadir tipo de armamento"
    url_base = "inventory:tipoarmamento"


class TipoArmamentoUpdateView(MasterUpdateView):
    model = TipoArmamento
    fields = ["nombre", "control"]
    titulo = "Editar tipo de armamento"
    url_base = "inventory:tipoarmamento"


class TipoArmamentoDeleteView(MasterDeleteView):
    model = TipoArmamento
    url_base = "inventory:tipoarmamento"


# --- CampoPersonalizado ------------------------------------------------------

class CampoPersonalizadoListView(MasterListView):
    model = CampoPersonalizado
    titulo = "Campos personalizados"
    campos = (("Nombre", "nombre"), ("Tipo", "tipo"))
    url_base = "inventory:campopersonalizado"


class CampoPersonalizadoCreateView(MasterCreateView):
    model = CampoPersonalizado
    fields = ["nombre", "tipo"]
    titulo = "Añadir campo personalizado"
    url_base = "inventory:campopersonalizado"


class CampoPersonalizadoUpdateView(MasterUpdateView):
    model = CampoPersonalizado
    fields = ["nombre", "tipo"]
    titulo = "Editar campo personalizado"
    url_base = "inventory:campopersonalizado"


class CampoPersonalizadoDeleteView(MasterDeleteView):
    model = CampoPersonalizado
    url_base = "inventory:campopersonalizado"
