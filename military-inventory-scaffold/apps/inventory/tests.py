from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from .models import Armamento, Compania, Deposito, Soldado, TipoArmamento, Unidad


class SeedCommandTests(TestCase):
    def test_seed_is_idempotent_and_creates_master_data(self):
        call_command("seed_initial")
        call_command("seed_initial")  # segunda vez no duplica
        self.assertEqual(Unidad.objects.count(), 1)
        self.assertEqual(Compania.objects.count(), 7)
        self.assertEqual(Deposito.objects.count(), 2)
        self.assertEqual(TipoArmamento.objects.count(), 23)


class ArmamentoRulesTests(TestCase):
    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(nombre="FUSIL AR CAL. 5.56 MM")
        self.soldado_a = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.comp_a
        )

    def test_arma_en_deposito_requiere_deposito(self):
        arma = Armamento(
            numero_serie="S-001", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=None,
        )
        with self.assertRaises(ValidationError):
            arma.full_clean()

    def test_soldado_debe_ser_de_la_misma_compania(self):
        soldado_b = Soldado.objects.create(apellidos_nombres="Gómez Ana", compania=self.comp_b)
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
