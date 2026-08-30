"""SIGA domain model.

Conceptos (ver docs/PRD.md):

- Unidad      : una sola, sembrada (Batallón de Selva No. 52). Normalizada
                para soportar varias unidades a futuro; sin configurador (NO-1).
- Compania    : pertenece a una unidad. 7 sembradas. Un soldado pertenece a una.
- Deposito    : lugar físico de almacenamiento, agnóstico a la compañía. 2 sembrados.
- Peloton     : 4 por compañía. Dato del soldado, editable manualmente (RF-16).
- Soldado     : personal de tropa, NO es usuario. Pertenece a una sola compañía
                y a un solo pelotón de esa compañía.
- TipoArmamento: catálogo creable, controlado por SERIE (individual) o CANTIDAD
                (existencias) — RF-05.
- Armamento   : el ítem central, siempre de un tipo por SERIE. Se identifica por
                número de serie. Pertenece a una compañía y está EN MANO de un
                soldado (de donde deriva su pelotón) o EN DEPÓSITO.
- Existencia  : saldo por CANTIDAD (munición, cascos) de un tipo, compañía,
                depósito y lote opcional (RF-14).
- Prestamo    : traslado de cantidad de un tipo CANTIDAD entre compañías,
                ajustando las existencias de origen y destino (RF-15).
- Movimiento  : historial de entregas/devoluciones de armamento serializado
                (trazabilidad, RNF-03).
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class Unidad(models.Model):
    nombre = models.CharField("nombre", max_length=120, unique=True)

    class Meta:
        verbose_name = "unidad"
        verbose_name_plural = "unidades"

    def __str__(self):
        return self.nombre


class Compania(models.Model):
    unidad = models.ForeignKey(Unidad, on_delete=models.PROTECT, related_name="companias")
    nombre = models.CharField("nombre", max_length=120)

    class Meta:
        verbose_name = "compañía"
        verbose_name_plural = "compañías"
        constraints = [
            models.UniqueConstraint(fields=["unidad", "nombre"], name="uq_compania_unidad_nombre")
        ]

    def __str__(self):
        return self.nombre


class Deposito(models.Model):
    nombre = models.CharField("nombre", max_length=120, unique=True)
    descripcion = models.CharField("descripción", max_length=200, blank=True)

    class Meta:
        verbose_name = "depósito"
        verbose_name_plural = "depósitos"

    def __str__(self):
        return self.nombre


class Peloton(models.Model):
    """Pelotón de una compañía (4 por compañía, sembrados) — RF-16."""

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="pelotones")
    nombre = models.CharField("nombre", max_length=120)

    class Meta:
        verbose_name = "pelotón"
        verbose_name_plural = "pelotones"
        ordering = ["compania__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["compania", "nombre"], name="uq_peloton_compania_nombre"
            )
        ]

    def __str__(self):
        return f"{self.nombre} ({self.compania})"


class Soldado(models.Model):
    apellidos_nombres = models.CharField("apellidos y nombres", max_length=200)
    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="soldados")
    peloton = models.ForeignKey(Peloton, on_delete=models.PROTECT, related_name="soldados")

    class Meta:
        verbose_name = "soldado"
        verbose_name_plural = "soldados"
        ordering = ["apellidos_nombres"]

    def __str__(self):
        return f"{self.apellidos_nombres} ({self.compania})"

    def clean(self):
        if self.peloton_id and self.compania_id and self.peloton.compania_id != self.compania_id:
            raise ValidationError("El pelotón debe pertenecer a la misma compañía del soldado.")


class TipoArmamento(models.Model):
    class Control(models.TextChoices):
        SERIE = "SERIE", "Por serie individual"
        CANTIDAD = "CANTIDAD", "Por cantidad"

    nombre = models.CharField("tipo de armamento", max_length=150, unique=True)
    control = models.CharField(
        "forma de control", max_length=10, choices=Control.choices, default=Control.SERIE
    )

    class Meta:
        verbose_name = "tipo de armamento"
        verbose_name_plural = "tipos de armamento"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Armamento(models.Model):
    class Ubicacion(models.TextChoices):
        DEPOSITO = "DEPOSITO", "En depósito"
        EN_MANO = "EN_MANO", "En mano"

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        BAJA = "BAJA", "Dado de baja"

    class MotivoBaja(models.TextChoices):
        DANO = "DANO", "Dañado"
        PERDIDA = "PERDIDA", "Perdido"
        ROBO = "ROBO", "Robado"

    numero_serie = models.CharField("número de serie", max_length=120, unique=True)
    tipo = models.ForeignKey(TipoArmamento, on_delete=models.PROTECT, related_name="armamentos")
    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="armamentos")

    ubicacion = models.CharField(
        "ubicación", max_length=10, choices=Ubicacion.choices, default=Ubicacion.DEPOSITO
    )
    deposito = models.ForeignKey(
        Deposito, on_delete=models.PROTECT, null=True, blank=True, related_name="armamentos"
    )
    soldado = models.ForeignKey(
        Soldado, on_delete=models.PROTECT, null=True, blank=True, related_name="armamentos"
    )

    estado = models.CharField(
        "estado", max_length=10, choices=Estado.choices, default=Estado.ACTIVO
    )
    motivo_baja = models.CharField(
        "motivo de baja", max_length=10, choices=MotivoBaja.choices, blank=True
    )
    fecha_baja = models.DateField("fecha de baja", null=True, blank=True)

    # Campos personalizados definidos por el administrador (RF-08). Solo aplica
    # al armamento. Estructura: {"nombre_campo": valor}.
    datos_extra = models.JSONField("datos adicionales", default=dict, blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "armamento"
        verbose_name_plural = "armamento"
        ordering = ["numero_serie"]
        indexes = [models.Index(fields=["numero_serie"])]

    def __str__(self):
        return f"{self.numero_serie} — {self.tipo}"

    def clean(self):
        # El armamento serializado solo admite tipos controlados por serie (RF-05).
        if self.tipo_id and self.tipo.control != TipoArmamento.Control.SERIE:
            raise ValidationError(
                "El tipo de armamento debe controlarse por serie individual."
            )
        # Coherencia entre ubicación y su referencia.
        if self.ubicacion == self.Ubicacion.EN_MANO:
            if self.soldado is None:
                raise ValidationError("Un arma en mano debe tener un soldado asignado.")
            if self.soldado.compania_id != self.compania_id:
                raise ValidationError("El soldado debe pertenecer a la misma compañía del arma.")
        if self.ubicacion == self.Ubicacion.DEPOSITO and self.deposito is None:
            raise ValidationError("Un arma en depósito debe indicar en cuál depósito está.")

    @property
    def ubicacion_actual(self) -> str:
        if self.ubicacion == self.Ubicacion.EN_MANO and self.soldado:
            return f"En mano — {self.soldado.apellidos_nombres} ({self.compania})"
        if self.deposito:
            return f"En depósito — {self.deposito}"
        return self.get_ubicacion_display()

    @property
    def peloton_actual(self) -> "Peloton | None":
        """Pelotón derivado del soldado que tiene el arma en mano (RF-16)."""
        if self.ubicacion == self.Ubicacion.EN_MANO and self.soldado_id:
            return self.soldado.peloton
        return None

    def entregar(self, *, soldado, usuario, observacion=""):
        """Mueve el arma de depósito a mano de un soldado, dejando rastro (RF-10)."""
        if self.ubicacion != self.Ubicacion.DEPOSITO:
            raise ValidationError("El arma debe estar en depósito para poder entregarse.")
        if soldado.compania_id != self.compania_id:
            raise ValidationError("El soldado debe pertenecer a la misma compañía del arma.")
        with transaction.atomic():
            self.ubicacion = self.Ubicacion.EN_MANO
            self.soldado = soldado
            self.deposito = None
            self.full_clean()
            self.save()
            return Movimiento.objects.create(
                armamento=self,
                tipo=Movimiento.Tipo.ENTREGA,
                soldado=soldado,
                usuario=usuario,
                observacion=observacion,
            )

    def devolver(self, *, deposito, usuario, observacion=""):
        """Mueve el arma de mano de un soldado a depósito, dejando rastro (RF-10)."""
        if self.ubicacion != self.Ubicacion.EN_MANO:
            raise ValidationError("El arma debe estar en mano de un soldado para poder devolverse.")
        with transaction.atomic():
            self.ubicacion = self.Ubicacion.DEPOSITO
            self.deposito = deposito
            self.soldado = None
            self.full_clean()
            self.save()
            return Movimiento.objects.create(
                armamento=self,
                tipo=Movimiento.Tipo.DEVOLUCION,
                deposito=deposito,
                usuario=usuario,
                observacion=observacion,
            )


class CampoPersonalizado(models.Model):
    """Definición de un campo personalizado del armamento (RF-08)."""

    class Tipo(models.TextChoices):
        TEXTO = "TEXTO", "Texto"
        NUMERO = "NUMERO", "Número"
        FECHA = "FECHA", "Fecha"

    nombre = models.CharField("nombre del campo", max_length=80, unique=True)
    tipo = models.CharField("tipo de dato", max_length=10, choices=Tipo.choices, default=Tipo.TEXTO)

    class Meta:
        verbose_name = "campo personalizado (armamento)"
        verbose_name_plural = "campos personalizados (armamento)"

    def __str__(self):
        return f"{self.nombre} [{self.get_tipo_display()}]"


class Movimiento(models.Model):
    """Historial de entregas y devoluciones (RF-10, RNF-03)."""

    class Tipo(models.TextChoices):
        ENTREGA = "ENTREGA", "Entrega (a soldado)"
        DEVOLUCION = "DEVOLUCION", "Devolución (a depósito)"

    armamento = models.ForeignKey(Armamento, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField("tipo de movimiento", max_length=12, choices=Tipo.choices)
    soldado = models.ForeignKey(
        Soldado, on_delete=models.PROTECT, null=True, blank=True, related_name="movimientos"
    )
    deposito = models.ForeignKey(
        Deposito, on_delete=models.PROTECT, null=True, blank=True, related_name="movimientos"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimientos"
    )
    observacion = models.CharField("observación", max_length=300, blank=True)
    fecha = models.DateTimeField("fecha y hora", auto_now_add=True)

    class Meta:
        verbose_name = "movimiento"
        verbose_name_plural = "movimientos"
        ordering = ["-fecha"]

    def __str__(self):
        serie = self.armamento.numero_serie
        return f"{self.get_tipo_display()} — {serie} — {self.fecha:%Y-%m-%d %H:%M}"


class Existencia(models.Model):
    """Saldo por CANTIDAD (munición, cascos) de un tipo en una compañía y
    depósito, opcionalmente por lote (RF-14)."""

    tipo = models.ForeignKey(TipoArmamento, on_delete=models.PROTECT, related_name="existencias")
    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="existencias")
    deposito = models.ForeignKey(Deposito, on_delete=models.PROTECT, related_name="existencias")
    lote = models.CharField("número de lote", max_length=80, blank=True)
    cantidad = models.PositiveIntegerField("cantidad", default=0)

    class Meta:
        verbose_name = "existencia"
        verbose_name_plural = "existencias"
        ordering = ["tipo__nombre", "compania__nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo", "compania", "deposito", "lote"],
                name="uq_existencia_tipo_compania_deposito_lote",
            )
        ]

    def __str__(self):
        lote = f" (lote {self.lote})" if self.lote else ""
        return f"{self.tipo}{lote} — {self.compania}: {self.cantidad}"

    def clean(self):
        if self.tipo_id and self.tipo.control != TipoArmamento.Control.CANTIDAD:
            raise ValidationError("Solo los tipos controlados por cantidad llevan existencias.")


class Prestamo(models.Model):
    """Préstamo de una cantidad de un tipo CANTIDAD (típicamente munición)
    entre compañías — RF-15. Al crearse, ajusta atómicamente las existencias
    de origen (resta) y destino (suma, creándola si no existía)."""

    tipo = models.ForeignKey(TipoArmamento, on_delete=models.PROTECT, related_name="prestamos")
    deposito = models.ForeignKey(Deposito, on_delete=models.PROTECT, related_name="prestamos")
    lote = models.CharField("número de lote", max_length=80, blank=True)
    cantidad = models.PositiveIntegerField("cantidad")
    compania_origen = models.ForeignKey(
        Compania, on_delete=models.PROTECT, related_name="prestamos_realizados"
    )
    compania_destino = models.ForeignKey(
        Compania, on_delete=models.PROTECT, related_name="prestamos_recibidos"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="prestamos"
    )
    observacion = models.CharField("observación", max_length=300, blank=True)
    fecha = models.DateTimeField("fecha y hora", auto_now_add=True)

    class Meta:
        verbose_name = "préstamo"
        verbose_name_plural = "préstamos"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.tipo} x{self.cantidad}: {self.compania_origen} → {self.compania_destino}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            super().save(*args, **kwargs)
            return
        with transaction.atomic():
            origen = Existencia.objects.select_for_update().get(
                tipo=self.tipo,
                compania=self.compania_origen,
                deposito=self.deposito,
                lote=self.lote,
            )
            origen.cantidad -= self.cantidad
            origen.save(update_fields=["cantidad"])

            destino, _ = Existencia.objects.select_for_update().get_or_create(
                tipo=self.tipo,
                compania=self.compania_destino,
                deposito=self.deposito,
                lote=self.lote,
                defaults={"cantidad": 0},
            )
            destino.cantidad += self.cantidad
            destino.save(update_fields=["cantidad"])

            super().save(*args, **kwargs)

    def clean(self):
        if self.tipo_id and self.tipo.control != TipoArmamento.Control.CANTIDAD:
            raise ValidationError("Solo se prestan tipos controlados por cantidad.")
        if (
            self.compania_origen_id
            and self.compania_destino_id
            and self.compania_origen_id == self.compania_destino_id
        ):
            raise ValidationError("La compañía de origen y destino no pueden ser la misma.")
        if self.cantidad is not None and self.cantidad <= 0:
            raise ValidationError("La cantidad prestada debe ser mayor a cero.")
        if self._state.adding and self.tipo_id and self.compania_origen_id and self.deposito_id:
            try:
                origen = Existencia.objects.get(
                    tipo=self.tipo,
                    compania=self.compania_origen,
                    deposito=self.deposito,
                    lote=self.lote,
                )
            except Existencia.DoesNotExist:
                raise ValidationError(
                    f"{self.compania_origen} no tiene existencia registrada de {self.tipo} "
                    f"en {self.deposito}."
                ) from None
            if self.cantidad and origen.cantidad < self.cantidad:
                raise ValidationError(
                    f"{self.compania_origen} no tiene suficiente cantidad "
                    f"({origen.cantidad} disponible, se solicitan {self.cantidad})."
                )
