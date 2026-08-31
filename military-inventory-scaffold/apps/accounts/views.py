"""Auth screens (login/logout/password change) and user management (H-01),
all in SIGA's own mobile-first design — replaces the Django admin's built-in
versions of these now that the admin is being retired.
"""
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import SetPasswordForm
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from .forms import UsuarioForm
from .models import User
from .permissions import requiere_admin, requiere_autorizado


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        # "Mantener sesión" sin marcar => la sesión expira al cerrar el
        # navegador en vez de usar el default de Django (2 semanas).
        if not self.request.POST.get("remember"):
            self.request.session.set_expiry(0)
        return response


def recuperar_password(request):
    return render(request, "accounts/recuperar_password.html")


class LogoutView(auth_views.LogoutView):
    next_page = "accounts:login"


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:password_change_done")


class PasswordChangeDoneView(auth_views.PasswordChangeDoneView):
    template_name = "accounts/password_change_done.html"


@requiere_autorizado
def cuenta(request):
    return render(request, "accounts/cuenta.html")


@requiere_admin
def usuario_list(request):
    usuarios = User.objects.order_by("email")
    return render(request, "accounts/usuario_list.html", {"usuarios": usuarios})


@requiere_admin
def usuario_crear(request):
    if request.method == "POST":
        form = UsuarioForm(request.POST)
        if form.is_valid():
            usuario = form.save(commit=False)
            usuario.set_password(form.cleaned_data["password"])
            usuario.save()
            messages.success(request, f"Usuario {usuario.email} creado.")
            return redirect("accounts:usuario_list")
    else:
        form = UsuarioForm()
    return render(
        request, "accounts/usuario_form.html", {"form": form, "titulo": "Añadir usuario"}
    )


@requiere_admin
def usuario_editar(request, pk):
    usuario = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UsuarioForm(request.POST, instance=usuario, es_edicion=True)
        if form.is_valid():
            # Con 6 usuarios en total, un ADMIN podría quitarse a sí mismo el
            # rol o desactivarse sin darse cuenta, dejando a todos sin nadie
            # que gestione usuarios (nadie más puede revertirlo desde la UI).
            if usuario.pk == request.user.pk and (
                form.cleaned_data["role"] != User.Role.ADMIN
                or not form.cleaned_data["is_active"]
            ):
                messages.error(
                    request,
                    "No puedes quitarte a ti mismo el rol de administrador ni desactivarte.",
                )
                return render(
                    request,
                    "accounts/usuario_form.html",
                    {"form": form, "titulo": f"Editar {usuario.email}", "usuario": usuario},
                )
            form.save()
            messages.success(request, f"Usuario {usuario.email} actualizado.")
            return redirect("accounts:usuario_list")
    else:
        form = UsuarioForm(instance=usuario, es_edicion=True)
    return render(
        request,
        "accounts/usuario_form.html",
        {"form": form, "titulo": f"Editar {usuario.email}", "usuario": usuario},
    )


@requiere_admin
def usuario_restablecer_password(request, pk):
    usuario = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = SetPasswordForm(usuario, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Contraseña de {usuario.email} restablecida.")
            return redirect("accounts:usuario_list")
    else:
        form = SetPasswordForm(usuario)
    return render(
        request,
        "accounts/usuario_password_form.html",
        {"form": form, "usuario": usuario},
    )
