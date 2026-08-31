"""Superficie principal de SIGA: selección de compañía de trabajo (RF-02) y
todas las pantallas de inventario/entrega/devolución/movimientos/soldados/
munición/préstamos/datos maestros (T-06, H-17) — el admin de Django ya no
existe (ADR-0004); esto es la única UI de la aplicación.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError, Q
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


def _codigo_compania(nombre):
    """Código corto para la tarjeta de selección (issue #6). `Compania` no
    tiene un campo `codigo` propio (PRD P-5, aún sin confirmar por David) —
    se deriva de `nombre` reproduciendo el mapeo que ya describe el PRD
    (RF-03): una letra para los nombres largos, el nombre tal cual para los
    que ya son cortos/siglas (ASPC, IR)."""
    return nombre if len(nombre) <= 4 else nombre[0].upper()


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

    actual_id = request.session.get(SESSION_KEY)
    opciones = [
        {
            "compania": compania,
            "codigo": _codigo_compania(compania.nombre),
            "total": Armamento.objects.filter(compania=compania).count(),
            "reciente": compania.pk == actual_id,
        }
        for compania in companias
    ]

    context = {
        "title": "Elegir compañía de trabajo",
        "companias": companias,
        "opciones": opciones,
        "actual_id": actual_id,
        "next": next_url,
    }
    return render(request, "inventory/elegir_compania.html", context)


@requiere_autorizado
def ajustes(request):
    """Reemplazo del índice del admin de Django: enlaces a los módulos de
    datos maestros y (solo ADMIN) usuarios."""
    return render(request, "inventory/ajustes.html")


def _borrar_protegido(request, obj, redirect_url_name):
    """Borra `obj`, mostrando un error claro (en vez de un 500) si otro
    registro depende de él vía on_delete=PROTECT — mismo criterio que
    `MasterDeleteView.form_valid` en `crud.py`, para las vistas de Soldado/
    Existencia que no usan el CRUD genérico (llevan su propio listado con
    búsqueda y contexto de compañía)."""
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request, f'No se puede borrar "{obj}" porque otros registros dependen de él.'
        )
    else:
        messages.success(request, f'"{obj}" borrado.')
    return redirect(redirect_url_name)


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

    # KPIs del layout de escritorio (issue #3): sobre el alcance de compañía
    # actual, sin aplicar q/peloton/ubicacion/tipo — mismo criterio que el
    # subtítulo "Compañía X" ya usa, no el resultado ya filtrado por texto.
    kpi_qs = Armamento.objects.all()
    if compania_id and not ver_todas:
        kpi_qs = kpi_qs.filter(compania_id=compania_id)
    kpi_total = kpi_qs.count()
    kpi_en_deposito = kpi_qs.filter(
        estado=Armamento.Estado.ACTIVO, ubicacion=Armamento.Ubicacion.DEPOSITO
    ).count()
    kpi_en_mano = kpi_qs.filter(
        estado=Armamento.Estado.ACTIVO, ubicacion=Armamento.Ubicacion.EN_MANO
    ).count()
    kpi_de_baja = kpi_qs.filter(estado=Armamento.Estado.BAJA).count()

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
        "kpi_total": kpi_total,
        "kpi_en_deposito": kpi_en_deposito,
        "kpi_en_mano": kpi_en_mano,
        "kpi_de_baja": kpi_de_baja,
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


def _historial_arma(armamento):
    """Historial de movimientos del arma, más reciente primero (issue #5).

    `Movimiento` solo guarda el destino de cada paso (soldado en ENTREGA,
    depósito en DEVOLUCION) — el "desde X" se deriva encadenando el destino
    del movimiento anterior, ya que entre dos movimientos el arma no pudo
    haber estado en otro lado. El primer movimiento no tiene un "desde"
    confiable (no se registra un evento al crear/cargar el arma), así que
    se muestra sin esa cláusula; en su lugar se agrega al final una fila
    sintética de "Alta en inventario" con `Armamento.creado`, sin usuario
    inventado (la carga inicial es un script sin usuario asociado, RF-13)."""
    movimientos = armamento.movimientos.select_related("soldado", "deposito", "usuario").order_by(
        "fecha"
    )
    historial = []
    origen = None
    for mov in movimientos:
        if mov.tipo == Movimiento.Tipo.ENTREGA:
            titulo = "Entrega a soldado"
            destino_nombre = mov.soldado.apellidos_nombres if mov.soldado else "—"
            detalle = f"A {destino_nombre}"
        elif mov.tipo == Movimiento.Tipo.DEVOLUCION:
            titulo = "Devolución a depósito"
            destino_nombre = mov.deposito.nombre if mov.deposito else "—"
            detalle = f"A {destino_nombre}"
        else:
            titulo = "Baja"
            destino_nombre = None
            detalle = mov.observacion or "Dada de baja"
        if origen:
            detalle = f"{detalle} · desde {origen}"
        historial.append(
            {"titulo": titulo, "detalle": detalle, "fecha": mov.fecha, "usuario": mov.usuario}
        )
        origen = destino_nombre
    historial.reverse()
    historial.append(
        {
            "titulo": "Alta en inventario",
            "detalle": "Carga inicial",
            "fecha": armamento.creado,
            "usuario": None,
        }
    )
    return historial


@requiere_autorizado
def armamento_detalle(request, pk):
    arma = get_object_or_404(
        Armamento.objects.select_related(
            "tipo", "compania", "deposito", "soldado", "soldado__peloton"
        ),
        pk=pk,
    )
    context = {
        "arma": arma,
        "historial": _historial_arma(arma),
        "campos_personalizados": (arma.datos_extra or {}).items(),
    }
    return render(request, "inventory/armamento_detalle.html", context)


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
    context = {"form": form, "titulo": "Añadir soldado", "cancelar_url": "inventory:soldado_list"}
    return render(request, "inventory/master_form.html", context)


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
    context = {
        "form": form, "titulo": f"Editar {soldado}", "cancelar_url": "inventory:soldado_list",
    }
    return render(request, "inventory/master_form.html", context)


@requiere_admin
def soldado_borrar(request, pk):
    soldado = get_object_or_404(Soldado, pk=pk)
    if request.method == "POST":
        return _borrar_protegido(request, soldado, "inventory:soldado_list")
    context = {"object": soldado, "cancelar_url": "inventory:soldado_list"}
    return render(request, "inventory/master_confirm_delete.html", context)


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
    context = {
        "form": form, "titulo": "Añadir existencia", "cancelar_url": "inventory:existencia_list",
    }
    return render(request, "inventory/master_form.html", context)


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
    context = {
        "form": form, "titulo": f"Editar {existencia}",
        "cancelar_url": "inventory:existencia_list",
    }
    return render(request, "inventory/master_form.html", context)


@requiere_admin
def existencia_borrar(request, pk):
    existencia = get_object_or_404(Existencia, pk=pk)
    if request.method == "POST":
        return _borrar_protegido(request, existencia, "inventory:existencia_list")
    context = {"object": existencia, "cancelar_url": "inventory:existencia_list"}
    return render(request, "inventory/master_confirm_delete.html", context)


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
