"""Backup export and restore screens (issues #33/#34, RF-26/RF-27). ADMIN only.

The workbook format and the restore logic live in `respaldo.py`. This module only
handles HTTP:

1. Upload and validate. The file is checked in memory, then dry-run inside a
   transaction that is always rolled back.
2. Preview. Shows the current and incoming counts and asks for the typed word
   `REESTABLECER`.
3. Restore. Validates again and applies it all or nothing.

Between steps 2 and 3 the uploaded file waits in a temp directory, under a random
token kept in the session (the file itself never goes in the session).
"""
import secrets
import tempfile
import time
from io import BytesIO
from pathlib import Path

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.permissions import requiere_admin

from . import respaldo
from .models import Compania, Deposito
from .views import SESSION_KEY, SESSION_KEY_DEPOSITO

TAMANO_MAXIMO = 20 * 1024 * 1024  # 20 MB; a full real backup is well under 1 MB
SESSION_TOKEN = "respaldo_token"
CADUCIDAD_SEGUNDOS = 60 * 60
_DIRECTORIO = Path(tempfile.gettempdir()) / "siga-respaldos"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@requiere_admin
def respaldo_exportar(request):
    buffer = BytesIO()
    respaldo.exportar(buffer, request.user)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{respaldo.nombre_archivo()}"'
    return response


def _ruta(token: str) -> Path:
    return _DIRECTORIO / f"{token}.xlsx"


def _limpiar_viejos():
    if not _DIRECTORIO.exists():
        return
    limite = time.time() - CADUCIDAD_SEGUNDOS
    for archivo in _DIRECTORIO.glob("*.xlsx"):
        try:
            if archivo.stat().st_mtime < limite:
                archivo.unlink()
        except OSError:
            pass


def _descartar(request):
    token = request.session.pop(SESSION_TOKEN, None)
    if token:
        _ruta(token).unlink(missing_ok=True)


def _vista_previa(request, datos, error=None):
    filas = []
    for hoja, model in respaldo.MODELOS_RESPALDO:
        filas.append(
            {"hoja": hoja, "actual": model.objects.count(), "archivo": datos.conteo(hoja)}
        )
    return render(
        request,
        "inventory/respaldo_confirmar.html",
        {
            "filas": filas,
            "total": sum(f["archivo"] for f in filas),
            "generado": datos.generado,
            "generado_por": datos.meta.get("generado_por"),
            "palabra": respaldo.PALABRA_CONFIRMACION,
            "error": error,
        },
    )


def _formulario(request, errores=None, status=200):
    return render(
        request,
        "inventory/respaldo_reestablecer.html",
        {"errores": errores or []},
        status=status,
    )


@requiere_admin
def respaldo_reestablecer(request):
    """Step 1 (GET form, POST upload) → step 2 (preview)."""
    if request.method != "POST":
        return _formulario(request)

    archivo = request.FILES.get("archivo")
    if archivo is None:
        return _formulario(request, ["Selecciona el archivo de respaldo (.xlsx)."], 400)
    if archivo.size > TAMANO_MAXIMO:
        return _formulario(request, ["El archivo supera el tamaño máximo de 20 MB."], 400)
    contenido = archivo.read()
    try:
        datos = respaldo.leer(BytesIO(contenido))
        respaldo.probar(datos)
    except respaldo.ErrorRespaldo as exc:
        return _formulario(request, exc.errores, 400)

    _limpiar_viejos()
    _descartar(request)
    _DIRECTORIO.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    _ruta(token).write_bytes(contenido)
    request.session[SESSION_TOKEN] = token
    return _vista_previa(request, datos)


@requiere_admin
def respaldo_confirmar(request):
    """Step 3: typed confirmation, then the real restore."""
    if request.method != "POST":
        return redirect("inventory:respaldo_reestablecer")
    if request.POST.get("cancelar"):
        _descartar(request)
        messages.info(request, "Restauración cancelada. No se cambió nada.")
        return redirect("inventory:ajustes")

    token = request.session.get(SESSION_TOKEN)
    ruta = _ruta(token) if token else None
    if ruta is None or not ruta.exists():
        request.session.pop(SESSION_TOKEN, None)
        return _formulario(
            request, ["La sesión de restauración expiró. Vuelve a subir el archivo."], 400
        )
    try:
        datos = respaldo.leer(BytesIO(ruta.read_bytes()))
    except respaldo.ErrorRespaldo as exc:
        _descartar(request)
        return _formulario(request, exc.errores, 400)

    if request.POST.get("confirmacion", "").strip() != respaldo.PALABRA_CONFIRMACION:
        return _vista_previa(
            request,
            datos,
            error=f"Escribe exactamente {respaldo.PALABRA_CONFIRMACION} para confirmar.",
        )

    try:
        conteos = respaldo.restaurar(datos, request.user)
    except respaldo.ErrorRespaldo as exc:
        _descartar(request)
        return _formulario(request, exc.errores, 400)
    _descartar(request)

    # The working compañía/depósito may not exist in the restored data; drop it so
    # the middleware sends the user to the selector instead of a stale filter.
    sesion = request.session
    if sesion.get(SESSION_KEY) and not Compania.objects.filter(pk=sesion[SESSION_KEY]).exists():
        sesion.pop(SESSION_KEY)
    if (
        sesion.get(SESSION_KEY_DEPOSITO)
        and not Deposito.objects.filter(pk=sesion[SESSION_KEY_DEPOSITO]).exists()
    ):
        sesion.pop(SESSION_KEY_DEPOSITO)

    generado = datos.generado
    cuando = generado.strftime("%Y-%m-%d %H:%M") if generado else "?"
    messages.success(
        request,
        f"Respaldo del {cuando} reestablecido: {sum(conteos.values())} registros.",
    )
    return redirect(reverse("inventory:ajustes"))
