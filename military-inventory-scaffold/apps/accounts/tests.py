from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


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
