from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from .models import (
    Armamento,
    Compania,
    Deposito,
    Existencia,
    Peloton,
    Prestamo,
    Soldado,
    TipoArmamento,
    Unidad,
)


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
