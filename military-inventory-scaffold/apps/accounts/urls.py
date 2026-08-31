from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("recuperar-password/", views.recuperar_password, name="recuperar_password"),
    path("mi-cuenta/", views.cuenta, name="cuenta"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path(
        "password/hecho/",
        views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    path("usuarios/", views.usuario_list, name="usuario_list"),
    path("usuarios/nuevo/", views.usuario_crear, name="usuario_crear"),
    path("usuarios/<int:pk>/editar/", views.usuario_editar, name="usuario_editar"),
    path(
        "usuarios/<int:pk>/password/",
        views.usuario_restablecer_password,
        name="usuario_restablecer_password",
    ),
]
