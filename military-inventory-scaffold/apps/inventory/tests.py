import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Armamento,
    Compania,
    Deposito,
    Existencia,
    Movimiento,
    Peloton,
    Prestamo,
    Soldado,
    TipoArmamento,
    UnicodeJSONEncoder,
    Unidad,
)
from .views import SESSION_KEY

# Los tests que renderizan una página completa del admin usan almacenamiento
# de estáticos simple: el manifest de whitenoise solo existe tras
# `collectstatic`, que no corre como parte de la suite.
_PLAIN_STATIC_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class SeedCommandTests(TestCase):
    def test_seed_is_idempotent_and_creates_master_data(self):
        call_command("seed_initial")
        call_command("seed_initial")  # segunda vez no duplica
        self.assertEqual(Unidad.objects.count(), 1)
        self.assertEqual(Compania.objects.count(), 7)
        self.assertEqual(Deposito.objects.count(), 2)
        self.assertEqual(Peloton.objects.count(), 28)  # 4 por compañía x 7
        self.assertEqual(TipoArmamento.objects.count(), 24)

    def test_seed_marks_control_por_serie_y_cantidad(self):
        call_command("seed_initial")
        fusil = TipoArmamento.objects.get(nombre="FUSIL AR CAL. 5.56 MM")
        municion = TipoArmamento.objects.get(nombre="MUNICION CAL 5.56MM")
        self.assertEqual(fusil.control, TipoArmamento.Control.SERIE)
        self.assertEqual(municion.control, TipoArmamento.Control.CANTIDAD)


class ArmamentoRulesTests(TestCase):
    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.peloton_a1 = Peloton.objects.create(compania=self.comp_a, nombre="A 1")
        self.peloton_b1 = Peloton.objects.create(compania=self.comp_b, nombre="B 1")
        self.soldado_a = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.comp_a, peloton=self.peloton_a1
        )

    def test_arma_en_deposito_requiere_deposito(self):
        arma = Armamento(
            numero_serie="S-001", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=None,
        )
        with self.assertRaises(ValidationError):
            arma.full_clean()

    def test_soldado_debe_ser_de_la_misma_compania(self):
        soldado_b = Soldado.objects.create(
            apellidos_nombres="Gómez Ana", compania=self.comp_b, peloton=self.peloton_b1
        )
        arma = Armamento(
            numero_serie="S-002", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.EN_MANO, soldado=soldado_b,
        )
        with self.assertRaises(ValidationError):
            arma.full_clean()

    def test_ubicacion_actual_en_mano(self):
        arma = Armamento.objects.create(
            numero_serie="S-003", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.EN_MANO, soldado=self.soldado_a,
        )
        self.assertIn("En mano", arma.ubicacion_actual)
        self.assertIn("Pérez Juan", arma.ubicacion_actual)

    def test_tipo_por_cantidad_rechazado_en_armamento(self):
        municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        arma = Armamento(
            numero_serie="S-004", tipo=municion, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        with self.assertRaises(ValidationError):
            arma.full_clean()

    def test_peloton_actual_derivado_del_soldado(self):
        arma = Armamento.objects.create(
            numero_serie="S-005", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.EN_MANO, soldado=self.soldado_a,
        )
        self.assertEqual(arma.peloton_actual, self.peloton_a1)

    def test_peloton_actual_vacio_en_deposito(self):
        arma = Armamento.objects.create(
            numero_serie="S-006", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        self.assertIsNone(arma.peloton_actual)


class PelotonRulesTests(TestCase):
    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.peloton_b1 = Peloton.objects.create(compania=self.comp_b, nombre="B 1")

    def test_soldado_requiere_peloton_de_su_propia_compania(self):
        soldado = Soldado(
            apellidos_nombres="Ríos Carlos", compania=self.comp_a, peloton=self.peloton_b1
        )
        with self.assertRaises(ValidationError):
            soldado.full_clean()


class ExistenciaPrestamoTests(TestCase):
    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        self.fusil = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.existencia_a = Existencia.objects.create(
            tipo=self.municion, compania=self.comp_a, deposito=self.deposito,
            lote="L-001", cantidad=100,
        )
        self.usuario = get_user_model().objects.create_user(
            email="enlace@example.com", password="x"
        )

    def test_existencia_requiere_tipo_por_cantidad(self):
        existencia = Existencia(
            tipo=self.fusil, compania=self.comp_a, deposito=self.deposito, cantidad=5,
        )
        with self.assertRaises(ValidationError):
            existencia.full_clean()

    def test_prestamo_transfiere_cantidad_entre_companias(self):
        prestamo = Prestamo(
            tipo=self.municion, deposito=self.deposito, lote="L-001", cantidad=30,
            compania_origen=self.comp_a, compania_destino=self.comp_b, usuario=self.usuario,
        )
        prestamo.full_clean()
        prestamo.save()

        self.existencia_a.refresh_from_db()
        self.assertEqual(self.existencia_a.cantidad, 70)

        existencia_b = Existencia.objects.get(
            tipo=self.municion, compania=self.comp_b, deposito=self.deposito, lote="L-001"
        )
        self.assertEqual(existencia_b.cantidad, 30)

    def test_prestamo_cantidad_insuficiente_rechazado(self):
        prestamo = Prestamo(
            tipo=self.municion, deposito=self.deposito, lote="L-001", cantidad=999,
            compania_origen=self.comp_a, compania_destino=self.comp_b, usuario=self.usuario,
        )
        with self.assertRaises(ValidationError):
            prestamo.full_clean()

    def test_prestamo_misma_compania_origen_destino_rechazado(self):
        prestamo = Prestamo(
            tipo=self.municion, deposito=self.deposito, lote="L-001", cantidad=10,
            compania_origen=self.comp_a, compania_destino=self.comp_a, usuario=self.usuario,
        )
        with self.assertRaises(ValidationError):
            prestamo.full_clean()

    def test_prestamo_tipo_por_serie_rechazado(self):
        prestamo = Prestamo(
            tipo=self.fusil, deposito=self.deposito, cantidad=1,
            compania_origen=self.comp_a, compania_destino=self.comp_b, usuario=self.usuario,
        )
        with self.assertRaises(ValidationError):
            prestamo.full_clean()


class PWATests(TestCase):
    def test_manifest_is_served_at_root_with_correct_content_type(self):
        response = self.client.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")

    def test_service_worker_is_served_at_root_scope(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response["Content-Type"])
        self.assertEqual(response["Service-Worker-Allowed"], "/")


class EntregaDevolucionTests(TestCase):
    """Armamento.entregar()/devolver() — flujo de movimientos (RF-10, H-09)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.peloton_a1 = Peloton.objects.create(compania=self.comp_a, nombre="A 1")
        self.peloton_b1 = Peloton.objects.create(compania=self.comp_b, nombre="B 1")
        self.soldado_a = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.comp_a, peloton=self.peloton_a1
        )
        self.soldado_b = Soldado.objects.create(
            apellidos_nombres="Gómez Ana", compania=self.comp_b, peloton=self.peloton_b1
        )
        self.usuario = get_user_model().objects.create_user(
            email="enlace@example.com", password="x"
        )
        self.arma = Armamento.objects.create(
            numero_serie="S-100", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )

    def test_entregar_mueve_a_mano_y_crea_movimiento(self):
        movimiento = self.arma.entregar(
            soldado=self.soldado_a, usuario=self.usuario, observacion="ok"
        )
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.EN_MANO)
        self.assertEqual(self.arma.soldado, self.soldado_a)
        self.assertIsNone(self.arma.deposito)
        self.assertEqual(movimiento.tipo, Movimiento.Tipo.ENTREGA)
        self.assertEqual(movimiento.armamento, self.arma)
        self.assertEqual(movimiento.usuario, self.usuario)

    def test_entregar_rechaza_soldado_de_otra_compania(self):
        with self.assertRaises(ValidationError):
            self.arma.entregar(soldado=self.soldado_b, usuario=self.usuario)

    def test_entregar_rechaza_arma_que_no_esta_en_deposito(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.usuario)
        with self.assertRaises(ValidationError):
            self.arma.entregar(soldado=self.soldado_a, usuario=self.usuario)

    def test_devolver_mueve_a_deposito_y_crea_movimiento(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.usuario)
        movimiento = self.arma.devolver(deposito=self.deposito, usuario=self.usuario)
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.DEPOSITO)
        self.assertIsNone(self.arma.soldado)
        self.assertEqual(self.arma.deposito, self.deposito)
        self.assertEqual(movimiento.tipo, Movimiento.Tipo.DEVOLUCION)

    def test_devolver_rechaza_arma_que_no_esta_en_mano(self):
        with self.assertRaises(ValidationError):
            self.arma.devolver(deposito=self.deposito, usuario=self.usuario)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class ArmamentoMovimientoAdminViewTests(TestCase):
    """Flujo de entrega/devolución expuesto como acciones del admin (H-09)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.peloton_a1 = Peloton.objects.create(compania=self.comp_a, nombre="A 1")
        self.soldado_a = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.comp_a, peloton=self.peloton_a1
        )
        self.arma = Armamento.objects.create(
            numero_serie="S-200", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        self.admin_user = get_user_model().objects.create_superuser(
            email="admin@example.com", password="x"
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def test_entregar_view_confirms_and_creates_movimiento(self):
        url = reverse("admin:inventory_armamento_entregar")
        response = self.client.get(url, {"ids": str(self.arma.pk)})
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            url, {"ids": str(self.arma.pk), "soldado": self.soldado_a.pk, "observacion": ""}
        )
        self.assertRedirects(response, reverse("admin:inventory_armamento_changelist"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.EN_MANO)
        self.assertEqual(self.arma.soldado, self.soldado_a)
        self.assertTrue(
            Movimiento.objects.filter(armamento=self.arma, tipo=Movimiento.Tipo.ENTREGA).exists()
        )

    def test_devolver_view_confirms_and_creates_movimiento(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        url = reverse("admin:inventory_armamento_devolver")
        response = self.client.get(url, {"ids": str(self.arma.pk)})
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            url, {"ids": str(self.arma.pk), "deposito": self.deposito.pk, "observacion": ""}
        )
        self.assertRedirects(response, reverse("admin:inventory_armamento_changelist"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.DEPOSITO)
        self.assertIsNone(self.arma.soldado)
        self.assertTrue(
            Movimiento.objects.filter(
                armamento=self.arma, tipo=Movimiento.Tipo.DEVOLUCION
            ).exists()
        )


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class CompaniaContextoTests(TestCase):
    """Selección de compañía de trabajo (RF-02, H-08)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        Armamento.objects.create(
            numero_serie="S-A1", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        Armamento.objects.create(
            numero_serie="S-B1", tipo=self.tipo, compania=self.comp_b,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        self.admin_user = get_user_model().objects.create_superuser(
            email="admin@example.com", password="x"
        )
        self.client.force_login(self.admin_user)

    def test_sin_compania_en_sesion_redirige_al_selector(self):
        response = self.client.get(reverse("admin:index"))
        self.assertRedirects(response, "/compania/?next=/", fetch_redirect_response=False)

    def test_selector_esta_exento_de_su_propio_redirect(self):
        response = self.client.get(reverse("inventory:elegir_compania"))
        self.assertEqual(response.status_code, 200)

    def test_elegir_compania_guarda_en_sesion_y_redirige(self):
        response = self.client.post(
            reverse("inventory:elegir_compania"),
            {"compania": self.comp_a.pk, "next": reverse("admin:index")},
        )
        self.assertRedirects(response, reverse("admin:index"))
        self.assertEqual(self.client.session[SESSION_KEY], self.comp_a.pk)

        # ya no redirige a partir de aquí en la misma sesión.
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)

    def test_changelist_filtra_por_defecto_a_la_compania_en_sesion(self):
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        response = self.client.get(reverse("admin:inventory_armamento_changelist"))
        self.assertContains(response, "S-A1")
        self.assertNotContains(response, "S-B1")

    def test_filtro_explicito_de_compania_anula_el_contexto_por_defecto(self):
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        response = self.client.get(
            reverse("admin:inventory_armamento_changelist"), {"compania__id__exact": self.comp_b.pk}
        )
        self.assertContains(response, "S-B1")
        self.assertNotContains(response, "S-A1")

    def test_ver_todas_companias_anula_el_contexto_por_defecto(self):
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        response = self.client.get(
            reverse("admin:inventory_armamento_changelist"), {"ver_todas_companias": "1"}
        )
        self.assertContains(response, "S-A1")
        self.assertContains(response, "S-B1")

    def test_boton_cambiar_compania_aparece_en_el_admin(self):
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "cambiar compañía")
        self.assertContains(response, "Compañía:")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class BusquedaGlobalArmamentoTests(TestCase):
    """Búsqueda global por cualquier dato del armamento (RF-12, H-11)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="Bisonte")
        self.deposito_apiay = Deposito.objects.create(nombre="Apiay")
        self.deposito_caruru = Deposito.objects.create(nombre="Caruru")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.arma_a = Armamento.objects.create(
            numero_serie="ALC-0001", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito_apiay,
            datos_extra={"observacion_mantenimiento": "óptica reemplazada"},
        )
        Armamento.objects.create(
            numero_serie="BIS-0001", tipo=self.tipo, compania=self.comp_b,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito_caruru,
        )
        self.admin_user = get_user_model().objects.create_superuser(
            email="admin@example.com", password="x"
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def _buscar(self, termino):
        return self.client.get(
            reverse("admin:inventory_armamento_changelist"),
            {"q": termino, "ver_todas_companias": "1"},
        )

    def test_busca_por_numero_de_serie(self):
        response = self._buscar("ALC-0001")
        self.assertContains(response, "ALC-0001")
        self.assertNotContains(response, "BIS-0001")

    def test_busca_por_nombre_de_compania(self):
        response = self._buscar("Bisonte")
        self.assertContains(response, "BIS-0001")
        self.assertNotContains(response, "ALC-0001")

    def test_busca_por_nombre_de_deposito(self):
        response = self._buscar("Caruru")
        self.assertContains(response, "BIS-0001")
        self.assertNotContains(response, "ALC-0001")

    def test_busca_por_campo_personalizado(self):
        response = self._buscar("óptica reemplazada")
        self.assertContains(response, "ALC-0001")
        self.assertNotContains(response, "BIS-0001")

    def test_resultado_muestra_estado_completo_del_arma(self):
        response = self._buscar("ALC-0001")
        content = response.content.decode()
        self.assertIn("ALC-0001", content)
        self.assertIn("Alcatraz", content)
        self.assertIn("FUSIL AR CAL. 5.56 MM", content)
        self.assertIn("En depósito", content)
        self.assertIn("Apiay", content)

    def test_encoder_no_escapa_acentos(self):
        """`icontains` sobre datos_extra solo encuentra texto con tildes si el
        JSON serializado no los escapa como \\uXXXX (UnicodeJSONEncoder);
        json.dumps con ensure_ascii=True, el valor por defecto, sí lo haría."""
        encoded = json.dumps({"obs": "óptica"}, cls=UnicodeJSONEncoder)
        self.assertIn("óptica", encoded)
        self.assertNotIn("\\u00f3", encoded)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class RolePermissionsTests(TestCase):
    """Permisos por rol en la interfaz (RF-01, RF-10, H-03)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="Alcatraz 1")
        self.soldado = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.compania, peloton=self.peloton
        )
        self.arma = Armamento.objects.create(
            numero_serie="S-900", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        Existencia.objects.create(
            tipo=self.municion, compania=self.compania, deposito=self.deposito, cantidad=100
        )

        user_model = get_user_model()
        self.enlace = user_model.objects.create_user(email="enlace@example.com", password="x")
        self.admin_no_super = user_model.objects.create_user(
            email="jefe@example.com", password="x", role=user_model.Role.ADMIN
        )

    def _login_con_compania(self, user):
        self.client.force_login(user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    # --- Enlace: nunca puede crear/editar/borrar datos maestros ---

    def test_enlace_no_puede_agregar_datos_maestros(self):
        self._login_con_compania(self.enlace)
        for url_name in (
            "admin:inventory_compania_add",
            "admin:inventory_deposito_add",
            "admin:inventory_tipoarmamento_add",
            "admin:inventory_soldado_add",
            "admin:inventory_peloton_add",
            "admin:inventory_campopersonalizado_add",
            "admin:inventory_armamento_add",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 403, url_name)

    def test_enlace_puede_ver_pero_no_modificar_armamento(self):
        self._login_con_compania(self.enlace)
        url = reverse("admin:inventory_armamento_change", args=[self.arma.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)  # detalle de solo lectura

        response = self.client.post(
            url,
            {
                "numero_serie": "HACKEADO", "tipo": self.tipo.pk, "compania": self.compania.pk,
                "ubicacion": Armamento.Ubicacion.DEPOSITO, "deposito": self.deposito.pk,
                "estado": Armamento.Estado.ACTIVO,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.numero_serie, "S-900")

    def test_enlace_no_puede_borrar_compania(self):
        self._login_con_compania(self.enlace)
        url = reverse("admin:inventory_compania_delete", args=[self.compania.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_enlace_si_puede_ver_listados_de_datos_maestros(self):
        self._login_con_compania(self.enlace)
        for url_name in (
            "admin:inventory_compania_changelist",
            "admin:inventory_deposito_changelist",
            "admin:inventory_tipoarmamento_changelist",
            "admin:inventory_soldado_changelist",
            "admin:inventory_armamento_changelist",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)

    def test_enlace_no_puede_ver_ni_gestionar_usuarios(self):
        self._login_con_compania(self.enlace)
        response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("admin:accounts_user_add"))
        self.assertEqual(response.status_code, 403)

    # --- Enlace: sí puede registrar movimientos ---

    def test_enlace_si_puede_entregar_y_devolver(self):
        self._login_con_compania(self.enlace)
        url = reverse("admin:inventory_armamento_entregar")
        response = self.client.post(
            url, {"ids": str(self.arma.pk), "soldado": self.soldado.pk, "observacion": ""}
        )
        self.assertRedirects(response, reverse("admin:inventory_armamento_changelist"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.EN_MANO)

        url = reverse("admin:inventory_armamento_devolver")
        response = self.client.post(
            url, {"ids": str(self.arma.pk), "deposito": self.deposito.pk, "observacion": ""}
        )
        self.assertRedirects(response, reverse("admin:inventory_armamento_changelist"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.DEPOSITO)

    def test_enlace_si_puede_registrar_un_prestamo(self):
        self._login_con_compania(self.enlace)
        otra_compania = Compania.objects.create(unidad=self.unidad, nombre="Bisonte")
        response = self.client.post(
            reverse("admin:inventory_prestamo_add"),
            {
                "tipo": self.municion.pk, "deposito": self.deposito.pk, "lote": "",
                "cantidad": 10, "compania_origen": self.compania.pk,
                "compania_destino": otra_compania.pk, "observacion": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Prestamo.objects.filter(compania_destino=otra_compania).exists())

    def test_enlace_no_puede_modificar_un_prestamo_existente(self):
        self._login_con_compania(self.enlace)
        otra_compania = Compania.objects.create(unidad=self.unidad, nombre="Córsega")
        prestamo = Prestamo.objects.create(
            tipo=self.municion, deposito=self.deposito, cantidad=5,
            compania_origen=self.compania, compania_destino=otra_compania,
            usuario=self.admin_no_super,
        )
        url = reverse("admin:inventory_prestamo_change", args=[prestamo.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)  # detalle de solo lectura

        response = self.client.post(
            url,
            {
                "tipo": self.municion.pk, "deposito": self.deposito.pk, "lote": "",
                "cantidad": 999, "compania_origen": self.compania.pk,
                "compania_destino": otra_compania.pk, "observacion": "",
            },
        )
        self.assertEqual(response.status_code, 403)

    # --- Administrador (sin ser superusuario) conserva control total ---

    def test_administrador_no_superusuario_puede_gestionar_datos_maestros(self):
        self._login_con_compania(self.admin_no_super)
        response = self.client.get(reverse("admin:inventory_compania_add"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("admin:inventory_compania_add"),
            {"unidad": self.unidad.pk, "nombre": "Delta"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Compania.objects.filter(nombre="Delta").exists())

    def test_administrador_no_superusuario_puede_ver_y_gestionar_usuarios(self):
        self._login_con_compania(self.admin_no_super)
        response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertEqual(response.status_code, 200)
