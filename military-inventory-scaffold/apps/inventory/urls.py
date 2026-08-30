from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.armamento_list, name="armamento_list"),
    path("armamento/<int:pk>/entregar/", views.armamento_entregar, name="armamento_entregar"),
    path("armamento/<int:pk>/devolver/", views.armamento_devolver, name="armamento_devolver"),
    path("movimientos/", views.movimiento_list, name="movimiento_list"),
    path("soldados/", views.soldado_list, name="soldado_list"),
    path("municion/", views.existencia_list, name="existencia_list"),
    path("compania/", views.elegir_compania, name="elegir_compania"),
]
