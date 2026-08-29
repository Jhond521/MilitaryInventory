"""SIGA domain model.

Conceptos (ver docs/PRD.md):

- Unidad      : una sola, sembrada (Batallón de Selva No. 52). Normalizada
                para soportar varias unidades a futuro; sin configurador (NO-1).
- Compania    : pertenece a una unidad. 7 sembradas. Un soldado pertenece a una.
- Deposito    : lugar físico de almacenamiento, agnóstico a la compañía. 2 sembrados.
- Soldado     : personal de tropa, NO es usuario. Pertenece a una sola compañía.
- TipoArmamento: catálogo creable. 23 tipos sembrados.
- Armamento   : el ítem central. Se identifica por número de serie. Pertenece a
                una compañía y está EN MANO de un soldado o EN DEPÓSITO.
- Movimiento  : historial de entregas/devoluciones (trazabilidad, RNF-03).
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


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


class Soldado(models.Model):
    apellidos_nombres = models.CharField("apellidos y nombres", max_length=200)
    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="soldados")

    class Meta:
        verbose_name = "soldado"
        verbose_name_plural = "soldados"
        ordering = ["apellidos_nombres"]

    def __str__(self):
        return f"{self.apellidos_nombres} ({self.compania})"


class TipoArmamento(models.Model):
    nombre = models.CharField("tipo de armamento", max_length=150, unique=True)

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
