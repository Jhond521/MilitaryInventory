from django import forms
from django.utils import timezone

from .models import (
    Armamento,
    CampoPersonalizado,
    Compania,
    Deposito,
    Existencia,
    Soldado,
    TipoArmamento,
)


class EntregaForm(forms.Form):
    soldado = forms.ModelChoiceField(queryset=Soldado.objects.none(), label="Soldado")
    observacion = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, compania_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if compania_id is not None:
            self.fields["soldado"].queryset = Soldado.objects.filter(compania_id=compania_id)


class DevolucionForm(forms.Form):
    deposito = forms.ModelChoiceField(queryset=Deposito.objects.all(), label="Depósito")
    observacion = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class BajaForm(forms.Form):
    motivo = forms.ChoiceField(choices=Armamento.MotivoBaja.choices, label="Motivo")
    fecha = forms.DateField(
        label="Fecha de baja",
        initial=timezone.localdate,
        # El input HTML type="date" exige el valor en formato yyyy-mm-dd; el
        # formato de fecha por defecto del locale (es-co) es dd/mm/yyyy, así
        # que sin esto el navegador descarta silenciosamente el valor inicial.
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    observacion = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )


def campo_nombre_de_campo(campo):
    """Nombre técnico (HTML) del campo de formulario para un CampoPersonalizado."""
    return f"campo_{campo.pk}"


def campo_a_form_field(campo, valor_inicial):
    """Construye el `forms.Field` para capturar un CampoPersonalizado según su
    tipo (texto/número/fecha) — RF-08. Solo aplica al armamento: no hay
    equivalente para Soldado ni TipoArmamento (NO-2)."""
    if campo.tipo == CampoPersonalizado.Tipo.NUMERO:
        return forms.DecimalField(required=False, label=campo.nombre, initial=valor_inicial)
    if campo.tipo == CampoPersonalizado.Tipo.FECHA:
        return forms.DateField(
            required=False,
            label=campo.nombre,
            initial=valor_inicial,
            widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        )
    return forms.CharField(required=False, label=campo.nombre, initial=valor_inicial)


def aplicar_campos_personalizados(armamento, cleaned_data):
    """Traslada los valores de los `campo_<pk>` del formulario a
    `Armamento.datos_extra` (RF-08) — misma lógica que usaba
    `ArmamentoAdmin.save_model` antes de que el admin se retirara."""
    datos_extra = dict(armamento.datos_extra or {})
    for campo in CampoPersonalizado.objects.all():
        nombre_campo = campo_nombre_de_campo(campo)
        if nombre_campo not in cleaned_data:
            continue
        valor = cleaned_data[nombre_campo]
        if valor in (None, ""):
            datos_extra.pop(campo.nombre, None)
        else:
            datos_extra[campo.nombre] = valor
    armamento.datos_extra = datos_extra


class SoldadoForm(forms.ModelForm):
    class Meta:
        model = Soldado
        fields = ["apellidos_nombres", "compania", "peloton"]
        labels = {"apellidos_nombres": "Apellidos y nombres"}


class ArmamentoCrearForm(forms.ModelForm):
    """Alta de armamento (H-07) — siempre entra en depósito; entregar()
    (H-09) es el único camino para que pase a mano de un soldado."""

    class Meta:
        model = Armamento
        fields = ["numero_serie", "tipo", "compania", "deposito"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoArmamento.objects.filter(
            control=TipoArmamento.Control.SERIE
        )

    def save(self, commit=True):
        armamento = super().save(commit=False)
        armamento.ubicacion = Armamento.Ubicacion.DEPOSITO
        if commit:
            armamento.save()
        return armamento


class ArmamentoEditarForm(forms.ModelForm):
    """Edición de datos propios del armamento (H-12) — deliberadamente NO
    incluye ubicación/soldado/depósito/estado: esos solo cambian a través de
    entregar()/devolver()/dar_de_baja() (RF-10/RF-11), para que cada cambio
    de ubicación quede su `Movimiento`."""

    class Meta:
        model = Armamento
        fields = ["numero_serie", "tipo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoArmamento.objects.filter(
            control=TipoArmamento.Control.SERIE
        )
        datos_extra = self.instance.datos_extra or {}
        for campo in CampoPersonalizado.objects.all():
            self.fields[campo_nombre_de_campo(campo)] = campo_a_form_field(
                campo, datos_extra.get(campo.nombre)
            )


class ExistenciaForm(forms.ModelForm):
    class Meta:
        model = Existencia
        fields = ["tipo", "compania", "deposito", "lote", "cantidad"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoArmamento.objects.filter(
            control=TipoArmamento.Control.CANTIDAD
        )


class PrestamoForm(forms.Form):
    """Préstamo de munición entre compañías (RF-15, H-16) — un formulario
    plano, no ModelForm: `Prestamo.clean()`/`.save()` ya hacen toda la
    validación y el ajuste atómico de existencias; aquí solo se recoge la
    entrada y se construye la instancia en la vista."""

    tipo = forms.ModelChoiceField(
        queryset=TipoArmamento.objects.filter(control=TipoArmamento.Control.CANTIDAD),
        label="Tipo",
    )
    deposito = forms.ModelChoiceField(queryset=Deposito.objects.all(), label="Depósito")
    compania_origen = forms.ModelChoiceField(
        queryset=Compania.objects.all(), label="Compañía origen"
    )
    compania_destino = forms.ModelChoiceField(
        queryset=Compania.objects.all(), label="Compañía destino"
    )
    lote = forms.CharField(label="Lote", required=False)
    cantidad = forms.IntegerField(label="Cantidad", min_value=1)
    observacion = forms.CharField(
        label="Observación", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
