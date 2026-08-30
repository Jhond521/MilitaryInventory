from django.urls import path

from . import crud, views

app_name = "inventory"


def _crud_urls(prefix, name, class_prefix):
    """Las 4 rutas list/crear/editar/borrar para un modelo de datos maestros
    — mismo patrón para los 6 modelos simples (ver `crud.py`). `class_prefix`
    es el prefijo exacto de las clases en `crud.py` (p.ej. "TipoArmamento"),
    que no siempre coincide con `name.title()` para nombres compuestos."""
    return [
        path(f"{prefix}/", getattr(crud, f"{class_prefix}ListView").as_view(), name=f"{name}_list"),
        path(
            f"{prefix}/nuevo/",
            getattr(crud, f"{class_prefix}CreateView").as_view(),
            name=f"{name}_crear",
        ),
        path(
            f"{prefix}/<int:pk>/editar/",
            getattr(crud, f"{class_prefix}UpdateView").as_view(),
            name=f"{name}_editar",
        ),
        path(
            f"{prefix}/<int:pk>/borrar/",
            getattr(crud, f"{class_prefix}DeleteView").as_view(),
            name=f"{name}_borrar",
        ),
    ]


urlpatterns = [
    path("", views.armamento_list, name="armamento_list"),
    path("armamento/nuevo/", views.armamento_crear, name="armamento_crear"),
    path("armamento/<int:pk>/editar/", views.armamento_editar, name="armamento_editar"),
    path("armamento/<int:pk>/entregar/", views.armamento_entregar, name="armamento_entregar"),
    path("armamento/<int:pk>/devolver/", views.armamento_devolver, name="armamento_devolver"),
    path("armamento/<int:pk>/baja/", views.armamento_baja, name="armamento_baja"),
    path("movimientos/", views.movimiento_list, name="movimiento_list"),
    path("soldados/", views.soldado_list, name="soldado_list"),
    path("soldados/nuevo/", views.soldado_crear, name="soldado_crear"),
    path("soldados/<int:pk>/editar/", views.soldado_editar, name="soldado_editar"),
    path("municion/", views.existencia_list, name="existencia_list"),
    path("municion/nuevo/", views.existencia_crear, name="existencia_crear"),
    path("municion/<int:pk>/editar/", views.existencia_editar, name="existencia_editar"),
    path("prestamos/", views.prestamo_list, name="prestamo_list"),
    path("prestamos/nuevo/", views.prestamo_transferir, name="prestamo_transferir"),
    path("compania/", views.elegir_compania, name="elegir_compania"),
    path("ajustes/", views.ajustes, name="ajustes"),
    *_crud_urls("unidades", "unidad", "Unidad"),
    *_crud_urls("companias", "compania", "Compania"),
    *_crud_urls("depositos", "deposito", "Deposito"),
    *_crud_urls("pelotones", "peloton", "Peloton"),
    *_crud_urls("tipos-de-armamento", "tipoarmamento", "TipoArmamento"),
    *_crud_urls("campos-personalizados", "campopersonalizado", "CampoPersonalizado"),
]
