from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("compania/", views.elegir_compania, name="elegir_compania"),
]
