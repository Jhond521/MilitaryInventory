from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, JsonResponse
from django.urls import include, path

admin.site.site_header = "SIGA — Inventario de Armamento"
admin.site.site_title = "SIGA"
admin.site.index_title = "Administración"


def health(_request):
    """Liveness endpoint used by the smoke test and the deploy platform."""
    return JsonResponse({"status": "ok"})


def pwa_manifest(_request):
    """Web app manifest (RF-17), served from a stable root URL — not under
    /static/, so whitenoise's hashed filenames don't break it."""
    path_ = settings.BASE_DIR / "static" / "manifest.json"
    return FileResponse(path_.open("rb"), content_type="application/manifest+json")


def pwa_service_worker(_request):
    """Service worker (RF-17). Must be served at the origin root so its
    default scope covers the whole app, not just /static/."""
    path_ = settings.BASE_DIR / "static" / "sw.js"
    response = FileResponse(path_.open("rb"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


urlpatterns = [
    path("health/", health, name="health"),
    path("manifest.json", pwa_manifest, name="pwa-manifest"),
    path("sw.js", pwa_service_worker, name="pwa-service-worker"),
    path("", include("apps.inventory.urls")),
    path("admin/", admin.site.urls),
]
