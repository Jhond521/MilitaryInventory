from django import forms
from django.utils import timezone

from .models import Armamento, CampoPersonalizado, Deposito, Soldado


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
