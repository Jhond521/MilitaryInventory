from django import forms

from .models import User


class UsuarioForm(forms.ModelForm):
    """Alta/edición de usuarios (H-01) — sin exponer `is_superuser`/`is_staff`,
    que ya no tienen función real sin el admin de Django. La contraseña se
    pide solo al crear; para restablecerla en edición hay una vista aparte
    (`usuario_restablecer_password`, vía `SetPasswordForm`)."""

    password = forms.CharField(
        label="Contraseña", widget=forms.PasswordInput, required=False
    )
    password_confirmar = forms.CharField(
        label="Confirmar contraseña", widget=forms.PasswordInput, required=False
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "role", "is_active"]
        labels = {
            "first_name": "Nombres",
            "last_name": "Apellidos",
            "role": "Rol",
            "is_active": "Activo",
        }

    def __init__(self, *args, es_edicion=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.es_edicion = es_edicion
        if es_edicion:
            del self.fields["password"]
            del self.fields["password_confirmar"]
        else:
            del self.fields["is_active"]

    def clean(self):
        cleaned = super().clean()
        if not self.es_edicion:
            password = cleaned.get("password")
            if not password:
                self.add_error("password", "La contraseña es obligatoria.")
            elif password != cleaned.get("password_confirmar"):
                self.add_error("password_confirmar", "Las contraseñas no coinciden.")
        return cleaned
