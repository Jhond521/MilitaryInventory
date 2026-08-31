from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.inventory.models import Compania, Unidad
from apps.inventory.views import SESSION_KEY

User = get_user_model()

# Tests que renderizan una página completa usan almacenamiento de estáticos
# simple: el manifest de whitenoise solo existe tras `collectstatic`, que no
# corre como parte de la suite (ver apps/inventory/tests.py).
_PLAIN_STATIC_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class HealthEndpointTests(TestCase):
    def test_health_returns_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class UserModelTests(TestCase):
    def test_user_is_created_with_email_and_default_enlace_role(self):
        user = User.objects.create_user(email="Enlace@Example.com", password="pw-123456")
        self.assertEqual(user.email, "enlace@example.com")  # normalized to lowercase
        self.assertEqual(user.role, User.Role.ENLACE)
        self.assertFalse(user.is_admin_role)

    def test_superuser_has_admin_role(self):
        admin = User.objects.create_superuser(email="cmd@example.com", password="pw-123456")
        self.assertTrue(admin.is_admin_role)
        self.assertTrue(admin.is_superuser)


@override_settings(AUTHORIZED_EMAILS=["ok@example.com"])
class AllowlistBackendTests(TestCase):
    def setUp(self):
        User.objects.create_user(email="ok@example.com", password="pw-123456")
        User.objects.create_user(email="blocked@example.com", password="pw-123456")

    def test_authorized_email_can_authenticate(self):
        self.assertIsNotNone(authenticate(username="ok@example.com", password="pw-123456"))

    def test_email_outside_allowlist_is_rejected(self):
        self.assertIsNone(authenticate(username="blocked@example.com", password="pw-123456"))


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class UsuarioViewTests(TestCase):
    """Alta/edición de usuarios (H-01), solo ADMIN."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com", password="x", role=User.Role.ADMIN
        )
        self.client.force_login(self.admin)
        unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        compania = Compania.objects.create(unidad=unidad, nombre="Alcatraz")
        session = self.client.session
        session[SESSION_KEY] = compania.pk
        session.save()

    def test_crear_usuario(self):
        response = self.client.post(
            reverse("accounts:usuario_crear"),
            {
                "email": "nuevo@example.com", "first_name": "Ana", "last_name": "Ríos",
                "role": User.Role.ENLACE,
                "password": "clave-larga-1", "password_confirmar": "clave-larga-1",
            },
        )
        self.assertRedirects(response, reverse("accounts:usuario_list"))
        nuevo = User.objects.get(email="nuevo@example.com")
        self.assertEqual(nuevo.role, User.Role.ENLACE)
        self.assertTrue(nuevo.check_password("clave-larga-1"))

    def test_crear_usuario_contrasenas_no_coinciden(self):
        response = self.client.post(
            reverse("accounts:usuario_crear"),
            {
                "email": "nuevo2@example.com", "first_name": "Ana", "last_name": "Ríos",
                "role": User.Role.ENLACE,
                "password": "clave-larga-1", "password_confirmar": "otra-clave",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="nuevo2@example.com").exists())

    def test_editar_usuario(self):
        otro = User.objects.create_user(
            email="otro@example.com", password="x", role=User.Role.ENLACE
        )
        response = self.client.post(
            reverse("accounts:usuario_editar", args=[otro.pk]),
            {
                "email": otro.email, "first_name": "Carlos", "last_name": "Ruiz",
                "role": User.Role.ADMIN, "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("accounts:usuario_list"))
        otro.refresh_from_db()
        self.assertEqual(otro.role, User.Role.ADMIN)
        self.assertEqual(otro.first_name, "Carlos")

    def test_restablecer_password(self):
        otro = User.objects.create_user(email="otro2@example.com", password="vieja-clave")
        response = self.client.post(
            reverse("accounts:usuario_restablecer_password", args=[otro.pk]),
            {"new_password1": "clave-nueva-1", "new_password2": "clave-nueva-1"},
        )
        self.assertRedirects(response, reverse("accounts:usuario_list"))
        otro.refresh_from_db()
        self.assertTrue(otro.check_password("clave-nueva-1"))

    def test_admin_no_puede_quitarse_a_si_mismo_el_rol(self):
        response = self.client.post(
            reverse("accounts:usuario_editar", args=[self.admin.pk]),
            {
                "email": self.admin.email, "first_name": "", "last_name": "",
                "role": User.Role.ENLACE, "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMIN)

    def test_admin_no_puede_desactivarse_a_si_mismo(self):
        response = self.client.post(
            reverse("accounts:usuario_editar", args=[self.admin.pk]),
            {
                "email": self.admin.email, "first_name": "", "last_name": "",
                "role": User.Role.ADMIN,
                # is_active ausente = False en un checkbox sin marcar
            },
        )
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_puede_quitarle_el_rol_a_otro_administrador(self):
        otro_admin = User.objects.create_user(
            email="otroadmin@example.com", password="x", role=User.Role.ADMIN
        )
        response = self.client.post(
            reverse("accounts:usuario_editar", args=[otro_admin.pk]),
            {
                "email": otro_admin.email, "first_name": "", "last_name": "",
                "role": User.Role.ENLACE, "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("accounts:usuario_list"))
        otro_admin.refresh_from_db()
        self.assertEqual(otro_admin.role, User.Role.ENLACE)
