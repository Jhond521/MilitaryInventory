"""System users (RF-01).

Only 6 people use SIGA and they authenticate with email + password.
There are exactly two roles:

- ADMIN  (administrador): full control over master data, altas/bajas,
  custom fields and users, plus movements.
- ENLACE (enlace): read/search and register movements only.

Soldiers are NOT users — see apps.inventory.models.Soldado.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Manager for a user model that logs in with email instead of username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("El correo es obligatorio")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)  # all users reach the admin site
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, role=User.Role.ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        ENLACE = "ENLACE", "Enlace"

    username = None  # login is by email
    email = models.EmailField("correo", unique=True)
    role = models.CharField(
        "rol", max_length=10, choices=Role.choices, default=Role.ENLACE
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self):
        return self.email

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN
