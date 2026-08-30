"""Superficie móvil de SIGA: selección de compañía de trabajo (RF-02) y las
pantallas propias de inventario/entrega/devolución/movimientos/soldados/
munición (T-06, H-17) que reemplazan, para el uso diario, a las acciones del
admin de Django (que sigue disponible en /admin/ para datos maestros).
"""
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import (
    Armamento,
    Compania,
    Deposito,
    Existencia,
    Movimiento,
    Peloton,
    Soldado,
    TipoArmamento,
)

SESSION_KEY = "compania_actual_id"


@staff_member_required
def elegir_compania(request):
    companias = Compania.objects.order_by("nombre")

    next_url = (
        request.POST.get("next") or request.GET.get("next") or reverse("inventory:armamento_list")
    )
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse("inventory:armamento_list")

    if request.method == "POST":
        compania_id = request.POST.get("compania")
        if compania_id and companias.filter(pk=compania_id).exists():
            request.session[SESSION_KEY] = int(compania_id)
            return redirect(next_url)

    context = {
        **admin.site.each_context(request),
        "title": "Elegir compañía de trabajo",
        "companias": companias,
        "actual_id": request.session.get(SESSION_KEY),
        "next": next_url,
    }
    return render(request, "inventory/elegir_compania.html", context)


def _companias_scope(request):
    """(compania_id, ver_todas) — igual criterio que `CompaniaContextoMixin`
    del admin (RF-02, S-2): filtra por la compañía de trabajo salvo que se
    pida explícitamente ver todas."""
    return request.session.get(SESSION_KEY), request.GET.get("todas") == "1"


@staff_member_required
def armamento_list(request):
    compania_id, ver_todas = _companias_scope(request)
    qs = (
        Armamento.objects.filter(estado=Armamento.Estado.ACTIVO)
        .select_related("tipo", "compania", "deposito", "soldado", "soldado__peloton")
        .order_by("numero_serie")
    )
    if compania_id and not ver_todas:
        qs = qs.filter(compania_id=compania_id)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(numero_serie__icontains=q)
            | Q(soldado__apellidos_nombres__icontains=q)
            | Q(tipo__nombre__icontains=q)
            | Q(deposito__nombre__icontains=q)
            | Q(datos_extra__icontains=q)
        )

    peloton_id = request.GET.get("peloton", "")
    if peloton_id:
        qs = qs.filter(soldado__peloton_id=peloton_id)

    ubicacion = request.GET.get("ubicacion", "")
    if ubicacion in Armamento.Ubicacion.values:
        qs = qs.filter(ubicacion=ubicacion)

    tipo_id = request.GET.get("tipo", "")
    if tipo_id:
        qs = qs.filter(tipo_id=tipo_id)

    if compania_id and not ver_todas:
        pelotones = Peloton.objects.filter(compania_id=compania_id)
    else:
        pelotones = Peloton.objects.all()
    tipos = TipoArmamento.objects.filter(control=TipoArmamento.Control.SERIE).order_by("nombre")

    context = {
        "armamentos": qs,
        "q": q,
        "pelotones": pelotones,
        "tipos": tipos,
        "peloton_id": peloton_id,
        "ubicacion": ubicacion,
        "ubicacion_choices": Armamento.Ubicacion.choices,
        "tipo_id": tipo_id,
        "ver_todas": ver_todas,
    }
    return render(request, "inventory/armamento_list.html", context)


@staff_member_required
def armamento_entregar(request, pk):
    """Flujo guiado de 3 pasos (Arma → Soldado → Confirmar) sobre
    `Armamento.entregar()` (RF-10) — misma lógica que
    `ArmamentoAdmin.entregar_view`, para una sola arma a la vez."""
    arma = get_object_or_404(
        Armamento.objects.select_related("tipo", "compania", "deposito"),
        pk=pk,
        ubicacion=Armamento.Ubicacion.DEPOSITO,
        estado=Armamento.Estado.ACTIVO,
    )

    if request.method == "POST":
        soldado = get_object_or_404(
            Soldado, pk=request.POST.get("soldado"), compania_id=arma.compania_id
        )
        observacion = request.POST.get("observacion", "")
        try:
            arma.entregar(soldado=soldado, usuario=request.user, observacion=observacion)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("inventory:armamento_entregar", pk=arma.pk)
        messages.success(request, f"{arma.numero_serie} entregada a {soldado}.")
        return redirect("inventory:armamento_list")

    soldado_id = request.GET.get("soldado")
    if soldado_id:
        soldado = get_object_or_404(Soldado, pk=soldado_id, compania_id=arma.compania_id)
        context = {"arma": arma, "soldado": soldado, "paso": "confirmar"}
        return render(request, "inventory/armamento_entregar.html", context)

    q = request.GET.get("q", "").strip()
    soldados = Soldado.objects.filter(compania_id=arma.compania_id).select_related("peloton")
    if q:
        soldados = soldados.filter(apellidos_nombres__icontains=q)

    context = {"arma": arma, "q": q, "soldados": soldados[:30], "paso": "soldado"}
    return render(request, "inventory/armamento_entregar.html", context)


@staff_member_required
def armamento_devolver(request, pk):
    """Un solo paso (visualmente simétrico a `armamento_entregar`) sobre
    `Armamento.devolver()` (RF-10) — el depósito no depende de la compañía."""
    arma = get_object_or_404(
        Armamento.objects.select_related("tipo", "compania", "soldado", "soldado__peloton"),
        pk=pk,
        ubicacion=Armamento.Ubicacion.EN_MANO,
    )

    if request.method == "POST":
        deposito = get_object_or_404(Deposito, pk=request.POST.get("deposito"))
        observacion = request.POST.get("observacion", "")
        try:
            arma.devolver(deposito=deposito, usuario=request.user, observacion=observacion)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("inventory:armamento_devolver", pk=arma.pk)
        messages.success(request, f"{arma.numero_serie} devuelta a {deposito}.")
        return redirect("inventory:armamento_list")

    context = {"arma": arma, "depositos": Deposito.objects.order_by("nombre")}
    return render(request, "inventory/armamento_devolver.html", context)


@staff_member_required
def movimiento_list(request):
    compania_id, ver_todas = _companias_scope(request)
    qs = Movimiento.objects.select_related("armamento", "soldado", "deposito", "usuario")
    if compania_id and not ver_todas:
        qs = qs.filter(armamento__compania_id=compania_id)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(armamento__numero_serie__icontains=q) | Q(soldado__apellidos_nombres__icontains=q)
        )

    tipo = request.GET.get("tipo", "")
    if tipo in Movimiento.Tipo.values:
        qs = qs.filter(tipo=tipo)

    context = {
        "movimientos": qs[:200],
        "q": q,
        "tipo": tipo,
        "tipo_choices": Movimiento.Tipo.choices,
        "ver_todas": ver_todas,
    }
    return render(request, "inventory/movimiento_list.html", context)


@staff_member_required
def soldado_list(request):
    compania_id, ver_todas = _companias_scope(request)
    qs = Soldado.objects.select_related("compania", "peloton")
    if compania_id and not ver_todas:
        qs = qs.filter(compania_id=compania_id)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(apellidos_nombres__icontains=q)

    peloton_id = request.GET.get("peloton", "")
    if peloton_id:
        qs = qs.filter(peloton_id=peloton_id)

    if compania_id and not ver_todas:
        pelotones = Peloton.objects.filter(compania_id=compania_id)
    else:
        pelotones = Peloton.objects.all()

    context = {
        "soldados": qs,
        "q": q,
        "pelotones": pelotones,
        "peloton_id": peloton_id,
        "ver_todas": ver_todas,
    }
    return render(request, "inventory/soldado_list.html", context)


@staff_member_required
def existencia_list(request):
    compania_id, ver_todas = _companias_scope(request)
    qs = Existencia.objects.select_related("tipo", "compania", "deposito")
    if compania_id and not ver_todas:
        qs = qs.filter(compania_id=compania_id)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(tipo__nombre__icontains=q) | Q(lote__icontains=q))

    deposito_id = request.GET.get("deposito", "")
    if deposito_id:
        qs = qs.filter(deposito_id=deposito_id)

    context = {
        "existencias": qs,
        "q": q,
        "depositos": Deposito.objects.order_by("nombre"),
        "deposito_id": deposito_id,
        "ver_todas": ver_todas,
    }
    return render(request, "inventory/existencia_list.html", context)
