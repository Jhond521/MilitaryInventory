"""Issue #35 (RF-25): read-only CONSULTA users.

They log in without being in AUTHORIZED_EMAILS, see every screen, and can't
run any action (entregar/devolver/prestar or master data).
"""
from io import StringIO

from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.inventory.models import (
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
    Unidad,
)
from apps.inventory.views import SESSION_KEY

User = get_user_model()

_PLAIN_STATIC_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class ConsultaRoleModelTests(TestCase):
    def test_rol_consulta_existe_y_migraciones_al_dia(self):
        """#35 AC-1 — rol CONSULTA con etiqueta "Consulta"; makemigrations --check limpio."""
        self.assertEqual(User.Role.CONSULTA, "CONSULTA")
        self.assertEqual(User.Role.CONSULTA.label, "Consulta")
        call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())

    def test_puede_operar_por_rol(self):
        consulta = User(email="c@example.com", role=User.Role.CONSULTA)
        self.assertFalse(consulta.puede_operar)
        self.assertTrue(consulta.is_consulta_role)
        self.assertTrue(User(email="e@example.com", role=User.Role.ENLACE).puede_operar)
        self.assertTrue(User(email="a@example.com", role=User.Role.ADMIN).puede_operar)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE, AUTHORIZED_EMAILS=["ok@example.com"])
class ConsultaLoginTests(TestCase):
    def test_consulta_fuera_de_la_lista_puede_entrar(self):
        """#35 AC-3 — un Consulta activo con correo fuera de la lista se autentica."""
        consulta = User.objects.create_user(
            email="lector@example.com", password="clave-larga-1", role=User.Role.CONSULTA
        )
        self.assertEqual(
            authenticate(username="lector@example.com", password="clave-larga-1"), consulta
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "lector@example.com", "password": "clave-larga-1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/cuenta/login/", response["Location"])
        self.assertEqual(int(self.client.session["_auth_user_id"]), consulta.pk)

    def test_consulta_con_clave_incorrecta_no_entra(self):
        User.objects.create_user(
            email="lector@example.com", password="clave-larga-1", role=User.Role.CONSULTA
        )
        self.assertIsNone(authenticate(username="lector@example.com", password="otra"))

    def test_admin_y_enlace_fuera_de_la_lista_siguen_rechazados(self):
        """#35 AC-4 — ADMIN/ENLACE fuera de AUTHORIZED_EMAILS siguen sin entrar."""
        for rol, correo in [
            (User.Role.ADMIN, "adm@example.com"),
            (User.Role.ENLACE, "enl@example.com"),
        ]:
            User.objects.create_user(email=correo, password="clave-larga-1", role=rol)
            self.assertIsNone(authenticate(username=correo, password="clave-larga-1"))
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "enl@example.com", "password": "clave-larga-1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_consulta_inactivo_no_entra(self):
        """#35 AC-5 — un Consulta con is_active=False no se autentica."""
        User.objects.create_user(
            email="lector@example.com", password="clave-larga-1",
            role=User.Role.CONSULTA, is_active=False,
        )
        self.assertIsNone(authenticate(username="lector@example.com", password="clave-larga-1"))


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE, AUTHORIZED_EMAILS=["admin@example.com"])
class ConsultaUsuarioAdminTests(TestCase):
    """Gestión de usuarios Consulta por un ADMIN."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com", password="x", role=User.Role.ADMIN
        )
        self.client.force_login(self.admin)
        unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        session = self.client.session
        session[SESSION_KEY] = Compania.objects.create(unidad=unidad, nombre="Alcatraz").pk
        session.save()

    def test_admin_crea_usuarios_consulta_sin_tope(self):
        """#35 AC-2 — ADMIN crea usuarios Consulta fuera de la lista, sin tope, y se listan."""
        for i in range(10):
            response = self.client.post(
                reverse("accounts:usuario_crear"),
                {
                    "email": f"lector{i}@example.com", "first_name": "Ana",
                    "last_name": "Ríos", "role": User.Role.CONSULTA,
                    "password": "clave-larga-1", "password_confirmar": "clave-larga-1",
                },
            )
            self.assertRedirects(response, reverse("accounts:usuario_list"))
        self.assertEqual(User.objects.filter(role=User.Role.CONSULTA).count(), 10)
        response = self.client.get(reverse("accounts:usuario_list"))
        self.assertContains(response, "lector9@example.com")
        self.assertContains(response, 'siga-badge--consulta">Consulta<')

    def test_admin_cambia_consulta_a_enlace_y_viceversa(self):
        """#35 AC-12 — ADMIN pasa Consulta↔Enlace; como Enlace fuera de la lista ya no entra."""
        lector = User.objects.create_user(
            email="lector@example.com", password="clave-larga-1", role=User.Role.CONSULTA
        )
        url = reverse("accounts:usuario_editar", args=[lector.pk])
        datos = {"email": lector.email, "first_name": "", "last_name": "", "is_active": "on"}
        self.assertRedirects(
            self.client.post(url, {**datos, "role": User.Role.ENLACE}),
            reverse("accounts:usuario_list"),
        )
        lector.refresh_from_db()
        self.assertEqual(lector.role, User.Role.ENLACE)
        self.assertIsNone(authenticate(username="lector@example.com", password="clave-larga-1"))

        self.client.post(url, {**datos, "role": User.Role.CONSULTA})
        lector.refresh_from_db()
        self.assertEqual(lector.role, User.Role.CONSULTA)
        self.assertIsNotNone(
            authenticate(username="lector@example.com", password="clave-larga-1")
        )

    def test_admin_no_puede_pasarse_a_consulta(self):
        """#35 AC-12 — sigue vigente que un ADMIN no se quita a sí mismo el rol."""
        response = self.client.post(
            reverse("accounts:usuario_editar", args=[self.admin.pk]),
            {"email": self.admin.email, "first_name": "", "last_name": "",
             "role": User.Role.CONSULTA, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMIN)

    def test_enlace_no_puede_crear_usuarios(self):
        """#35 — crear cuentas (la barrera de entrada de Consulta) es solo ADMIN."""
        compania_id = self.client.session[SESSION_KEY]
        enlace = User.objects.create_user(email="enl@example.com", password="x")
        self.client.force_login(enlace)
        session = self.client.session
        session[SESSION_KEY] = compania_id
        session.save()
        response = self.client.post(
            reverse("accounts:usuario_crear"),
            {"email": "x@example.com", "role": User.Role.CONSULTA,
             "password": "clave-larga-1", "password_confirmar": "clave-larga-1"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email="x@example.com").exists())


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class ConsultaPermisosTests(TestCase):
    """Un usuario Consulta ve todo y no ejecuta ninguna acción."""

    def setUp(self):
        unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=unidad, nombre="Alcatraz")
        self.comp_b = Compania.objects.create(unidad=unidad, nombre="Bisonte")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.fusil = TipoArmamento.objects.create(
            nombre="FUSIL GALIL", control=TipoArmamento.Control.SERIE
        )
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION 5.56", control=TipoArmamento.Control.CANTIDAD
        )
        peloton = Peloton.objects.create(compania=self.comp_a, nombre="A 1")
        self.soldado = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.comp_a, peloton=peloton
        )
        self.operador = User.objects.create_user(
            email="enlace@example.com", password="x", role=User.Role.ENLACE
        )
        # Arma en depósito (entregar/prestar), en mano (devolver) y prestada.
        self.arma = self._arma("S-1")
        self.arma_mano = self._arma("S-2")
        self.arma_mano.entregar(soldado=self.soldado, usuario=self.operador)
        self.arma_prestada = self._arma("S-3")
        self.arma_prestada.prestar(compania=self.comp_b, usuario=self.operador)
        # Consumo: existencia, asignada a un soldado, y un préstamo pendiente.
        self.existencia = Existencia.objects.create(
            tipo=self.municion, compania=self.comp_a, deposito=self.deposito,
            lote="L-1", cantidad=100,
        )
        self.existencia.entregar(soldado=self.soldado, cantidad=10, usuario=self.operador)
        self.asignada = ExistenciaAsignada.objects.get(existencia=self.existencia)
        self.prestamo = Prestamo(
            tipo=self.municion, deposito=self.deposito, lote="L-1", cantidad=20,
            compania_origen=self.comp_a, compania_destino=self.comp_b, usuario=self.operador,
        )
        self.prestamo.full_clean()
        self.prestamo.save()

        self.consulta = User.objects.create_user(
            email="lector@example.com", password="x", role=User.Role.CONSULTA
        )
        self._entrar(self.consulta)

    def _arma(self, serie):
        return Armamento.objects.create(
            numero_serie=serie, tipo=self.fusil, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )

    def _entrar(self, usuario):
        self.client.force_login(usuario)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def _conteos(self):
        return (
            Movimiento.objects.count(), MovimientoExistencia.objects.count(),
            Prestamo.objects.count(), DevolucionPrestamo.objects.count(),
        )

    def _acciones(self):
        return [
            (reverse("inventory:armamento_entregar", args=[self.arma.pk]),
             {"soldado": self.soldado.pk}),
            (reverse("inventory:armamento_devolver", args=[self.arma_mano.pk]),
             {"deposito": self.deposito.pk}),
            (reverse("inventory:armamento_prestar", args=[self.arma.pk]),
             {"compania": self.comp_b.pk}),
            (reverse("inventory:armamento_devolver_prestamo", args=[self.arma_prestada.pk]),
             {}),
            (reverse("inventory:existencia_entregar", args=[self.existencia.pk]),
             {"soldado": self.soldado.pk, "cantidad": "5"}),
            (reverse("inventory:existencia_devolver", args=[self.asignada.pk]),
             {"cantidad": "5", "deposito": self.deposito.pk}),
            (reverse("inventory:prestamo_transferir"),
             {"tipo": self.municion.pk, "deposito": self.deposito.pk,
              "compania_origen": self.comp_a.pk, "compania_destino": self.comp_b.pk,
              "lote": "L-1", "cantidad": "5"}),
            (reverse("inventory:prestamo_devolver", args=[self.prestamo.pk]),
             {"cantidad": "5"}),
        ]

    def test_consulta_ve_pantallas_de_lectura(self):
        """#35 AC-6 — Consulta recibe 200 en todas las pantallas de lectura."""
        urls = [
            reverse("inventory:armamento_list"),
            reverse("inventory:armamento_detalle", args=[self.arma.pk]),
            reverse("inventory:movimiento_list"),
            reverse("inventory:soldado_list"),
            reverse("inventory:soldado_detalle", args=[self.soldado.pk]),
            reverse("inventory:existencia_list"),
            reverse("inventory:existencia_asignada_list"),
            reverse("inventory:prestamo_list"),
            reverse("inventory:elegir_compania"),
            reverse("inventory:ajustes"),
            reverse("inventory:compania_list"),
            reverse("accounts:cuenta"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(
            reverse("inventory:elegir_compania"), {"compania": self.comp_b.pk}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[SESSION_KEY], self.comp_b.pk)

    def test_consulta_recibe_403_en_acciones_y_no_cambia_nada(self):
        """#35 AC-7 — GET y POST a las 8 vistas de acción dan 403 y no registran nada."""
        antes = self._conteos()
        for url, datos in self._acciones():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, datos).status_code, 403)
        self.assertEqual(self._conteos(), antes)
        for obj in (self.arma, self.arma_mano, self.arma_prestada, self.existencia,
                    self.asignada, self.prestamo):
            obj.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.DEPOSITO)
        self.assertIsNone(self.arma.compania_en_prestamo)
        self.assertEqual(self.arma_mano.soldado, self.soldado)
        self.assertEqual(self.arma_prestada.compania_en_prestamo, self.comp_b)
        self.assertEqual(self.existencia.cantidad, 70)
        self.assertEqual(self.asignada.cantidad, 10)
        self.assertEqual(self.prestamo.cantidad_devuelta, 0)

    def test_las_acciones_siguen_abiertas_para_enlace(self):
        """#35 AC-13 — Enlace sigue pudiendo abrir las vistas de acción."""
        self._entrar(self.operador)
        for url, _datos in self._acciones():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_consulta_recibe_403_en_vistas_admin(self):
        """#35 AC-8 — Consulta recibe 403 en las vistas solo-ADMIN."""
        urls = [
            reverse("inventory:armamento_crear"),
            reverse("inventory:armamento_editar", args=[self.arma.pk]),
            reverse("inventory:armamento_baja", args=[self.arma.pk]),
            reverse("inventory:soldado_crear"),
            reverse("inventory:soldado_editar", args=[self.soldado.pk]),
            reverse("inventory:soldado_borrar", args=[self.soldado.pk]),
            reverse("inventory:existencia_crear"),
            reverse("inventory:existencia_editar", args=[self.existencia.pk]),
            reverse("inventory:existencia_borrar", args=[self.existencia.pk]),
            reverse("inventory:compania_crear"),
            reverse("inventory:compania_editar", args=[self.comp_a.pk]),
            reverse("inventory:compania_borrar", args=[self.comp_a.pk]),
            reverse("accounts:usuario_list"),
            reverse("accounts:usuario_crear"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.assertTrue(Soldado.objects.filter(pk=self.soldado.pk).exists())
        self.assertTrue(Compania.objects.filter(pk=self.comp_a.pk).exists())

    def _enlaces_de_accion(self):
        return {
            reverse("inventory:armamento_detalle", args=[self.arma.pk]): [
                reverse("inventory:armamento_entregar", args=[self.arma.pk]),
                reverse("inventory:armamento_prestar", args=[self.arma.pk]),
            ],
            reverse("inventory:armamento_detalle", args=[self.arma_mano.pk]): [
                reverse("inventory:armamento_devolver", args=[self.arma_mano.pk]),
            ],
            reverse("inventory:armamento_detalle", args=[self.arma_prestada.pk]): [
                reverse("inventory:armamento_devolver_prestamo", args=[self.arma_prestada.pk]),
            ],
            reverse("inventory:existencia_list") + "?todas=1": [
                reverse("inventory:existencia_entregar", args=[self.existencia.pk]),
                reverse("inventory:prestamo_devolver", args=[self.prestamo.pk]),
            ],
            reverse("inventory:existencia_asignada_list"): [
                reverse("inventory:existencia_devolver", args=[self.asignada.pk]),
            ],
            reverse("inventory:soldado_detalle", args=[self.soldado.pk]): [
                reverse("inventory:armamento_devolver", args=[self.arma_mano.pk]),
                reverse("inventory:existencia_devolver", args=[self.asignada.pk]),
            ],
            reverse("inventory:prestamo_list") + "?todas=1": [
                reverse("inventory:prestamo_transferir"),
                reverse("inventory:prestamo_devolver", args=[self.prestamo.pk]),
            ],
        }

    def test_consulta_no_ve_botones_de_accion(self):
        """#35 AC-9 — el HTML de Consulta no trae enlaces de acción ni "+ Añadir"."""
        for pagina, enlaces in self._enlaces_de_accion().items():
            response = self.client.get(pagina)
            for enlace in enlaces:
                with self.subTest(pagina=pagina, enlace=enlace):
                    self.assertNotContains(response, f'href="{enlace}')
            self.assertNotContains(response, "+ Añadir")
        for pagina in [reverse("inventory:armamento_list"), reverse("inventory:soldado_list")]:
            self.assertNotContains(self.client.get(pagina), "+ Añadir")

    def test_enlace_si_ve_botones_de_accion(self):
        """#35 AC-9 — para un Enlace los mismos enlaces de movimiento siguen apareciendo."""
        self._entrar(self.operador)
        for pagina, enlaces in self._enlaces_de_accion().items():
            response = self.client.get(pagina)
            for enlace in enlaces:
                with self.subTest(pagina=pagina, enlace=enlace):
                    self.assertContains(response, f'href="{enlace}')

    def test_sidebar_muestra_rol_consulta(self):
        """#35 AC-10 — el sidebar muestra el rol "Consulta"."""
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(
            response, '<span class="siga-sidebar__user-role">Consulta</span>', html=False
        )

    def test_consulta_cambia_su_propia_contrasena(self):
        """#35 AC-11 — Consulta puede cambiar su propia contraseña."""
        self.consulta.set_password("vieja-clave-1")
        self.consulta.save()
        self._entrar(self.consulta)
        response = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": "vieja-clave-1", "new_password1": "Nueva-clave-larga-9",
             "new_password2": "Nueva-clave-larga-9"},
        )
        self.assertRedirects(response, reverse("accounts:password_change_done"))
        self.consulta.refresh_from_db()
        self.assertTrue(self.consulta.check_password("Nueva-clave-larga-9"))
