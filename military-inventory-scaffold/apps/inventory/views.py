"""Superficie principal de SIGA: selección de compañía de trabajo (RF-02) y
todas las pantallas de inventario/entrega/devolución/movimientos/soldados/
munición/préstamos/datos maestros (T-06, H-17) — el admin de Django ya no
existe (ADR-0004); esto es la única UI de la aplicación.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.permissions import requiere_admin, requiere_autorizado

from .forms import (
    ArmamentoCrearForm,
    ArmamentoEditarForm,
    BajaForm,
    ExistenciaForm,
    PrestamoForm,
    SoldadoForm,
    aplicar_campos_personalizados,
)
from .models import (
    Armamento,
    Compania,
    Deposito,
    Existencia,
    Movimiento,
    Peloton,
    Prestamo,
    Soldado,
    TipoArmamento,
)

SESSION_KEY = "compania_actual_id"


@requiere_autorizado
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
        "title": "Elegir compañía de trabajo",
        "companias": companias,
        "actual_id": request.session.get(SESSION_KEY),
        "next": next_url,
    }
    return render(request, "inventory/elegir_compania.html", context)


@requiere_autorizado
def ajustes(request):
    """Reemplazo del índice del admin de Django: enlaces a los módulos de
    datos maestros y (solo ADMIN) usuarios."""
    return render(request, "inventory/ajustes.html")


def _companias_scope(request):
    """(compania_id, ver_todas) — igual criterio que el antiguo
    `CompaniaContextoMixin` del admin (RF-02, S-2): filtra por la compañía de
    trabajo salvo que se pida explícitamente ver todas."""
    return request.session.get(SESSION_KEY), request.GET.get("todas") == "1"


@requiere_autorizado
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
            | Q(compania__nombre__icontains=q)
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


@requiere_admin
def armamento_crear(request):
    if request.method == "POST":
        form = ArmamentoCrearForm(request.POST)
        if form.is_valid():
            armamento = form.save()
            messages.success(request, f"{armamento.numero_serie} añadida al inventario.")
            return redirect("inventory:armamento_list")
    else:
        form = ArmamentoCrearForm()
    return render(
        request, "inventory/armamento_form.html", {"form": form, "titulo": "Añadir armamento"}
    )


@requiere_admin
def armamento_editar(request, pk):
    armamento = get_object_or_404(Armamento, pk=pk)
    if request.method == "POST":
        form = ArmamentoEditarForm(request.POST, instance=armamento)
        if form.is_valid():
            aplicar_campos_personalizados(armamento, form.cleaned_data)
            form.save()
            messages.success(request, f"{armamento.numero_serie} actualizada.")
            return redirect("inventory:armamento_list")
    else:
        form = ArmamentoEditarForm(instance=armamento)
    context = {"form": form, "titulo": f"Editar {armamento.numero_serie}", "arma": armamento}
    return render(request, "inventory/armamento_form.html", context)


@requiere_admin
def armamento_baja(request, pk):
    """RF-11 — solo administrador, a diferencia de entregar/devolver."""
    armamento = get_object_or_404(Armamento, pk=pk, estado=Armamento.Estado.ACTIVO)
    if request.method == "POST":
        form = BajaForm(request.POST)
        if form.is_valid():
            try:
                armamento.dar_de_baja(
                    motivo=form.cleaned_data["motivo"],
                    fecha=form.cleaned_data["fecha"],
                    usuario=request.user,
                    observacion=form.cleaned_data["observacion"],
                )
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
                return redirect("inventory:armamento_baja", pk=armamento.pk)
            messages.success(request, f"{armamento.numero_serie} dada de baja.")
            return redirect("inventory:armamento_list")
    else:
        form = BajaForm(initial={"fecha": timezone.localdate()})
    return render(request, "inventory/armamento_baja.html", {"form": form, "arma": armamento})


@requiere_autorizado
def armamento_entregar(request, pk):
    """Flujo guiado de 3 pasos (Arma → Soldado → Confirmar) sobre
    `Armamento.entregar()` (RF-10)."""
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


@requiere_autorizado
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


@requiere_autorizado
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


@requiere_autorizado
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


@requiere_admin
def soldado_crear(request):
    if request.method == "POST":
        form = SoldadoForm(request.POST)
        if form.is_valid():
            soldado = form.save()
            messages.success(request, f"{soldado} añadido.")
            return redirect("inventory:soldado_list")
    else:
        form = SoldadoForm()
    return render(
        request, "inventory/master_form.html", {"form": form, "titulo": "Añadir soldado"}
    )


@requiere_admin
def soldado_editar(request, pk):
    soldado = get_object_or_404(Soldado, pk=pk)
    if request.method == "POST":
        form = SoldadoForm(request.POST, instance=soldado)
        if form.is_valid():
            form.save()
            messages.success(request, f"{soldado} actualizado.")
            return redirect("inventory:soldado_list")
    else:
        form = SoldadoForm(instance=soldado)
    return render(
        request,
        "inventory/master_form.html",
        {"form": form, "titulo": f"Editar {soldado}"},
    )


@requiere_autorizado
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


@requiere_admin
def existencia_crear(request):
    if request.method == "POST":
        form = ExistenciaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Existencia añadida.")
            return redirect("inventory:existencia_list")
    else:
        form = ExistenciaForm()
    return render(
        request, "inventory/master_form.html", {"form": form, "titulo": "Añadir existencia"}
    )


@requiere_admin
def existencia_editar(request, pk):
    existencia = get_object_or_404(Existencia, pk=pk)
    if request.method == "POST":
        form = ExistenciaForm(request.POST, instance=existencia)
        if form.is_valid():
            form.save()
            messages.success(request, "Existencia actualizada.")
            return redirect("inventory:existencia_list")
    else:
        form = ExistenciaForm(instance=existencia)
    return render(
        request,
        "inventory/master_form.html",
        {"form": form, "titulo": f"Editar {existencia}"},
    )


@requiere_autorizado
def prestamo_list(request):
    compania_id, ver_todas = _companias_scope(request)
    qs = Prestamo.objects.select_related(
        "tipo", "deposito", "compania_origen", "compania_destino", "usuario"
    )
    if compania_id and not ver_todas:
        qs = qs.filter(Q(compania_origen_id=compania_id) | Q(compania_destino_id=compania_id))
    context = {"prestamos": qs[:200], "ver_todas": ver_todas}
    return render(request, "inventory/prestamo_list.html", context)


@requiere_autorizado
def prestamo_transferir(request):
    """RF-15/H-16 — ambos roles pueden registrar (es "registrar un
    movimiento", no tocar datos maestros), igual que entregar/devolver."""
    compania_id, _ = _companias_scope(request)
    if request.method == "POST":
        form = PrestamoForm(request.POST)
        if form.is_valid():
            prestamo = Prestamo(
                tipo=form.cleaned_data["tipo"],
                deposito=form.cleaned_data["deposito"],
                compania_origen=form.cleaned_data["compania_origen"],
                compania_destino=form.cleaned_data["compania_destino"],
                lote=form.cleaned_data["lote"],
                cantidad=form.cleaned_data["cantidad"],
                observacion=form.cleaned_data["observacion"],
                usuario=request.user,
            )
            try:
                prestamo.full_clean()
                prestamo.save()
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, "Préstamo registrado.")
                return redirect("inventory:existencia_list")
    else:
        initial = {"compania_origen": compania_id} if compania_id else {}
        form = PrestamoForm(initial=initial)
    return render(request, "inventory/prestamo_form.html", {"form": form})
