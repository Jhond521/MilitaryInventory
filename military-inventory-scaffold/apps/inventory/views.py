"""Superficie principal de SIGA: selección de compañía de trabajo (RF-02) y
todas las pantallas de inventario/entrega/devolución/movimientos/soldados/
munición/préstamos/datos maestros (T-06, H-17) — el admin de Django ya no
existe (ADR-0004); esto es la única UI de la aplicación.
"""
from operator import attrgetter
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F, ProtectedError, Q, Sum
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
    DevolucionPrestamo,
    Existencia,
    ExistenciaAsignada,
    Movimiento,
    MovimientoExistencia,
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


def _next_seguro(request):
    """`next` (GET o POST) solo si apunta a este mismo sitio; si no, "".
    Lo usan las pantallas de devolver para volver a la ficha del soldado
    cuando se llegó desde ella (issue #17)."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return ""


def _con_next(url, next_url):
    return f"{url}?{urlencode({'next': next_url})}" if next_url else url


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
    inventado (la carga inicial es un script sin usuario asociado, RF-13).

    `detalle` (destino/origen) y `observacion` (texto libre capturado en el
    formulario) son campos separados — antes se mezclaban para BAJA y se
    perdían por completo para ENTREGA/DEVOLUCION (issue #14)."""
    movimientos = armamento.movimientos.select_related("soldado", "deposito", "usuario").order_by(
        "fecha"
    )
    historial = []
    origen = None
    for mov in movimientos:
        if mov.tipo == Movimiento.Tipo.ENTREGA:
            titulo = "Entrega a soldado"
            destino_nombre = mov.soldado.nombre_con_grado if mov.soldado else "—"
            detalle = f"A {destino_nombre}"
        elif mov.tipo == Movimiento.Tipo.DEVOLUCION:
            titulo = "Devolución a depósito"
            destino_nombre = mov.deposito.nombre if mov.deposito else "—"
            detalle = f"A {destino_nombre}"
        else:
            titulo = "Baja"
            destino_nombre = None
            detalle = "Dada de baja"
        if origen:
            detalle = f"{detalle} · desde {origen}"
        historial.append(
            {
                "titulo": titulo,
                "detalle": detalle,
                "observacion": mov.observacion,
                "fecha": mov.fecha,
                "usuario": mov.usuario,
            }
        )
        origen = destino_nombre
    historial.reverse()
    historial.append(
        {
            "titulo": "Alta en inventario",
            "detalle": "Carga inicial",
            "observacion": "",
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
    soldados = _buscar_soldados(soldados, q)

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

    next_url = _next_seguro(request)
    if request.method == "POST":
        deposito = get_object_or_404(Deposito, pk=request.POST.get("deposito"))
        observacion = request.POST.get("observacion", "")
        try:
            arma.devolver(deposito=deposito, usuario=request.user, observacion=observacion)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(
                _con_next(reverse("inventory:armamento_devolver", args=[arma.pk]), next_url)
            )
        messages.success(request, f"{arma.numero_serie} devuelta a {deposito}.")
        return redirect(next_url or "inventory:armamento_list")

    context = {
        "arma": arma,
        "depositos": Deposito.objects.order_by("nombre"),
        "next": next_url,
    }
    return render(request, "inventory/armamento_devolver.html", context)


MOVIMIENTOS_LIMITE = 200
CLASE_ARMAMENTO = "ARMAMENTO"
CLASE_MUNICION = "MUNICION"
CLASE_PRESTAMO = "PRESTAMO"
# Solo marca de fila para la plantilla: en el filtro va dentro de "Préstamos".
CLASE_DEVOLUCION_PRESTAMO = "DEVOLUCION_PRESTAMO"
CLASE_CHOICES = [
    (CLASE_ARMAMENTO, "Armamento"),
    (CLASE_MUNICION, "Munición"),
    (CLASE_PRESTAMO, "Préstamos"),
]


def _mezclar_por_fecha(grupos, limite):
    """Mezcla registros de varios modelos de historial en una sola lista,
    más reciente primero (issue #16). `grupos` es una lista de
    `(clase, queryset)`; cada registro queda marcado con `.clase` para que
    la plantilla sepa qué tarjeta dibujar. Cada queryset se recorta a
    `limite` antes de mezclar, así ninguno se trae entero a memoria. Un
    grupo también puede ser una lista ya armada (ficha del soldado, #17)."""
    registros = []
    for clase, qs in grupos:
        if hasattr(qs, "order_by"):
            qs = qs.order_by("-fecha")[:limite]
        for registro in qs:
            registro.clase = clase
            registros.append(registro)
    registros.sort(key=attrgetter("fecha"), reverse=True)
    return registros[:limite]


@requiere_autorizado
def movimiento_list(request):
    """Historial unificado (RNF-03, issue #16): entregas/devoluciones/bajas
    de armamento (`Movimiento`), entregas/devoluciones de existencias
    (`MovimientoExistencia`, RF-18) y préstamos entre compañías
    (`Prestamo`, RF-15). Son tres modelos separados (ADR-0005); se mezclan
    aquí, en la vista, sin un modelo común. Las devoluciones de préstamo
    (`DevolucionPrestamo`, RF-22) van con la clase "Préstamos"."""
    compania_id, ver_todas = _companias_scope(request)
    q = request.GET.get("q", "").strip()
    tipo = request.GET.get("tipo", "")
    if tipo not in Movimiento.Tipo.values:
        tipo = ""
    clase = request.GET.get("clase", "")
    if clase not in dict(CLASE_CHOICES):
        clase = ""
    filtra_compania = bool(compania_id and not ver_todas)

    grupos = []
    if clase in ("", CLASE_ARMAMENTO):
        qs = Movimiento.objects.select_related(
            "armamento__tipo", "soldado", "deposito", "usuario"
        )
        if filtra_compania:
            qs = qs.filter(armamento__compania_id=compania_id)
        if q:
            qs = qs.filter(
                Q(armamento__numero_serie__icontains=q)
                | Q(soldado__apellidos_nombres__icontains=q)
            )
        if tipo:
            qs = qs.filter(tipo=tipo)
        grupos.append((CLASE_ARMAMENTO, qs))

    # Las existencias no tienen baja: con Tipo = Baja no aportan nada.
    if clase in ("", CLASE_MUNICION) and tipo != Movimiento.Tipo.BAJA:
        qs = MovimientoExistencia.objects.select_related(
            "existencia__tipo", "existencia__compania", "soldado", "usuario"
        )
        if filtra_compania:
            qs = qs.filter(existencia__compania_id=compania_id)
        if q:
            qs = qs.filter(
                Q(existencia__tipo__nombre__icontains=q)
                | Q(existencia__lote__icontains=q)
                | Q(soldado__apellidos_nombres__icontains=q)
            )
        if tipo:
            qs = qs.filter(tipo=tipo)
        grupos.append((CLASE_MUNICION, qs))

    # Un préstamo no es entrega/devolución/baja: solo aparece sin filtro de tipo.
    if clase in ("", CLASE_PRESTAMO) and not tipo:
        qs = Prestamo.objects.select_related(
            "tipo", "deposito", "compania_origen", "compania_destino", "usuario"
        )
        if filtra_compania:
            qs = qs.filter(
                Q(compania_origen_id=compania_id) | Q(compania_destino_id=compania_id)
            )
        if q:
            qs = qs.filter(
                Q(tipo__nombre__icontains=q)
                | Q(lote__icontains=q)
                | Q(compania_origen__nombre__icontains=q)
                | Q(compania_destino__nombre__icontains=q)
            )
        grupos.append((CLASE_PRESTAMO, qs))

        # Devoluciones de préstamo (RF-22) — mismos filtros que su préstamo.
        devoluciones = DevolucionPrestamo.objects.select_related(
            "prestamo__tipo", "prestamo__deposito", "prestamo__compania_origen",
            "prestamo__compania_destino", "usuario",
        )
        if filtra_compania:
            devoluciones = devoluciones.filter(
                Q(prestamo__compania_origen_id=compania_id)
                | Q(prestamo__compania_destino_id=compania_id)
            )
        if q:
            devoluciones = devoluciones.filter(
                Q(prestamo__tipo__nombre__icontains=q)
                | Q(prestamo__lote__icontains=q)
                | Q(prestamo__compania_origen__nombre__icontains=q)
                | Q(prestamo__compania_destino__nombre__icontains=q)
            )
        grupos.append((CLASE_DEVOLUCION_PRESTAMO, devoluciones))

    context = {
        "movimientos": _mezclar_por_fecha(grupos, MOVIMIENTOS_LIMITE),
        "q": q,
        "tipo": tipo,
        "tipo_choices": Movimiento.Tipo.choices,
        "clase": clase,
        "clase_choices": CLASE_CHOICES,
        "ver_todas": ver_todas,
    }
    return render(request, "inventory/movimiento_list.html", context)


def _buscar_soldados(qs, q):
    """Filtra soldados por nombre o cédula (RF-21). La cédula se compara
    sin puntos ni espacios, igual a como se guarda."""
    if not q:
        return qs
    filtro = Q(apellidos_nombres__icontains=q)
    cedula = q.replace(".", "").replace(" ", "")
    if cedula.isascii() and cedula.isdigit():
        filtro |= Q(cedula__icontains=cedula)
    return qs.filter(filtro)


@requiere_autorizado
def soldado_list(request):
    compania_id, ver_todas = _companias_scope(request)
    qs = Soldado.objects.select_related("compania", "peloton")
    if compania_id and not ver_todas:
        qs = qs.filter(compania_id=compania_id)

    q = request.GET.get("q", "").strip()
    qs = _buscar_soldados(qs, q)

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


FICHA_HISTORIAL_LIMITE = 50


def _movimientos_armas_del_soldado(soldado):
    """Entregas, devoluciones y bajas de armamento que involucran al
    soldado, más reciente primero (issue #17).

    `Armamento.devolver()` no guarda el soldado en el `Movimiento` (solo el
    depósito de destino), así que `soldado.movimientos` no trae las
    devoluciones. Igual que `_historial_arma`, se encadena: una devolución
    o baja es de este soldado si la entrega anterior de esa arma fue a él."""
    armas = Movimiento.objects.filter(
        soldado=soldado, tipo=Movimiento.Tipo.ENTREGA
    ).values_list("armamento_id", flat=True)
    movimientos = (
        Movimiento.objects.filter(armamento_id__in=armas)
        .select_related("armamento__tipo", "deposito", "usuario")
        .order_by("armamento_id", "fecha", "pk")
    )
    propios = []
    tenedor = {}
    for mov in movimientos:
        if mov.tipo == Movimiento.Tipo.ENTREGA:
            tenedor[mov.armamento_id] = mov.soldado_id
            if mov.soldado_id == soldado.pk:
                propios.append(mov)
            continue
        if tenedor.get(mov.armamento_id) == soldado.pk:
            propios.append(mov)
        if mov.tipo == Movimiento.Tipo.DEVOLUCION:
            tenedor[mov.armamento_id] = None
    propios.sort(key=attrgetter("fecha"), reverse=True)
    return propios


def _resumen_a_cargo(armas, asignadas):
    """Total por tipo de material de lo que el soldado tiene hoy (issue #17,
    "tanta munición, tantas granadas, tanto casco"): armas contadas por
    tipo y existencias sumadas por tipo a través de lotes y depósitos.
    Armas primero, luego existencias, alfabético dentro de cada grupo."""
    por_arma = {}
    for arma in armas:
        por_arma[arma.tipo.nombre] = por_arma.get(arma.tipo.nombre, 0) + 1
    por_existencia = {}
    for asignada in asignadas:
        nombre = asignada.existencia.tipo.nombre
        por_existencia[nombre] = por_existencia.get(nombre, 0) + asignada.cantidad
    return [
        {"nombre": nombre, "cantidad": cantidad, "clase": CLASE_ARMAMENTO}
        for nombre, cantidad in sorted(por_arma.items())
    ] + [
        {"nombre": nombre, "cantidad": cantidad, "clase": CLASE_MUNICION}
        for nombre, cantidad in sorted(por_existencia.items())
    ]


@requiere_autorizado
def soldado_detalle(request, pk):
    """Ficha del soldado (RF-20, issue #17): lo que tiene a cargo ahora
    (resumen por tipo + detalle de armas y existencias, con acceso a
    devolver) y sus últimos movimientos. Visible para ambos roles y para
    soldados de cualquier compañía (la compañía de trabajo es un filtro,
    no un permiso — PRD S-2). No mueve material: devolver usa las
    pantallas existentes y vuelve aquí vía `?next=`."""
    soldado = get_object_or_404(
        Soldado.objects.select_related("compania", "peloton"), pk=pk
    )
    # `dar_de_baja()` cambia solo `estado` y deja `ubicacion`/`soldado`: un
    # arma de baja no está "a cargo" aunque siga apuntando al soldado.
    armas = list(
        soldado.armamentos.filter(
            ubicacion=Armamento.Ubicacion.EN_MANO, estado=Armamento.Estado.ACTIVO
        )
        .select_related("tipo")
        .order_by("tipo__nombre", "numero_serie")
    )
    asignadas = list(
        soldado.existencias_asignadas.select_related(
            "existencia__tipo", "existencia__deposito"
        ).order_by("existencia__tipo__nombre", "existencia__lote")
    )
    historial = _mezclar_por_fecha(
        [
            (CLASE_ARMAMENTO, _movimientos_armas_del_soldado(soldado)[:FICHA_HISTORIAL_LIMITE]),
            (
                CLASE_MUNICION,
                soldado.movimientos_existencia.select_related("existencia__tipo", "usuario"),
            ),
        ],
        FICHA_HISTORIAL_LIMITE,
    )
    context = {
        "soldado": soldado,
        "resumen": _resumen_a_cargo(armas, asignadas),
        "armas": armas,
        "asignadas": asignadas,
        "historial": historial,
        "ficha_url": reverse("inventory:soldado_detalle", args=[soldado.pk]),
    }
    return render(request, "inventory/soldado_detalle.html", context)


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


def _marcar_prestamos_pendientes(existencias):
    """Anota en cada existencia los préstamos con saldo pendiente que la
    afectan (RF-22): `.prestamos_recibidos` (la compañía de la existencia
    es la destino) y `.prestamos_realizados` (es la origen), con el mismo
    tipo, depósito y lote. Para resaltarlos en Munición sin guardar nada."""
    claves = {(e.tipo_id, e.deposito_id, e.lote) for e in existencias}
    recibidos, realizados = {}, {}
    pendientes = Prestamo.objects.filter(
        cantidad__gt=F("cantidad_devuelta"),
        tipo_id__in={tipo for tipo, _, _ in claves},
    ).select_related("compania_origen", "compania_destino")
    for prestamo in pendientes:
        clave = (prestamo.tipo_id, prestamo.deposito_id, prestamo.lote)
        if clave not in claves:
            continue
        recibidos.setdefault(clave + (prestamo.compania_destino_id,), []).append(prestamo)
        realizados.setdefault(clave + (prestamo.compania_origen_id,), []).append(prestamo)
    for existencia in existencias:
        clave = (
            existencia.tipo_id, existencia.deposito_id, existencia.lote, existencia.compania_id,
        )
        existencia.prestamos_recibidos = recibidos.get(clave, [])
        existencia.prestamos_realizados = realizados.get(clave, [])


@requiere_autorizado
def existencia_list(request):
    compania_id, ver_todas = _companias_scope(request)
    # `en_mano`: cuánto de cada existencia tienen hoy los soldados (RF-18),
    # para que se vea desde Munición a dónde se fue lo entregado (issue #16).
    qs = Existencia.objects.select_related("tipo", "compania", "deposito").annotate(
        en_mano=Sum("asignaciones__cantidad")
    )
    if compania_id and not ver_todas:
        qs = qs.filter(compania_id=compania_id)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(tipo__nombre__icontains=q) | Q(lote__icontains=q))

    deposito_id = request.GET.get("deposito", "")
    if deposito_id:
        qs = qs.filter(deposito_id=deposito_id)

    existencias = list(qs)
    _marcar_prestamos_pendientes(existencias)
    context = {
        "existencias": existencias,
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
def existencia_entregar(request, pk):
    """Flujo guiado (Soldado → Confirmar) sobre `Existencia.entregar()`
    (RF-18) — visualmente simétrico a `armamento_entregar`."""
    existencia = get_object_or_404(
        Existencia.objects.select_related("tipo", "compania", "deposito"), pk=pk
    )

    if request.method == "POST":
        soldado = get_object_or_404(
            Soldado, pk=request.POST.get("soldado"), compania_id=existencia.compania_id
        )
        try:
            cantidad = int(request.POST.get("cantidad", ""))
        except ValueError:
            cantidad = 0
        observacion = request.POST.get("observacion", "")
        try:
            existencia.entregar(
                soldado=soldado, cantidad=cantidad, usuario=request.user, observacion=observacion
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("inventory:existencia_entregar", pk=existencia.pk)
        messages.success(request, f"{cantidad} de {existencia.tipo.nombre} entregadas a {soldado}.")
        return redirect("inventory:existencia_list")

    soldado_id = request.GET.get("soldado")
    if soldado_id:
        soldado = get_object_or_404(Soldado, pk=soldado_id, compania_id=existencia.compania_id)
        context = {"existencia": existencia, "soldado": soldado, "paso": "confirmar"}
        return render(request, "inventory/existencia_entregar.html", context)

    q = request.GET.get("q", "").strip()
    soldados = Soldado.objects.filter(compania_id=existencia.compania_id).select_related("peloton")
    soldados = _buscar_soldados(soldados, q)

    context = {"existencia": existencia, "q": q, "soldados": soldados[:30], "paso": "soldado"}
    return render(request, "inventory/existencia_entregar.html", context)


@requiere_autorizado
def existencia_devolver(request, pk):
    """Un solo paso sobre `ExistenciaAsignada.devolver()` (RF-18) —
    simétrico a `armamento_devolver`; el depósito de retorno es siempre el
    mismo del que salió, así que no hay nada que elegir."""
    asignada = get_object_or_404(
        ExistenciaAsignada.objects.select_related(
            "existencia__tipo", "existencia__compania", "existencia__deposito",
            "soldado", "soldado__peloton",
        ),
        pk=pk,
    )

    next_url = _next_seguro(request)
    if request.method == "POST":
        try:
            cantidad = int(request.POST.get("cantidad", ""))
        except ValueError:
            cantidad = 0
        observacion = request.POST.get("observacion", "")
        try:
            asignada.devolver(cantidad=cantidad, usuario=request.user, observacion=observacion)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(
                _con_next(reverse("inventory:existencia_devolver", args=[asignada.pk]), next_url)
            )
        messages.success(
            request, f"{cantidad} de {asignada.existencia.tipo.nombre} devueltas a depósito."
        )
        return redirect(next_url or "inventory:existencia_asignada_list")

    context = {"asignada": asignada, "next": next_url}
    return render(request, "inventory/existencia_devolver.html", context)


@requiere_autorizado
def existencia_asignada_list(request):
    """Lo que cada soldado tiene en mano (RF-18) + historial reciente de
    entregas/devoluciones de existencias (RNF-03).

    `?existencia=<pk>` (enlace "ver quién" de cada tarjeta de Munición,
    issue #16) restringe todo a esa existencia. En ese caso la compañía de
    trabajo no se aplica: la existencia ya define su compañía, y el enlace
    también se usa desde "ver todas"."""
    compania_id, ver_todas = _companias_scope(request)
    asignadas = ExistenciaAsignada.objects.select_related(
        "existencia__tipo", "existencia__compania", "existencia__deposito", "soldado"
    )
    movimientos = MovimientoExistencia.objects.select_related(
        "existencia__tipo", "existencia__compania", "soldado", "usuario"
    )
    existencia = None
    existencia_id = request.GET.get("existencia", "")
    if existencia_id.isdigit():
        existencia = get_object_or_404(
            Existencia.objects.select_related("tipo", "deposito"), pk=existencia_id
        )
        asignadas = asignadas.filter(existencia=existencia)
        movimientos = movimientos.filter(existencia=existencia)
    elif compania_id and not ver_todas:
        asignadas = asignadas.filter(existencia__compania_id=compania_id)
        movimientos = movimientos.filter(existencia__compania_id=compania_id)
    context = {
        "asignadas": asignadas,
        "movimientos": movimientos[:50],
        "existencia": existencia,
        "ver_todas": ver_todas,
    }
    return render(request, "inventory/existencia_asignada_list.html", context)


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


@requiere_autorizado
def prestamo_devolver(request, pk):
    """Devolución total o parcial de un préstamo a la compañía de origen
    (RF-22, ADR-0006). Ambos roles, igual que prestar (RF-15)."""
    prestamo = get_object_or_404(
        Prestamo.objects.select_related(
            "tipo", "deposito", "compania_origen", "compania_destino"
        ),
        pk=pk,
    )
    destino = Existencia.objects.filter(
        tipo_id=prestamo.tipo_id,
        compania_id=prestamo.compania_destino_id,
        deposito_id=prestamo.deposito_id,
        lote=prestamo.lote,
    ).first()
    disponible = destino.cantidad if destino else 0
    maximo = min(prestamo.saldo, disponible)

    next_url = _next_seguro(request)
    if request.method == "POST":
        try:
            cantidad = int(request.POST.get("cantidad", ""))
        except ValueError:
            cantidad = 0
        observacion = request.POST.get("observacion", "")
        try:
            prestamo.devolver(cantidad=cantidad, usuario=request.user, observacion=observacion)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(
                _con_next(reverse("inventory:prestamo_devolver", args=[prestamo.pk]), next_url)
            )
        messages.success(
            request,
            f"{cantidad} de {prestamo.tipo.nombre} devueltas a {prestamo.compania_origen.nombre}.",
        )
        return redirect(next_url or "inventory:prestamo_list")

    context = {
        "prestamo": prestamo,
        "disponible": disponible,
        "maximo": maximo,
        "next": next_url,
    }
    return render(request, "inventory/prestamo_devolver.html", context)
