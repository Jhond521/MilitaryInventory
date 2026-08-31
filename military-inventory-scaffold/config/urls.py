from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

admin.site.site_header = "SIGA — Inventario de Armamento"
admin.site.site_title = "SIGA"
admin.site.index_title = "Administración"


def health(_request):
    """Liveness endpoint used by the smoke test and the deploy platform."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("", admin.site.urls),
]
