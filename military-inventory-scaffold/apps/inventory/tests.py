import json
import os
import re
import tempfile
from datetime import date, timedelta

import openpyxl
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Armamento,
    CampoPersonalizado,
    Compania,
    Deposito,
    Existencia,
    ExistenciaAsignada,
    Movimiento,
    MovimientoExistencia,
    Peloton,
    Prestamo,
    Soldado,
    TipoArmamento,
    UnicodeJSONEncoder,
    Unidad,
)
from .views import SESSION_KEY, SESSION_KEY_DEPOSITO

# Los tests que renderizan una página completa del admin usan almacenamiento
# de estáticos simple: el manifest de whitenoise solo existe tras
# `collectstatic`, que no corre como parte de la suite.
_PLAIN_STATIC_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _crear_excel(hojas):
    """hojas: {nombre_hoja: [[fila...], ...]}, primera fila = encabezados.
    Devuelve la ruta de un archivo .xlsx temporal (quien llama lo borra)."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for nombre, filas in hojas.items():
        hoja = workbook.create_sheet(title=nombre)
        for fila in filas:
            hoja.append(fila)
    archivo_temporal = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    workbook.save(archivo_temporal.name)
    archivo_temporal.close()
    return archivo_temporal.name


class SeedCommandTests(TestCase):
    def test_seed_is_idempotent_and_creates_master_data(self):
        call_command("seed_initial")
        call_command("seed_initial")  # segunda vez no duplica
        self.assertEqual(Unidad.objects.count(), 1)
        self.assertEqual(Compania.objects.count(), 7)
        self.assertEqual(Deposito.objects.count(), 2)
        self.assertEqual(Peloton.objects.count(), 28)  # 4 por compañía x 7
        self.assertEqual(TipoArmamento.objects.count(), 55)

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

    def test_baja_exige_motivo_y_fecha(self):
        arma = Armamento(
            numero_serie="S-007", tipo=self.tipo, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
            estado=Armamento.Estado.BAJA,
        )
        with self.assertRaises(ValidationError):
            arma.full_clean()


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


class GradoSoldadoTests(TestCase):
    """`Soldado.grado`/`nombre_con_grado` (RF-19, issue #13) — campo fijo
    opcional, el prefijo antepuesto en todo el sistema."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="A 1")

    def test_nombre_con_grado_antepone_la_abreviatura(self):
        soldado = Soldado.objects.create(
            apellidos_nombres="Bolaños Gómez David",
            grado=Soldado.Grado.CT,
            compania=self.compania,
            peloton=self.peloton,
        )
        self.assertEqual(soldado.nombre_con_grado, "CT Bolaños Gómez David")
        self.assertIn("CT Bolaños Gómez David", str(soldado))

    def test_nombre_con_grado_sin_grado_muestra_solo_el_nombre(self):
        soldado = Soldado.objects.create(
            apellidos_nombres="Ríos Carlos", compania=self.compania, peloton=self.peloton
        )
        self.assertEqual(soldado.nombre_con_grado, "Ríos Carlos")

    def test_grado_es_opcional(self):
        soldado = Soldado(
            apellidos_nombres="Ríos Carlos", compania=self.compania, peloton=self.peloton
        )
        soldado.full_clean()  # no debe reventar sin grado


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class SoldadoFormGradoTests(TestCase):
    """El formulario de alta/edición de soldado guarda el grado elegido
    (issue #13) — selector agrupado por categoría, solo se guarda la
    abreviatura."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="A 1")
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def test_crear_soldado_con_grado(self):
        response = self.client.post(
            reverse("inventory:soldado_crear"),
            {
                "apellidos_nombres": "Bolaños Gómez David",
                "cedula": "1000001",
                "grado": Soldado.Grado.CT,
                "compania": self.compania.pk,
                "peloton": self.peloton.pk,
            },
        )
        self.assertRedirects(response, reverse("inventory:soldado_list"))
        soldado = Soldado.objects.get(apellidos_nombres="Bolaños Gómez David")
        self.assertEqual(soldado.grado, Soldado.Grado.CT)

    def test_crear_soldado_sin_grado(self):
        response = self.client.post(
            reverse("inventory:soldado_crear"),
            {
                "apellidos_nombres": "Ríos Carlos",
                "cedula": "1000002",
                "grado": "",
                "compania": self.compania.pk,
                "peloton": self.peloton.pk,
            },
        )
        self.assertRedirects(response, reverse("inventory:soldado_list"))
        soldado = Soldado.objects.get(apellidos_nombres="Ríos Carlos")
        self.assertEqual(soldado.grado, "")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class CedulaSoldadoTests(TestCase):
    """Cédula del soldado como identificador (issue #21, RF-21): única,
    solo dígitos, obligatoria en el formulario y buscable."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.otra = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="A 1")
        self.peloton_b = Peloton.objects.create(compania=self.otra, nombre="B 1")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def _datos(self, **extra):
        datos = {
            "apellidos_nombres": "Ríos Carlos",
            "cedula": "1234567",
            "grado": "",
            "compania": self.compania.pk,
            "peloton": self.peloton.pk,
        }
        datos.update(extra)
        return datos

    def test_crear_sin_cedula_no_guarda(self):
        response = self.client.post(reverse("inventory:soldado_crear"), self._datos(cedula=""))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La cédula es obligatoria.")
        self.assertFalse(Soldado.objects.exists())

    def test_cedula_se_normaliza_sin_puntos_ni_espacios(self):
        self.client.post(reverse("inventory:soldado_crear"), self._datos(cedula="1.234 567"))
        self.assertEqual(Soldado.objects.get().cedula, "1234567")

    def test_cedula_con_letras_rechazada(self):
        response = self.client.post(
            reverse("inventory:soldado_crear"), self._datos(cedula="12AB34")
        )
        self.assertContains(response, "La cédula solo puede tener dígitos.")
        self.assertFalse(Soldado.objects.exists())

    def test_cedula_repetida_en_otra_compania_rechazada(self):
        Soldado.objects.create(
            apellidos_nombres="Bolaños Gómez David", grado=Soldado.Grado.CT,
            cedula="1234567", compania=self.otra, peloton=self.peloton_b,
        )
        response = self.client.post(reverse("inventory:soldado_crear"), self._datos())
        self.assertContains(
            response, "Esta cédula ya está registrada para CT Bolaños Gómez David (B)."
        )
        self.assertEqual(Soldado.objects.count(), 1)

    def test_modelo_rechaza_cedula_no_numerica(self):
        soldado = Soldado(
            apellidos_nombres="Ríos Carlos", cedula="12-34",
            compania=self.compania, peloton=self.peloton,
        )
        with self.assertRaises(ValidationError):
            soldado.full_clean()

    def test_soldados_existentes_sin_cedula_conviven(self):
        for nombre in ("Uno", "Dos"):
            Soldado.objects.create(
                apellidos_nombres=nombre, compania=self.compania, peloton=self.peloton
            )
        self.assertEqual(Soldado.objects.filter(cedula__isnull=True).count(), 2)

    def test_editar_soldado_sin_cedula_la_exige(self):
        soldado = Soldado.objects.create(
            apellidos_nombres="Ríos Carlos", compania=self.compania, peloton=self.peloton
        )
        url = reverse("inventory:soldado_editar", args=[soldado.pk])
        response = self.client.post(url, self._datos(cedula=""))
        self.assertContains(response, "La cédula es obligatoria.")
        self.client.post(url, self._datos(cedula="7654321"))
        soldado.refresh_from_db()
        self.assertEqual(soldado.cedula, "7654321")

    def test_editar_conserva_su_propia_cedula(self):
        soldado = Soldado.objects.create(
            apellidos_nombres="Ríos Carlos", cedula="1234567",
            compania=self.compania, peloton=self.peloton,
        )
        response = self.client.post(
            reverse("inventory:soldado_editar", args=[soldado.pk]),
            self._datos(apellidos_nombres="Ríos Pérez Carlos"),
        )
        self.assertRedirects(response, reverse("inventory:soldado_list"))

    def test_buscar_por_cedula_en_soldados_y_al_entregar(self):
        Soldado.objects.create(
            apellidos_nombres="Ríos Carlos", cedula="1234567",
            compania=self.compania, peloton=self.peloton,
        )
        Soldado.objects.create(
            apellidos_nombres="Pérez Juan", cedula="9999999",
            compania=self.compania, peloton=self.peloton,
        )
        arma = Armamento.objects.create(
            numero_serie="S-001", compania=self.compania, deposito=self.deposito,
            tipo=TipoArmamento.objects.create(
                nombre="FUSIL", control=TipoArmamento.Control.SERIE
            ),
        )
        existencia = Existencia.objects.create(
            tipo=TipoArmamento.objects.create(
                nombre="MUNICION 5.56", control=TipoArmamento.Control.CANTIDAD
            ),
            compania=self.compania, deposito=self.deposito, cantidad=100,
        )
        for url in (
            reverse("inventory:soldado_list"),
            reverse("inventory:armamento_entregar", args=[arma.pk]),
            reverse("inventory:existencia_entregar", args=[existencia.pk]),
        ):
            response = self.client.get(url, {"q": "1.234"})
            self.assertContains(response, "Ríos Carlos", msg_prefix=url)
            self.assertNotContains(response, "Pérez Juan", msg_prefix=url)

    def test_ficha_muestra_cedula(self):
        con = Soldado.objects.create(
            apellidos_nombres="Ríos Carlos", cedula="1234567",
            compania=self.compania, peloton=self.peloton,
        )
        sin = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.compania, peloton=self.peloton
        )
        self.assertContains(
            self.client.get(reverse("inventory:soldado_detalle", args=[con.pk])), "C.C. 1234567"
        )
        self.assertContains(
            self.client.get(reverse("inventory:soldado_detalle", args=[sin.pk])), "Sin cédula"
        )

    def _numeros(self, response):
        return re.findall(r'siga-pick-item__num">(\d+)<', response.content.decode())

    def test_listas_de_soldados_numeradas_y_con_cedula(self):
        """Issue #20: cada fila lleva su posición 1…N en la lista que se
        ve (no un identificador) y la cédula del soldado."""
        for i, nombre in enumerate(("Arango", "Bermúdez", "Caro"), start=1):
            Soldado.objects.create(
                apellidos_nombres=nombre, cedula=f"10{i}", compania=self.compania,
                peloton=self.peloton,
            )
        Soldado.objects.create(
            apellidos_nombres="Díaz", compania=self.compania, peloton=self.peloton
        )
        arma = Armamento.objects.create(
            numero_serie="S-001", compania=self.compania, deposito=self.deposito,
            tipo=TipoArmamento.objects.create(nombre="FUSIL", control=TipoArmamento.Control.SERIE),
        )
        existencia = Existencia.objects.create(
            tipo=TipoArmamento.objects.create(
                nombre="MUNICION 5.56", control=TipoArmamento.Control.CANTIDAD
            ),
            compania=self.compania, deposito=self.deposito, cantidad=100,
        )
        for url in (
            reverse("inventory:soldado_list"),
            reverse("inventory:armamento_entregar", args=[arma.pk]),
            reverse("inventory:existencia_entregar", args=[existencia.pk]),
        ):
            response = self.client.get(url)
            self.assertEqual(self._numeros(response), ["1", "2", "3", "4"], url)
            self.assertContains(response, "C.C. 102", msg_prefix=url)
            self.assertContains(response, "Sin cédula", msg_prefix=url)

    def test_numeracion_se_reinicia_al_filtrar_y_al_borrar(self):
        for nombre in ("Arango", "Bermúdez", "Caro"):
            Soldado.objects.create(
                apellidos_nombres=nombre, compania=self.compania, peloton=self.peloton
            )
        url = reverse("inventory:soldado_list")
        self.assertEqual(self._numeros(self.client.get(url, {"q": "Caro"})), ["1"])
        Soldado.objects.get(apellidos_nombres="Bermúdez").delete()
        response = self.client.get(url)
        self.assertEqual(self._numeros(response), ["1", "2"])
        self.assertContains(response, "2 soldados")


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


class EntregaDevolucionExistenciaTests(TestCase):
    """`Existencia.entregar()`/`ExistenciaAsignada.devolver()` — espejo de
    `Armamento.entregar()`/`.devolver()` para material por cantidad
    (RF-18, issue #12)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="B")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
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
        self.existencia = Existencia.objects.create(
            tipo=self.municion, compania=self.comp_a, deposito=self.deposito,
            lote="L-001", cantidad=100,
        )

    def test_entregar_descuenta_existencia_y_crea_asignada(self):
        movimiento = self.existencia.entregar(
            soldado=self.soldado_a, cantidad=30, usuario=self.usuario, observacion="ok"
        )
        self.existencia.refresh_from_db()
        self.assertEqual(self.existencia.cantidad, 70)

        asignada = ExistenciaAsignada.objects.get(
            existencia=self.existencia, soldado=self.soldado_a
        )
        self.assertEqual(asignada.cantidad, 30)
        self.assertEqual(movimiento.tipo, MovimientoExistencia.Tipo.ENTREGA)
        self.assertEqual(movimiento.cantidad, 30)
        self.assertEqual(movimiento.observacion, "ok")

    def test_entregar_acumula_sobre_asignacion_existente(self):
        self.existencia.entregar(soldado=self.soldado_a, cantidad=30, usuario=self.usuario)
        self.existencia.refresh_from_db()
        self.existencia.entregar(soldado=self.soldado_a, cantidad=20, usuario=self.usuario)
        asignada = ExistenciaAsignada.objects.get(
            existencia=self.existencia, soldado=self.soldado_a
        )
        self.assertEqual(asignada.cantidad, 50)
        self.assertEqual(
            ExistenciaAsignada.objects.filter(
                existencia=self.existencia, soldado=self.soldado_a
            ).count(),
            1,
        )

    def test_entregar_rechaza_soldado_de_otra_compania(self):
        with self.assertRaises(ValidationError):
            self.existencia.entregar(soldado=self.soldado_b, cantidad=10, usuario=self.usuario)

    def test_entregar_rechaza_cantidad_insuficiente(self):
        with self.assertRaises(ValidationError):
            self.existencia.entregar(soldado=self.soldado_a, cantidad=999, usuario=self.usuario)

    def test_entregar_rechaza_cantidad_no_positiva(self):
        with self.assertRaises(ValidationError):
            self.existencia.entregar(soldado=self.soldado_a, cantidad=0, usuario=self.usuario)

    def test_devolver_total_repone_existencia_y_borra_asignada(self):
        self.existencia.entregar(soldado=self.soldado_a, cantidad=30, usuario=self.usuario)
        self.existencia.refresh_from_db()
        asignada = ExistenciaAsignada.objects.get(
            existencia=self.existencia, soldado=self.soldado_a
        )
        movimiento = asignada.devolver(cantidad=30, usuario=self.usuario, observacion="listo")
        self.existencia.refresh_from_db()
        self.assertEqual(self.existencia.cantidad, 100)
        self.assertFalse(ExistenciaAsignada.objects.filter(pk=asignada.pk).exists())
        self.assertEqual(movimiento.tipo, MovimientoExistencia.Tipo.DEVOLUCION)
        self.assertEqual(movimiento.observacion, "listo")

    def test_devolver_parcial_deja_saldo_en_mano(self):
        self.existencia.entregar(soldado=self.soldado_a, cantidad=30, usuario=self.usuario)
        self.existencia.refresh_from_db()
        asignada = ExistenciaAsignada.objects.get(
            existencia=self.existencia, soldado=self.soldado_a
        )
        asignada.devolver(cantidad=10, usuario=self.usuario)
        self.existencia.refresh_from_db()
        asignada.refresh_from_db()
        self.assertEqual(self.existencia.cantidad, 80)
        self.assertEqual(asignada.cantidad, 20)

    def test_devolver_rechaza_cantidad_mayor_a_la_asignada(self):
        self.existencia.entregar(soldado=self.soldado_a, cantidad=30, usuario=self.usuario)
        asignada = ExistenciaAsignada.objects.get(
            existencia=self.existencia, soldado=self.soldado_a
        )
        with self.assertRaises(ValidationError):
            asignada.devolver(cantidad=31, usuario=self.usuario)


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

    def test_dar_de_baja_desde_deposito_registra_deposito_en_movimiento(self):
        hoy = date.today()
        movimiento = self.arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.DANO, fecha=hoy, usuario=self.usuario
        )
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.estado, Armamento.Estado.BAJA)
        self.assertEqual(self.arma.motivo_baja, Armamento.MotivoBaja.DANO)
        self.assertEqual(self.arma.fecha_baja, hoy)
        self.assertEqual(movimiento.tipo, Movimiento.Tipo.BAJA)
        self.assertEqual(movimiento.deposito, self.deposito)
        self.assertIsNone(movimiento.soldado)

    def test_dar_de_baja_desde_mano_registra_soldado_en_movimiento(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.usuario)
        movimiento = self.arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.ROBO, fecha=date.today(), usuario=self.usuario
        )
        self.assertEqual(movimiento.soldado, self.soldado_a)
        self.assertIsNone(movimiento.deposito)

    def test_dar_de_baja_dos_veces_rechazada(self):
        self.arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.PERDIDA, fecha=date.today(), usuario=self.usuario
        )
        with self.assertRaises(ValidationError):
            self.arma.dar_de_baja(
                motivo=Armamento.MotivoBaja.PERDIDA, fecha=date.today(), usuario=self.usuario
            )

    def test_no_se_puede_entregar_un_arma_dada_de_baja(self):
        self.arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.DANO, fecha=date.today(), usuario=self.usuario
        )
        with self.assertRaises(ValidationError):
            self.arma.entregar(soldado=self.soldado_a, usuario=self.usuario)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class ArmamentoMovimientoViewTests(TestCase):
    """Flujo de entrega/devolución/baja expuesto por las pantallas propias
    (H-09, H-10) — reemplaza las acciones del admin retirado (ADR-0004)."""

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
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def test_entregar_view_confirms_and_creates_movimiento(self):
        url = reverse("inventory:armamento_entregar", args=[self.arma.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(url, {"soldado": self.soldado_a.pk, "observacion": ""})
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.EN_MANO)
        self.assertEqual(self.arma.soldado, self.soldado_a)
        self.assertTrue(
            Movimiento.objects.filter(armamento=self.arma, tipo=Movimiento.Tipo.ENTREGA).exists()
        )

    def test_devolver_view_confirms_and_creates_movimiento(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        url = reverse("inventory:armamento_devolver", args=[self.arma.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(url, {"deposito": self.deposito.pk, "observacion": ""})
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.DEPOSITO)
        self.assertIsNone(self.arma.soldado)
        self.assertTrue(
            Movimiento.objects.filter(
                armamento=self.arma, tipo=Movimiento.Tipo.DEVOLUCION
            ).exists()
        )

    def test_dar_de_baja_view_confirms_and_creates_movimiento(self):
        url = reverse("inventory:armamento_baja", args=[self.arma.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            url,
            {"motivo": Armamento.MotivoBaja.DANO, "fecha": "2026-01-15", "observacion": ""},
        )
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.estado, Armamento.Estado.BAJA)
        self.assertEqual(self.arma.motivo_baja, Armamento.MotivoBaja.DANO)
        self.assertTrue(
            Movimiento.objects.filter(armamento=self.arma, tipo=Movimiento.Tipo.BAJA).exists()
        )

    def test_enlace_no_puede_dar_de_baja(self):
        enlace = get_user_model().objects.create_user(email="enlace2@example.com", password="x")
        self.client.force_login(enlace)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        url = reverse("inventory:armamento_baja", args=[self.arma.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            url,
            {"motivo": Armamento.MotivoBaja.DANO, "fecha": "2026-01-15", "observacion": ""},
        )
        self.assertEqual(response.status_code, 403)
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.estado, Armamento.Estado.ACTIVO)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class ExistenciaMovimientoViewTests(TestCase):
    """Pantallas propias de entrega/devolución de existencias (RF-18,
    issue #12) — simétricas a `ArmamentoMovimientoViewTests`."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="A")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        self.peloton_a1 = Peloton.objects.create(compania=self.comp_a, nombre="A 1")
        self.soldado_a = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.comp_a, peloton=self.peloton_a1
        )
        self.existencia = Existencia.objects.create(
            tipo=self.municion, compania=self.comp_a, deposito=self.deposito,
            lote="L-001", cantidad=100,
        )
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def test_entregar_view_confirms_and_creates_movimiento(self):
        url = reverse("inventory:existencia_entregar", args=[self.existencia.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            url, {"soldado": self.soldado_a.pk, "cantidad": 30, "observacion": ""}
        )
        self.assertRedirects(response, reverse("inventory:existencia_list"))
        self.existencia.refresh_from_db()
        self.assertEqual(self.existencia.cantidad, 70)
        asignada = ExistenciaAsignada.objects.get(
            existencia=self.existencia, soldado=self.soldado_a
        )
        self.assertEqual(asignada.cantidad, 30)
        self.assertTrue(
            MovimientoExistencia.objects.filter(
                existencia=self.existencia, tipo=MovimientoExistencia.Tipo.ENTREGA
            ).exists()
        )

    def test_entregar_view_rechaza_cantidad_excesiva(self):
        url = reverse("inventory:existencia_entregar", args=[self.existencia.pk])
        response = self.client.post(
            url, {"soldado": self.soldado_a.pk, "cantidad": 999, "observacion": ""}
        )
        self.assertRedirects(response, url)
        self.existencia.refresh_from_db()
        self.assertEqual(self.existencia.cantidad, 100)

    def test_devolver_view_confirms_and_creates_movimiento(self):
        self.existencia.entregar(soldado=self.soldado_a, cantidad=30, usuario=self.admin_user)
        self.existencia.refresh_from_db()
        asignada = ExistenciaAsignada.objects.get(
            existencia=self.existencia, soldado=self.soldado_a
        )
        url = reverse("inventory:existencia_devolver", args=[asignada.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(url, {"cantidad": 30, "observacion": ""})
        self.assertRedirects(response, reverse("inventory:existencia_asignada_list"))
        self.existencia.refresh_from_db()
        self.assertEqual(self.existencia.cantidad, 100)
        self.assertFalse(ExistenciaAsignada.objects.filter(pk=asignada.pk).exists())
        self.assertTrue(
            MovimientoExistencia.objects.filter(
                existencia=self.existencia, tipo=MovimientoExistencia.Tipo.DEVOLUCION
            ).exists()
        )

    def test_enlace_puede_entregar_y_devolver(self):
        """RF-18, igual que RF-10: ambos roles registran movimientos."""
        enlace = get_user_model().objects.create_user(email="enlace3@example.com", password="x")
        self.client.force_login(enlace)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        url = reverse("inventory:existencia_entregar", args=[self.existencia.pk])
        response = self.client.post(
            url, {"soldado": self.soldado_a.pk, "cantidad": 10, "observacion": ""}
        )
        self.assertRedirects(response, reverse("inventory:existencia_list"))
        self.assertEqual(response.status_code, 302)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class CamposPersonalizadosViewTests(TestCase):
    """Captura de campos personalizados en `armamento_editar` (RF-08, H-12)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.campo_texto = CampoPersonalizado.objects.create(
            nombre="Óptica instalada", tipo=CampoPersonalizado.Tipo.TEXTO
        )
        self.campo_numero = CampoPersonalizado.objects.create(
            nombre="Horas de uso", tipo=CampoPersonalizado.Tipo.NUMERO
        )
        self.campo_fecha = CampoPersonalizado.objects.create(
            nombre="Último mantenimiento", tipo=CampoPersonalizado.Tipo.FECHA
        )
        self.arma = Armamento.objects.create(
            numero_serie="S-500", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def _form_data(self, **overrides):
        data = {
            "numero_serie": self.arma.numero_serie,
            "tipo": self.tipo.pk,
            f"campo_{self.campo_texto.pk}": "",
            f"campo_{self.campo_numero.pk}": "",
            f"campo_{self.campo_fecha.pk}": "",
        }
        data.update(overrides)
        return data

    def test_campos_personalizados_aparecen_en_el_formulario(self):
        response = self.client.get(reverse("inventory:armamento_editar", args=[self.arma.pk]))
        content = response.content.decode()
        self.assertIn("Óptica instalada", content)
        self.assertIn("Horas de uso", content)
        self.assertIn("Último mantenimiento", content)
        self.assertNotIn("datos_extra", content)

    def test_guardar_captura_valores_por_tipo_en_datos_extra(self):
        url = reverse("inventory:armamento_editar", args=[self.arma.pk])
        response = self.client.post(url, self._form_data(**{
            f"campo_{self.campo_texto.pk}": "Holográfica",
            f"campo_{self.campo_numero.pk}": "123.5",
            f"campo_{self.campo_fecha.pk}": "2026-01-10",
        }))
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.datos_extra["Óptica instalada"], "Holográfica")
        self.assertEqual(str(self.arma.datos_extra["Horas de uso"]), "123.5")
        self.assertEqual(str(self.arma.datos_extra["Último mantenimiento"]), "2026-01-10")

    def test_valores_existentes_se_precargan_en_el_formulario(self):
        self.arma.datos_extra = {"Óptica instalada": "Réflex"}
        self.arma.save()
        response = self.client.get(reverse("inventory:armamento_editar", args=[self.arma.pk]))
        self.assertContains(response, "Réflex")

    def test_dejar_un_campo_vacio_lo_quita_de_datos_extra(self):
        self.arma.datos_extra = {"Óptica instalada": "Réflex"}
        self.arma.save()
        url = reverse("inventory:armamento_editar", args=[self.arma.pk])
        response = self.client.post(url, self._form_data())
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.arma.refresh_from_db()
        self.assertNotIn("Óptica instalada", self.arma.datos_extra)

    def test_numero_invalido_muestra_error_de_formulario(self):
        url = reverse("inventory:armamento_editar", args=[self.arma.pk])
        response = self.client.post(
            url, self._form_data(**{f"campo_{self.campo_numero.pk}": "no-es-un-numero"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingrese un número.")

    def test_formulario_de_armamento_funciona_sin_campos_personalizados(self):
        CampoPersonalizado.objects.all().delete()
        response = self.client.get(reverse("inventory:armamento_editar", args=[self.arma.pk]))
        self.assertEqual(response.status_code, 200)

    def test_enlace_no_puede_editar_armamento(self):
        """H-03: editar armamento (incluidos los campo_<pk>) es solo ADMIN —
        a diferencia del admin retirado, Enlace ni siquiera ve el formulario
        (ya ve el detalle completo desde la tarjeta de Inventario)."""
        self.arma.datos_extra = {"Óptica instalada": "Réflex"}
        self.arma.save()
        enlace = get_user_model().objects.create_user(email="enlace3@example.com", password="x")
        self.client.force_login(enlace)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

        url = reverse("inventory:armamento_editar", args=[self.arma.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(url, self._form_data(**{
            f"campo_{self.campo_texto.pk}": "Valor colado",
        }))
        self.assertEqual(response.status_code, 403)
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.datos_extra["Óptica instalada"], "Réflex")


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
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)

    def test_sin_compania_en_sesion_redirige_al_selector(self):
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertRedirects(response, "/compania/?next=/", fetch_redirect_response=False)

    def test_selector_esta_exento_de_su_propio_redirect(self):
        response = self.client.get(reverse("inventory:elegir_compania"))
        self.assertEqual(response.status_code, 200)

    def test_elegir_compania_guarda_en_sesion_y_redirige(self):
        response = self.client.post(
            reverse("inventory:elegir_compania"),
            {"compania": self.comp_a.pk, "next": reverse("inventory:ajustes")},
        )
        self.assertRedirects(response, reverse("inventory:ajustes"))
        self.assertEqual(self.client.session[SESSION_KEY], self.comp_a.pk)

        # ya no redirige a partir de aquí en la misma sesión.
        response = self.client.get(reverse("inventory:ajustes"))
        self.assertEqual(response.status_code, 200)

    def test_armamento_list_filtra_por_defecto_a_la_compania_en_sesion(self):
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, "S-A1")
        self.assertNotContains(response, "S-B1")

    def test_ver_todas_anula_el_contexto_por_defecto(self):
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        response = self.client.get(reverse("inventory:armamento_list"), {"todas": "1"})
        self.assertContains(response, "S-A1")
        self.assertContains(response, "S-B1")

    def test_boton_cambiar_compania_aparece_en_el_header(self):
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, reverse("inventory:elegir_compania"))
        self.assertContains(response, self.comp_a.nombre)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class CompanySelectorTests(TestCase):
    """Pantalla independiente de selección de compañía (issue #6)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.alcatraz = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.aspc = Compania.objects.create(unidad=self.unidad, nombre="ASPC")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="ACE-23", control=TipoArmamento.Control.SERIE
        )
        Armamento.objects.create(
            numero_serie="SEL-1", tipo=self.tipo, compania=self.alcatraz,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        Armamento.objects.create(
            numero_serie="SEL-2", tipo=self.tipo, compania=self.alcatraz,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.enlace_user = user_model.objects.create_user(
            email="enlace@example.com", password="x", role=user_model.Role.ENLACE
        )

    def test_tarjeta_muestra_codigo_derivado_y_total(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("inventory:elegir_compania"))
        self.assertContains(response, "ALCATRAZ")
        self.assertContains(response, "Código A · 2 elementos")
        self.assertContains(response, "ASPC")
        self.assertContains(response, "Código ASPC · 0 elementos")

    def test_compania_en_sesion_tiene_tag_reciente(self):
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.alcatraz.pk
        session.save()

        response = self.client.get(reverse("inventory:elegir_compania"))
        content = response.content.decode()
        self.assertIn("siga-compania-card--reciente", content)
        self.assertIn("Reciente", content)

    def test_nueva_compania_visible_solo_para_administrador(self):
        crear_url = reverse("inventory:compania_crear")

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("inventory:elegir_compania"))
        self.assertContains(response, crear_url)

        self.client.force_login(self.enlace_user)
        response = self.client.get(reverse("inventory:elegir_compania"))
        self.assertNotContains(response, crear_url)

    def test_no_hereda_el_sidebar_ni_el_bottom_nav_compartidos(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("inventory:elegir_compania"))
        self.assertNotContains(response, "siga-sidebar__nav")
        self.assertNotContains(response, "siga-bottom-nav")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class InventarioEscritorioTests(TestCase):
    """Layout de escritorio de Inventario: sidebar + KPIs + tabla (issue #3)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="Alcatraz 1")
        self.soldado = Soldado.objects.create(
            apellidos_nombres="Ramírez G.", compania=self.compania, peloton=self.peloton
        )
        self.tipo = TipoArmamento.objects.create(
            nombre="ACE-23", control=TipoArmamento.Control.SERIE
        )
        Armamento.objects.create(
            numero_serie="EN-DEP-1", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        Armamento.objects.create(
            numero_serie="EN-MANO-1", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.EN_MANO, soldado=self.soldado,
        )
        arma_baja = Armamento.objects.create(
            numero_serie="DE-BAJA-1", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )

        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        arma_baja.dar_de_baja(
            motivo=Armamento.MotivoBaja.DANO, fecha=date.today(), usuario=self.admin_user
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def test_kpis_reflejan_el_desglose_por_ubicacion_y_estado(self):
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertEqual(response.context["kpi_total"], 3)
        self.assertEqual(response.context["kpi_en_deposito"], 1)
        self.assertEqual(response.context["kpi_en_mano"], 1)
        self.assertEqual(response.context["kpi_de_baja"], 1)

    def test_kpis_no_cuentan_otra_compania(self):
        otra_compania = Compania.objects.create(unidad=self.unidad, nombre="Bisonte")
        Armamento.objects.create(
            numero_serie="OTRA-COMP", tipo=self.tipo, compania=otra_compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertEqual(response.context["kpi_total"], 3)

    def test_tabla_de_escritorio_muestra_las_mismas_series_que_las_tarjetas(self):
        response = self.client.get(reverse("inventory:armamento_list"))
        content = response.content.decode()
        self.assertIn('class="siga-table-wrap"', content)
        self.assertIn('class="siga-card-list siga-card-list--inventario"', content)
        for serie in ("EN-DEP-1", "EN-MANO-1"):
            msg = f"{serie} debería aparecer en tabla y tarjeta"
            self.assertEqual(content.count(serie), 2, msg)

    def test_sidebar_incluye_administracion_apuntando_a_ajustes(self):
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, 'class="siga-sidebar__nav"')
        self.assertContains(response, reverse("inventory:ajustes"))
        self.assertContains(response, "Administración")

    def test_item_activo_del_sidebar_resalta_inventario(self):
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, "siga-sidebar__link--active")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class ArmamentoDetalleTests(TestCase):
    """Pantalla de detalle del armamento con historial (issue #5)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.apiay = Deposito.objects.create(nombre="Apiay")
        self.caruru = Deposito.objects.create(nombre="Caruru")
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="Alcatraz 1")
        self.soldado1 = Soldado.objects.create(
            apellidos_nombres="Pérez A.", compania=self.compania, peloton=self.peloton
        )
        self.soldado2 = Soldado.objects.create(
            apellidos_nombres="Gómez L.", compania=self.compania, peloton=self.peloton
        )
        self.tipo = TipoArmamento.objects.create(
            nombre="ACE-23", control=TipoArmamento.Control.SERIE
        )
        self.arma = Armamento.objects.create(
            numero_serie="DET-1", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.apiay,
            datos_extra={"Estado físico": "Operativo"},
        )
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.enlace_user = user_model.objects.create_user(
            email="enlace@example.com", password="x", role=user_model.Role.ENLACE
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def test_boton_entregar_cuando_esta_en_deposito(self):
        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        self.assertContains(response, reverse("inventory:armamento_entregar", args=[self.arma.pk]))
        self.assertNotContains(
            response, reverse("inventory:armamento_devolver", args=[self.arma.pk])
        )

    def test_boton_devolver_cuando_esta_en_mano(self):
        self.arma.entregar(soldado=self.soldado1, usuario=self.admin_user)
        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        self.assertContains(response, reverse("inventory:armamento_devolver", args=[self.arma.pk]))
        self.assertNotContains(
            response, reverse("inventory:armamento_entregar", args=[self.arma.pk])
        )

    def test_boton_dar_de_baja_solo_para_administrador(self):
        url = reverse("inventory:armamento_detalle", args=[self.arma.pk])
        baja_url = reverse("inventory:armamento_baja", args=[self.arma.pk])

        response = self.client.get(url)
        self.assertContains(response, baja_url)

        self.client.force_login(self.enlace_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()
        response = self.client.get(url)
        self.assertNotContains(response, baja_url)

    def test_agregar_campo_solo_para_administrador(self):
        url = reverse("inventory:armamento_detalle", args=[self.arma.pk])
        editar_url = reverse("inventory:armamento_editar", args=[self.arma.pk])

        response = self.client.get(url)
        self.assertContains(response, editar_url)

        self.client.force_login(self.enlace_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()
        response = self.client.get(url)
        self.assertNotContains(response, editar_url)

    def test_campos_personalizados_se_muestran(self):
        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        self.assertContains(response, "Estado físico")
        self.assertContains(response, "Operativo")

    def test_historial_mas_reciente_primero_con_origen_encadenado(self):
        self.arma.entregar(soldado=self.soldado1, usuario=self.admin_user)
        self.arma.devolver(deposito=self.caruru, usuario=self.admin_user)
        self.arma.entregar(soldado=self.soldado2, usuario=self.admin_user)

        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        historial = response.context["historial"]

        self.assertEqual(len(historial), 4)
        self.assertEqual(historial[0]["titulo"], "Entrega a soldado")
        self.assertEqual(historial[0]["detalle"], "A Gómez L. · desde Caruru")
        self.assertEqual(historial[1]["titulo"], "Devolución a depósito")
        self.assertEqual(historial[1]["detalle"], "A Caruru · desde Pérez A.")
        self.assertEqual(historial[2]["titulo"], "Entrega a soldado")
        self.assertEqual(historial[2]["detalle"], "A Pérez A.")
        self.assertEqual(historial[3]["titulo"], "Alta en inventario")

    def test_lista_enlaza_al_detalle_no_directo_a_entregar_o_devolver(self):
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        self.assertNotContains(
            response, reverse("inventory:armamento_entregar", args=[self.arma.pk])
        )

    def test_historial_antepone_el_grado_del_soldado(self):
        """RF-19, issue #13: el prefijo de grado llega hasta el historial
        del arma, no solo a las pantallas de Soldados."""
        self.soldado1.grado = Soldado.Grado.CT
        self.soldado1.save()
        self.arma.entregar(soldado=self.soldado1, usuario=self.admin_user)

        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        historial = response.context["historial"]
        self.assertEqual(historial[0]["detalle"], "A CT Pérez A.")

    def test_historial_muestra_la_observacion_de_entrega_y_devolucion(self):
        """Issue #14: `observacion` ya no se pierde — queda separada de
        `detalle` y se renderiza en la página."""
        self.arma.entregar(
            soldado=self.soldado1, usuario=self.admin_user, observacion="Arma inspeccionada"
        )
        self.arma.devolver(
            deposito=self.apiay, usuario=self.admin_user, observacion="Culata reemplazada"
        )

        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        historial = response.context["historial"]
        # [0] = devolución (más reciente), [1] = entrega.
        self.assertEqual(historial[0]["detalle"], "A Apiay · desde Pérez A.")
        self.assertEqual(historial[0]["observacion"], "Culata reemplazada")
        self.assertEqual(historial[1]["detalle"], "A Pérez A.")
        self.assertEqual(historial[1]["observacion"], "Arma inspeccionada")
        self.assertContains(response, "Culata reemplazada")
        self.assertContains(response, "Arma inspeccionada")

    def test_historial_muestra_la_observacion_de_baja_separada_del_detalle(self):
        self.arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.DANO,
            fecha=date.today(),
            usuario=self.admin_user,
            observacion="Culata partida en entrenamiento",
        )
        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        historial = response.context["historial"]
        self.assertEqual(historial[0]["detalle"], "Dada de baja")
        self.assertEqual(historial[0]["observacion"], "Culata partida en entrenamiento")
        self.assertContains(response, "Culata partida en entrenamiento")

    def test_historial_no_muestra_observacion_vacia(self):
        self.arma.entregar(soldado=self.soldado1, usuario=self.admin_user, observacion="")
        response = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        self.assertNotContains(response, "Observación:")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class MovimientoListObservacionTests(TestCase):
    """Issue #14: la lista de Movimientos también muestra la observación,
    no solo el historial del arma."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="Alcatraz 1")
        self.soldado = Soldado.objects.create(
            apellidos_nombres="Pérez A.", compania=self.compania, peloton=self.peloton
        )
        self.tipo = TipoArmamento.objects.create(
            nombre="ACE-23", control=TipoArmamento.Control.SERIE
        )
        self.arma = Armamento.objects.create(
            numero_serie="MOV-1", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def test_lista_muestra_observacion_no_vacia(self):
        self.arma.entregar(
            soldado=self.soldado, usuario=self.admin_user, observacion="Revisar mira"
        )
        response = self.client.get(reverse("inventory:movimiento_list"))
        self.assertContains(response, "Revisar mira")

    def test_lista_no_muestra_nada_cuando_la_observacion_esta_vacia(self):
        self.arma.entregar(soldado=self.soldado, usuario=self.admin_user, observacion="")
        response = self.client.get(reverse("inventory:movimiento_list"))
        self.assertNotContains(response, "Observación:")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class MovimientoListUnificadaTests(TestCase):
    """Issue #16: Movimientos muestra armas, entregas/devoluciones de
    existencias (RF-18) y préstamos entre compañías (RF-15), mezclados por
    fecha, y Munición indica cuánto está en mano y de quién."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="Bisonte")
        self.comp_c = Compania.objects.create(unidad=self.unidad, nombre="Córsega")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        peloton_a = Peloton.objects.create(compania=self.comp_a, nombre="Alcatraz 1")
        peloton_c = Peloton.objects.create(compania=self.comp_c, nombre="Córsega 1")
        self.soldado_a = Soldado.objects.create(
            apellidos_nombres="Rada Pedro", compania=self.comp_a, peloton=peloton_a,
            grado="TE",
        )
        self.soldado_c = Soldado.objects.create(
            apellidos_nombres="Gómez Luis", compania=self.comp_c, peloton=peloton_c
        )
        self.fusil = TipoArmamento.objects.create(
            nombre="FUSIL GALIL", control=TipoArmamento.Control.SERIE
        )
        self.granada = TipoArmamento.objects.create(
            nombre="GRANADA DE MANO", control=TipoArmamento.Control.CANTIDAD
        )
        self.cartucho = TipoArmamento.objects.create(
            nombre="CARTUCHO 5.56", control=TipoArmamento.Control.CANTIDAD
        )
        self.arma = Armamento.objects.create(
            numero_serie="GAL-001", tipo=self.fusil, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        self.granadas_a = Existencia.objects.create(
            tipo=self.granada, compania=self.comp_a, deposito=self.deposito,
            lote="LG-7", cantidad=40,
        )
        self.granadas_c = Existencia.objects.create(
            tipo=self.granada, compania=self.comp_c, deposito=self.deposito, cantidad=10
        )
        self.cartuchos_a = Existencia.objects.create(
            tipo=self.cartucho, compania=self.comp_a, deposito=self.deposito,
            lote="L-1", cantidad=500,
        )
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def _prestar(self, cantidad, origen, destino):
        prestamo = Prestamo(
            tipo=self.cartucho, deposito=self.deposito, lote="L-1", cantidad=cantidad,
            compania_origen=origen, compania_destino=destino, usuario=self.admin_user,
        )
        prestamo.full_clean()
        prestamo.save()
        return prestamo

    def _clases(self, response):
        return [m.clase for m in response.context["movimientos"]]

    def _escalonar_fechas(self):
        """`auto_now_add` puede repetir la misma marca de tiempo entre filas
        creadas seguidas; aquí se fijan fechas distintas en el orden en que
        cada test crea los registros (armas, luego munición, luego préstamos;
        dentro de cada modelo, por pk)."""
        base = timezone.now() - timedelta(days=1)
        paso = 0
        for modelo in (Movimiento, MovimientoExistencia, Prestamo):
            for pk in modelo.objects.order_by("pk").values_list("pk", flat=True):
                modelo.objects.filter(pk=pk).update(fecha=base + timedelta(minutes=paso))
                paso += 1

    def _get(self, url):
        self._escalonar_fechas()
        return self.client.get(url)

    def test_entrega_de_municion_aparece_con_cantidad_y_soldado(self):
        self.granadas_a.entregar(
            soldado=self.soldado_a, cantidad=15, usuario=self.admin_user,
            observacion="Para el ejercicio",
        )
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertContains(response, "GRANADA DE MANO")
        self.assertContains(response, "Lote LG-7")
        self.assertContains(response, "TE Rada Pedro")
        self.assertContains(response, '<span class="siga-card__serie">15</span>', html=True)
        self.assertContains(response, "Para el ejercicio")

    def test_devolucion_parcial_de_municion_aparece_con_la_cantidad_devuelta(self):
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        asignada = ExistenciaAsignada.objects.get(existencia=self.granadas_a)
        asignada.devolver(cantidad=5, usuario=self.admin_user)
        response = self._get(reverse("inventory:movimiento_list"))
        movimientos = response.context["movimientos"]
        self.assertEqual([m.cantidad for m in movimientos], [5, 15])
        self.assertEqual(
            [m.tipo for m in movimientos],
            [MovimientoExistencia.Tipo.DEVOLUCION, MovimientoExistencia.Tipo.ENTREGA],
        )

    def test_mezcla_las_tres_clases_ordenadas_por_fecha(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        self._prestar(200, self.comp_a, self.comp_b)
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertEqual(self._clases(response), ["PRESTAMO", "MUNICION", "ARMAMENTO"])
        fechas = [m.fecha for m in response.context["movimientos"]]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

    def test_prestamo_muestra_origen_y_destino(self):
        self._prestar(200, self.comp_a, self.comp_b)
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertContains(response, "Préstamo")
        self.assertContains(response, "<strong>Alcatraz</strong> → <strong>Bisonte</strong>")

    def test_prestamo_aparece_en_la_compania_origen_y_en_la_destino(self):
        self._prestar(200, self.comp_a, self.comp_b)
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertEqual(self._clases(response), ["PRESTAMO"])

        session = self.client.session
        session[SESSION_KEY] = self.comp_b.pk
        session.save()
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertEqual(self._clases(response), ["PRESTAMO"])

        session = self.client.session
        session[SESSION_KEY] = self.comp_c.pk
        session.save()
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertEqual(self._clases(response), [])

    def test_compania_de_trabajo_filtra_municion_y_ver_todas_la_incluye(self):
        self.granadas_c.entregar(soldado=self.soldado_c, cantidad=3, usuario=self.admin_user)
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertEqual(self._clases(response), [])
        response = self._get(reverse("inventory:movimiento_list") + "?todas=1")
        self.assertEqual(self._clases(response), ["MUNICION"])

    def test_filtro_clase(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        self._prestar(200, self.comp_a, self.comp_b)
        url = reverse("inventory:movimiento_list")
        self.assertEqual(self._clases(self._get(url + "?clase=MUNICION")), ["MUNICION"])
        self.assertEqual(
            self._clases(self._get(url + "?clase=ARMAMENTO")), ["ARMAMENTO"]
        )
        self.assertEqual(self._clases(self._get(url + "?clase=PRESTAMO")), ["PRESTAMO"])
        # Un valor desconocido se ignora (equivale a Todos).
        self.assertEqual(len(self._clases(self._get(url + "?clase=OTRA"))), 3)

    def test_filtro_tipo_excluye_prestamos_y_baja_excluye_municion(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        self._prestar(200, self.comp_a, self.comp_b)
        url = reverse("inventory:movimiento_list")
        response = self._get(url + "?tipo=ENTREGA")
        self.assertEqual(self._clases(response), ["MUNICION", "ARMAMENTO"])

        self.arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.DANO, fecha=date(2026, 10, 1), usuario=self.admin_user
        )
        response = self._get(url + "?tipo=BAJA")
        self.assertEqual(self._clases(response), ["ARMAMENTO"])

    def test_busqueda_por_soldado_trae_armas_y_municion(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        self._prestar(200, self.comp_a, self.comp_b)
        response = self._get(reverse("inventory:movimiento_list") + "?q=rada")
        self.assertEqual(self._clases(response), ["MUNICION", "ARMAMENTO"])

    def test_busqueda_por_material_y_por_compania(self):
        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        self._prestar(200, self.comp_a, self.comp_b)
        url = reverse("inventory:movimiento_list")
        self.assertEqual(self._clases(self._get(url + "?q=granada")), ["MUNICION"])
        self.assertEqual(self._clases(self._get(url + "?q=bisonte")), ["PRESTAMO"])

    def test_limite_se_aplica_sobre_la_lista_combinada(self):
        from . import views

        self.arma.entregar(soldado=self.soldado_a, usuario=self.admin_user)
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=1, usuario=self.admin_user)
        self._prestar(10, self.comp_a, self.comp_b)
        limite_original = views.MOVIMIENTOS_LIMITE
        views.MOVIMIENTOS_LIMITE = 2
        try:
            response = self._get(reverse("inventory:movimiento_list"))
        finally:
            views.MOVIMIENTOS_LIMITE = limite_original
        self.assertEqual(self._clases(response), ["PRESTAMO", "MUNICION"])

    def test_enlace_ve_la_lista_unificada(self):
        enlace = get_user_model().objects.create_user(email="enlace@example.com", password="x")
        self.client.force_login(enlace)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        response = self._get(reverse("inventory:movimiento_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._clases(response), ["MUNICION"])

    def test_municion_muestra_cuanto_esta_en_mano_y_enlaza_a_quien(self):
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        response = self.client.get(reverse("inventory:existencia_list"))
        self.assertContains(response, "En mano: <strong>15</strong>", html=True)
        self.assertContains(
            response,
            reverse("inventory:existencia_asignada_list") + f"?existencia={self.granadas_a.pk}",
        )
        # Sin entregas no se muestra "En mano" (los cartuchos siguen todos en depósito).
        existencias = {e.pk: e for e in response.context["existencias"]}
        self.assertIsNone(existencias[self.cartuchos_a.pk].en_mano)
        self.assertContains(response, "En mano:", count=1)

    def test_municion_tiene_acceso_visible_a_municion_asignada(self):
        response = self.client.get(reverse("inventory:existencia_list"))
        self.assertContains(response, 'class="siga-quicklinks"')
        self.assertContains(response, ">Consumo asignado</a>")

    def test_asignadas_filtradas_por_existencia(self):
        self.granadas_a.entregar(soldado=self.soldado_a, cantidad=15, usuario=self.admin_user)
        self.cartuchos_a.entregar(soldado=self.soldado_a, cantidad=60, usuario=self.admin_user)
        url = reverse("inventory:existencia_asignada_list")
        response = self.client.get(url + f"?existencia={self.granadas_a.pk}")
        self.assertEqual(
            [a.existencia_id for a in response.context["asignadas"]], [self.granadas_a.pk]
        )
        self.assertEqual(
            [m.existencia_id for m in response.context["movimientos"]], [self.granadas_a.pk]
        )

    def test_asignadas_filtradas_por_existencia_de_otra_compania(self):
        """El enlace "ver quién" también se usa desde "ver todas": la
        existencia manda, no la compañía de trabajo."""
        self.granadas_c.entregar(soldado=self.soldado_c, cantidad=3, usuario=self.admin_user)
        url = reverse("inventory:existencia_asignada_list")
        response = self.client.get(url + f"?existencia={self.granadas_c.pk}")
        self.assertEqual(len(response.context["asignadas"]), 1)

    def test_asignadas_existencia_inexistente_da_404(self):
        url = reverse("inventory:existencia_asignada_list")
        self.assertEqual(self.client.get(url + "?existencia=99999").status_code, 404)


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
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def _buscar(self, termino):
        return self.client.get(
            reverse("inventory:armamento_list"), {"q": termino, "todas": "1"}
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
            "inventory:compania_crear",
            "inventory:deposito_crear",
            "inventory:tipoarmamento_crear",
            "inventory:soldado_crear",
            "inventory:peloton_crear",
            "inventory:campopersonalizado_crear",
            "inventory:armamento_crear",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 403, url_name)

    def test_enlace_no_puede_editar_armamento(self):
        self._login_con_compania(self.enlace)
        url = reverse("inventory:armamento_editar", args=[self.arma.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            url, {"numero_serie": "HACKEADO", "tipo": self.tipo.pk}
        )
        self.assertEqual(response.status_code, 403)
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.numero_serie, "S-900")

    def test_enlace_no_puede_borrar_compania(self):
        self._login_con_compania(self.enlace)
        url = reverse("inventory:compania_borrar", args=[self.compania.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_enlace_si_puede_ver_listados_de_datos_maestros(self):
        self._login_con_compania(self.enlace)
        for url_name in (
            "inventory:compania_list",
            "inventory:deposito_list",
            "inventory:tipoarmamento_list",
            "inventory:soldado_list",
            "inventory:armamento_list",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)

    def test_enlace_no_puede_ver_ni_gestionar_usuarios(self):
        self._login_con_compania(self.enlace)
        response = self.client.get(reverse("accounts:usuario_list"))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("accounts:usuario_crear"))
        self.assertEqual(response.status_code, 403)

    # --- Enlace: sí puede registrar movimientos ---

    def test_enlace_si_puede_entregar_y_devolver(self):
        self._login_con_compania(self.enlace)
        url = reverse("inventory:armamento_entregar", args=[self.arma.pk])
        response = self.client.post(url, {"soldado": self.soldado.pk, "observacion": ""})
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.EN_MANO)

        url = reverse("inventory:armamento_devolver", args=[self.arma.pk])
        response = self.client.post(url, {"deposito": self.deposito.pk, "observacion": ""})
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.ubicacion, Armamento.Ubicacion.DEPOSITO)

    def test_enlace_si_puede_registrar_un_prestamo(self):
        self._login_con_compania(self.enlace)
        otra_compania = Compania.objects.create(unidad=self.unidad, nombre="Bisonte")
        response = self.client.post(
            reverse("inventory:prestamo_transferir"),
            {
                "tipo": self.municion.pk, "deposito": self.deposito.pk, "lote": "",
                "cantidad": 10, "compania_origen": self.compania.pk,
                "compania_destino": otra_compania.pk, "observacion": "",
            },
        )
        self.assertRedirects(response, reverse("inventory:existencia_list"))
        self.assertTrue(Prestamo.objects.filter(compania_destino=otra_compania).exists())

    # --- Administrador (sin ser superusuario) conserva control total ---

    def test_administrador_no_superusuario_puede_gestionar_datos_maestros(self):
        self._login_con_compania(self.admin_no_super)
        response = self.client.get(reverse("inventory:compania_crear"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("inventory:compania_crear"),
            {"unidad": self.unidad.pk, "nombre": "Delta"},
        )
        self.assertRedirects(response, reverse("inventory:compania_list"))
        self.assertTrue(Compania.objects.filter(nombre="Delta").exists())

    def test_administrador_no_superusuario_puede_ver_y_gestionar_usuarios(self):
        self._login_con_compania(self.admin_no_super)
        response = self.client.get(reverse("accounts:usuario_list"))
        self.assertEqual(response.status_code, 200)


class ImportarArmamentoTests(TestCase):
    """Carga inicial del inventario serializado desde Excel (RF-13, H-13)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.alcatraz = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.bisonte = Compania.objects.create(unidad=self.unidad, nombre="Bisonte")
        self.apiay = Deposito.objects.create(nombre="Apiay")
        self.caruru = Deposito.objects.create(nombre="Caruru")
        self.fusil = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        self._archivos = []
        self.addCleanup(self._borrar_archivos)

    def _borrar_archivos(self):
        for ruta in self._archivos:
            os.unlink(ruta)

    def _importar(self, hojas, **opciones):
        ruta = _crear_excel(hojas)
        self._archivos.append(ruta)
        call_command("importar_armamento", ruta, **opciones)

    def test_importa_armamento_por_hoja_de_compania(self):
        self._importar({
            "Alcatraz": [
                ["Serie", "Denominación", "Depósito"],
                ["ALC-001", "FUSIL AR CAL. 5.56 MM", "Apiay"],
                ["ALC-002", "FUSIL AR CAL. 5.56 MM", "Apiay"],
            ],
            "Bisonte": [
                ["Serie", "Denominación", "Depósito"],
                ["BIS-001", "FUSIL AR CAL. 5.56 MM", "Caruru"],
            ],
        })
        self.assertEqual(Armamento.objects.count(), 3)
        arma = Armamento.objects.get(numero_serie="ALC-001")
        self.assertEqual(arma.compania, self.alcatraz)
        self.assertEqual(arma.tipo, self.fusil)
        self.assertEqual(arma.deposito, self.apiay)
        self.assertEqual(arma.ubicacion, Armamento.Ubicacion.DEPOSITO)

    def test_usa_deposito_global_cuando_la_hoja_no_trae_columna(self):
        self._importar(
            {"Alcatraz": [["Serie", "Denominación"], ["ALC-010", "FUSIL AR CAL. 5.56 MM"]]},
            deposito="Apiay",
        )
        arma = Armamento.objects.get(numero_serie="ALC-010")
        self.assertEqual(arma.deposito, self.apiay)

    def test_hoja_sin_compania_conocida_se_omite_con_aviso(self):
        self._importar({
            "Resumen": [["Serie", "Denominación"], ["X-1", "FUSIL AR CAL. 5.56 MM"]],
            "Alcatraz": [
                ["Serie", "Denominación", "Depósito"],
                ["ALC-020", "FUSIL AR CAL. 5.56 MM", "Apiay"],
            ],
        })
        self.assertEqual(Armamento.objects.count(), 1)
        self.assertFalse(Armamento.objects.filter(numero_serie="X-1").exists())

    def test_serie_duplicada_en_archivo_bloquea_toda_la_carga(self):
        with self.assertRaises(CommandError):
            self._importar({
                "Alcatraz": [
                    ["Serie", "Denominación", "Depósito"],
                    ["ALC-030", "FUSIL AR CAL. 5.56 MM", "Apiay"],
                    ["ALC-030", "FUSIL AR CAL. 5.56 MM", "Apiay"],
                ],
            })
        self.assertEqual(Armamento.objects.count(), 0)

    def test_serie_ya_existente_en_bd_bloquea_toda_la_carga(self):
        Armamento.objects.create(
            numero_serie="ALC-999", tipo=self.fusil, compania=self.alcatraz,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.apiay,
        )
        with self.assertRaises(CommandError):
            self._importar({
                "Alcatraz": [
                    ["Serie", "Denominación", "Depósito"],
                    ["ALC-999", "FUSIL AR CAL. 5.56 MM", "Apiay"],
                    ["ALC-040", "FUSIL AR CAL. 5.56 MM", "Apiay"],
                ],
            })
        self.assertFalse(Armamento.objects.filter(numero_serie="ALC-040").exists())

    def test_tipo_no_reconocido_bloquea_toda_la_carga(self):
        with self.assertRaises(CommandError):
            self._importar({
                "Alcatraz": [
                    ["Serie", "Denominación", "Depósito"],
                    ["ALC-050", "RIFLE INEXISTENTE", "Apiay"],
                ],
            })
        self.assertEqual(Armamento.objects.count(), 0)

    def test_tipo_por_cantidad_no_se_reconoce_para_serializados(self):
        with self.assertRaises(CommandError):
            self._importar({
                "Alcatraz": [
                    ["Serie", "Denominación", "Depósito"],
                    ["ALC-060", "MUNICION CAL 5.56MM", "Apiay"],
                ],
            })
        self.assertEqual(Armamento.objects.count(), 0)

    def test_normaliza_errores_de_tipeo_conocidos(self):
        visor = TipoArmamento.objects.create(
            nombre="VISORES NOCTURNOS AN PVS 14", control=TipoArmamento.Control.SERIE
        )
        self._importar({
            "Alcatraz": [
                ["Serie", "Denominación", "Depósito"],
                ["ALC-070", "VOSIRES NOCTURNOS AN PVS 14", "Apiay"],
            ],
        })
        arma = Armamento.objects.get(numero_serie="ALC-070")
        self.assertEqual(arma.tipo, visor)

    def test_sin_deposito_ni_columna_bloquea_la_carga(self):
        with self.assertRaises(CommandError):
            self._importar({
                "Alcatraz": [["Serie", "Denominación"], ["ALC-080", "FUSIL AR CAL. 5.56 MM"]],
            })
        self.assertEqual(Armamento.objects.count(), 0)

    def test_dry_run_no_crea_nada(self):
        self._importar(
            {
                "Alcatraz": [
                    ["Serie", "Denominación", "Depósito"],
                    ["ALC-090", "FUSIL AR CAL. 5.56 MM", "Apiay"],
                ],
            },
            dry_run=True,
        )
        self.assertEqual(Armamento.objects.count(), 0)

    def test_hoja_con_varios_bloques_de_encabezado_repetido(self):
        """El Excel real trae varios bloques por categoría dentro de una misma
        hoja (título + encabezado + datos, separados por filas en blanco) —
        no un único encabezado al principio (issue "cargar la data real")."""
        self._importar({
            "Alcatraz": [
                [None, None, None],
                ["Categoría Uno", None, None],
                ["Denominación", "Serie", "Depósito"],
                ["FUSIL AR CAL. 5.56 MM", "ALC-100", "Apiay"],
                [],
                ["Categoría Dos", None, None],
                ["Denominación", "Serie", "Depósito"],
                ["FUSIL AR CAL. 5.56 MM", "ALC-101", "Caruru"],
            ],
        })
        self.assertEqual(Armamento.objects.count(), 2)
        self.assertEqual(
            Armamento.objects.get(numero_serie="ALC-100").deposito, self.apiay
        )
        self.assertEqual(
            Armamento.objects.get(numero_serie="ALC-101").deposito, self.caruru
        )

    def test_hoja_nombrada_cp_mas_codigo_se_resuelve_por_letra(self):
        """"CP A" no coincide con ninguna Compania sembrada tal cual — se
        resuelve quitando el prefijo y usando el mapeo A -> Alcatraz."""
        self._importar({
            "CP A": [
                ["Serie", "Denominación", "Depósito"],
                ["ALC-200", "FUSIL AR CAL. 5.56 MM", "Apiay"],
            ],
        })
        self.assertEqual(Armamento.objects.get(numero_serie="ALC-200").compania, self.alcatraz)

    def test_fila_sin_serie_crea_existencia_en_vez_de_armamento(self):
        casco = TipoArmamento.objects.create(
            nombre="BALISTICO HELMET KEVLAR N. III", control=TipoArmamento.Control.CANTIDAD
        )
        self._importar({
            "Alcatraz": [
                ["Serie", "Denominación", "Depósito"],
                ["SIN SERIE", "BALISTICO HELMET KEVLAR N. III", "Apiay"],
                ["SIN SERIE", "BALISTICO HELMET KEVLAR N. III", "Apiay"],
            ],
        })
        self.assertEqual(Armamento.objects.count(), 0)
        existencia = Existencia.objects.get(
            tipo=casco, compania=self.alcatraz, deposito=self.apiay
        )
        self.assertEqual(existencia.cantidad, 2)

    def test_deposito_multiple_se_reparte_por_turnos(self):
        self._importar(
            {
                "Alcatraz": [
                    ["Serie", "Denominación"],
                    ["ALC-300", "FUSIL AR CAL. 5.56 MM"],
                    ["ALC-301", "FUSIL AR CAL. 5.56 MM"],
                    ["ALC-302", "FUSIL AR CAL. 5.56 MM"],
                ],
            },
            deposito="Apiay,Caruru",
        )
        self.assertEqual(Armamento.objects.get(numero_serie="ALC-300").deposito, self.apiay)
        self.assertEqual(Armamento.objects.get(numero_serie="ALC-301").deposito, self.caruru)
        self.assertEqual(Armamento.objects.get(numero_serie="ALC-302").deposito, self.apiay)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class ImportarExistenciasTests(TestCase):
    """Carga de existencias por cantidad desde el archivo de consumo (RF-14, H-15)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.alcatraz = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.apiay = Deposito.objects.create(nombre="Apiay")
        self.caruru = Deposito.objects.create(nombre="Caruru")
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        self._archivos = []
        self.addCleanup(self._borrar_archivos)

    def _borrar_archivos(self):
        for ruta in self._archivos:
            os.unlink(ruta)

    def _importar(self, hojas, **opciones):
        ruta = _crear_excel(hojas)
        self._archivos.append(ruta)
        call_command("importar_existencias", ruta, **opciones)

    def test_importa_existencias_por_hoja_de_compania(self):
        self._importar(
            {"Alcatraz": [["No", "MATERIAL", "CARGOS SAP"], [1, "MUNICION CAL 5.56MM", 100]]},
            deposito="Apiay",
        )
        existencia = Existencia.objects.get(tipo=self.municion, compania=self.alcatraz)
        self.assertEqual(existencia.cantidad, 100)
        self.assertEqual(existencia.deposito, self.apiay)

    def test_suma_a_existencia_previa_en_vez_de_reemplazar(self):
        Existencia.objects.create(
            tipo=self.municion, compania=self.alcatraz, deposito=self.apiay, cantidad=50
        )
        self._importar(
            {"Alcatraz": [["No", "MATERIAL", "CARGOS SAP"], [1, "MUNICION CAL 5.56MM", 100]]},
            deposito="Apiay",
        )
        existencia = Existencia.objects.get(
            tipo=self.municion, compania=self.alcatraz, deposito=self.apiay
        )
        self.assertEqual(existencia.cantidad, 150)

    def test_deposito_multiple_se_reparte_por_turnos(self):
        self._importar(
            {
                "Alcatraz": [
                    ["No", "MATERIAL", "CARGOS SAP"],
                    [1, "MUNICION CAL 5.56MM", 10],
                ],
                "CP A": [
                    ["No", "MATERIAL", "CARGOS SAP"],
                    [1, "MUNICION CAL 5.56MM", 20],
                ],
            },
            deposito="Apiay,Caruru",
        )
        # dos hojas resuelven a la misma compañía (Alcatraz y CP A) — cada una
        # es una fila válida distinta, así que se reparten por turnos.
        total = Existencia.objects.filter(tipo=self.municion, compania=self.alcatraz)
        self.assertEqual(total.filter(deposito=self.apiay).first().cantidad, 10)
        self.assertEqual(total.filter(deposito=self.caruru).first().cantidad, 20)

    def test_material_no_reconocido_bloquea_toda_la_carga(self):
        with self.assertRaises(CommandError):
            self._importar(
                {"Alcatraz": [["No", "MATERIAL", "CARGOS SAP"], [1, "MATERIAL INEXISTENTE", 5]]},
                deposito="Apiay",
            )
        self.assertEqual(Existencia.objects.count(), 0)

    def test_sin_deposito_bloquea_la_carga(self):
        with self.assertRaises(CommandError):
            self._importar(
                {"Alcatraz": [["No", "MATERIAL", "CARGOS SAP"], [1, "MUNICION CAL 5.56MM", 5]]}
            )

    def test_dry_run_no_modifica_nada(self):
        self._importar(
            {"Alcatraz": [["No", "MATERIAL", "CARGOS SAP"], [1, "MUNICION CAL 5.56MM", 5]]},
            deposito="Apiay",
            dry_run=True,
        )
        self.assertEqual(Existencia.objects.count(), 0)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class MasterCrudTests(TestCase):
    """CRUD genérico de datos maestros (`apps/inventory/crud.py`)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def test_borrar_compania_sin_dependientes(self):
        response = self.client.post(
            reverse("inventory:compania_borrar", args=[self.compania.pk])
        )
        self.assertRedirects(response, reverse("inventory:compania_list"))
        self.assertFalse(Compania.objects.filter(pk=self.compania.pk).exists())

    def test_borrar_compania_con_dependientes_no_revienta(self):
        """Compania.pelotones usa on_delete=PROTECT — borrar una compañía con
        pelotones debe mostrar un error, no un 500 (ProtectedError sin
        capturar)."""
        Peloton.objects.create(compania=self.compania, nombre="Alcatraz 1")
        response = self.client.post(
            reverse("inventory:compania_borrar", args=[self.compania.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Compania.objects.filter(pk=self.compania.pk).exists())
        self.assertContains(response, "No se puede borrar")

    def test_crear_editar_borrar_deposito(self):
        response = self.client.post(
            reverse("inventory:deposito_crear"), {"nombre": "Caruru", "descripcion": ""}
        )
        self.assertRedirects(response, reverse("inventory:deposito_list"))
        nuevo = Deposito.objects.get(nombre="Caruru")

        response = self.client.post(
            reverse("inventory:deposito_editar", args=[nuevo.pk]),
            {"nombre": "Caruru", "descripcion": "Depósito secundario"},
        )
        self.assertRedirects(response, reverse("inventory:deposito_list"))
        nuevo.refresh_from_db()
        self.assertEqual(nuevo.descripcion, "Depósito secundario")

        response = self.client.post(reverse("inventory:deposito_borrar", args=[nuevo.pk]))
        self.assertRedirects(response, reverse("inventory:deposito_list"))
        self.assertFalse(Deposito.objects.filter(pk=nuevo.pk).exists())

    def test_nombre_duplicado_muestra_error_de_formulario(self):
        response = self.client.post(
            reverse("inventory:deposito_crear"), {"nombre": "Apiay", "descripcion": ""}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Deposito.objects.filter(nombre="Apiay").count(), 1)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class CardListaVisibleEnEscritorioTests(TestCase):
    """issue #8: #3 (ba1e771) escondió `.siga-card-list` en escritorio pensando
    que era exclusiva de Inventario, pero la clase la reusan `ajustes.html`,
    `master_list.html` y varias listas más — quedaron en blanco en escritorio.
    Estos tests no evalúan CSS (pytest no renderiza estilos), pero fijan la
    estructura HTML que el fix depende de: Inventario debe llevar el modificador
    `--inventario` que sí se esconde, y las demás pantallas deben conservar la
    clase base sin ese modificador para no quedar atrapadas por la misma regla
    si alguien la vuelve a escribir sin escopar."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.tipo = TipoArmamento.objects.create(
            nombre="ACE-23", control=TipoArmamento.Control.SERIE
        )
        Armamento.objects.create(
            numero_serie="CARD-1", tipo=self.tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def test_ajustes_conserva_la_clase_de_tarjetas_sin_el_modificador_de_inventario(self):
        response = self.client.get(reverse("inventory:ajustes"))
        self.assertContains(response, 'class="siga-card-list"')
        self.assertNotContains(response, "siga-card-list--inventario")

    def test_lista_generica_de_datos_maestros_conserva_la_clase_de_tarjetas(self):
        response = self.client.get(reverse("inventory:compania_list"))
        self.assertContains(response, 'class="siga-card-list"')
        self.assertNotContains(response, "siga-card-list--inventario")

    def test_inventario_lleva_el_modificador_que_si_se_esconde_en_escritorio(self):
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, "siga-card-list--inventario")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class SoldadoExistenciaBorrarTests(TestCase):
    """Borrar soldado/existencia (ADMIN-only), con el mismo manejo de
    ProtectedError que `MasterDeleteView` (ver `_borrar_protegido`)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.compania = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.peloton = Peloton.objects.create(compania=self.compania, nombre="Alcatraz 1")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

    def test_borrar_soldado_sin_armas(self):
        soldado = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.compania, peloton=self.peloton
        )
        response = self.client.post(reverse("inventory:soldado_borrar", args=[soldado.pk]))
        self.assertRedirects(response, reverse("inventory:soldado_list"))
        self.assertFalse(Soldado.objects.filter(pk=soldado.pk).exists())

    def test_borrar_soldado_con_arma_en_mano_no_revienta(self):
        soldado = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.compania, peloton=self.peloton
        )
        tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        Armamento.objects.create(
            numero_serie="S-1", tipo=tipo, compania=self.compania,
            ubicacion=Armamento.Ubicacion.EN_MANO, soldado=soldado,
        )
        response = self.client.post(
            reverse("inventory:soldado_borrar", args=[soldado.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Soldado.objects.filter(pk=soldado.pk).exists())
        self.assertContains(response, "No se puede borrar")

    def test_borrar_existencia(self):
        existencia = Existencia.objects.create(
            tipo=self.municion, compania=self.compania, deposito=self.deposito, cantidad=10
        )
        response = self.client.post(
            reverse("inventory:existencia_borrar", args=[existencia.pk])
        )
        self.assertRedirects(response, reverse("inventory:existencia_list"))
        self.assertFalse(Existencia.objects.filter(pk=existencia.pk).exists())

    def test_enlace_no_puede_borrar_soldado_ni_existencia(self):
        soldado = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.compania, peloton=self.peloton
        )
        existencia = Existencia.objects.create(
            tipo=self.municion, compania=self.compania, deposito=self.deposito, cantidad=10
        )
        enlace = get_user_model().objects.create_user(email="enlace@example.com", password="x")
        self.client.force_login(enlace)
        session = self.client.session
        session[SESSION_KEY] = self.compania.pk
        session.save()

        response = self.client.post(reverse("inventory:soldado_borrar", args=[soldado.pk]))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse("inventory:existencia_borrar", args=[existencia.pk])
        )
        self.assertEqual(response.status_code, 403)


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class SoldadoFichaTests(TestCase):
    """Issue #17 (RF-20): ficha del soldado con lo que tiene a cargo
    (resumen por tipo + detalle), sus últimos movimientos y acceso a
    devolver, volviendo a la ficha."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.comp_a = Compania.objects.create(unidad=self.unidad, nombre="ASPC")
        self.comp_b = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.deposito = Deposito.objects.create(nombre="Apiay")
        self.peloton_a = Peloton.objects.create(compania=self.comp_a, nombre="ASPC 1")
        self.peloton_b = Peloton.objects.create(compania=self.comp_b, nombre="Alcatraz 1")
        self.soldado = Soldado.objects.create(
            apellidos_nombres="Bolaños Gómez David", compania=self.comp_a,
            peloton=self.peloton_a, grado="CT",
        )
        self.otro = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.comp_a, peloton=self.peloton_a
        )
        self.de_otra_compania = Soldado.objects.create(
            apellidos_nombres="Rada Pedro", compania=self.comp_b, peloton=self.peloton_b,
            grado="TE",
        )
        self.fusil = TipoArmamento.objects.create(
            nombre="FUSIL GALIL", control=TipoArmamento.Control.SERIE
        )
        self.cartucho = TipoArmamento.objects.create(
            nombre="CARTUCHO 5.56", control=TipoArmamento.Control.CANTIDAD
        )
        self.casco = TipoArmamento.objects.create(
            nombre="CASCO", control=TipoArmamento.Control.CANTIDAD
        )
        self.arma = self._arma("GAL-001")
        self.cartuchos_l1 = Existencia.objects.create(
            tipo=self.cartucho, compania=self.comp_a, deposito=self.deposito,
            lote="L1", cantidad=500,
        )
        self.cartuchos_l2 = Existencia.objects.create(
            tipo=self.cartucho, compania=self.comp_a, deposito=self.deposito,
            lote="L2", cantidad=500,
        )
        self.cascos = Existencia.objects.create(
            tipo=self.casco, compania=self.comp_a, deposito=self.deposito, cantidad=20
        )
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            email="admin@example.com", password="x", role=user_model.Role.ADMIN
        )
        self.enlace = user_model.objects.create_user(email="enlace@example.com", password="x")
        self._login(self.admin_user)

    def _login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session[SESSION_KEY] = self.comp_a.pk
        session.save()

    def _arma(self, serie):
        return Armamento.objects.create(
            numero_serie=serie, tipo=self.fusil, compania=self.comp_a,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )

    def _url(self, soldado=None):
        return reverse("inventory:soldado_detalle", args=[(soldado or self.soldado).pk])

    def _escalonar_fechas(self):
        """Fechas distintas en orden de creación (armas por pk, luego
        munición por pk): `auto_now_add` puede repetirse entre filas."""
        base = timezone.now() - timedelta(days=1)
        paso = 0
        for modelo in (Movimiento, MovimientoExistencia):
            for pk in modelo.objects.order_by("pk").values_list("pk", flat=True):
                modelo.objects.filter(pk=pk).update(fecha=base + timedelta(minutes=paso))
                paso += 1

    def test_lista_de_soldados_enlaza_a_la_ficha(self):
        response = self.client.get(reverse("inventory:soldado_list"))
        self.assertContains(response, f'href="{self._url()}"')

    def test_ficha_muestra_encabezado(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CT Bolaños Gómez David")
        self.assertContains(response, "Compañía ASPC · Pelotón ASPC 1")

    def test_resumen_suma_por_tipo_entre_lotes_y_cuenta_armas(self):
        self.arma.entregar(soldado=self.soldado, usuario=self.admin_user)
        self.cartuchos_l1.entregar(soldado=self.soldado, cantidad=80, usuario=self.admin_user)
        self.cartuchos_l2.entregar(soldado=self.soldado, cantidad=40, usuario=self.admin_user)
        self.cascos.entregar(soldado=self.soldado, cantidad=1, usuario=self.admin_user)
        response = self.client.get(self._url())
        resumen = [(i["nombre"], i["cantidad"]) for i in response.context["resumen"]]
        self.assertEqual(
            resumen, [("FUSIL GALIL", 1), ("CARTUCHO 5.56", 120), ("CASCO", 1)]
        )
        # El detalle sí conserva una fila por lote.
        self.assertEqual(len(response.context["asignadas"]), 3)
        self.assertContains(response, "A cargo actualmente")

    def test_resumen_aparece_antes_que_el_detalle_y_el_historial(self):
        self.cascos.entregar(soldado=self.soldado, cantidad=1, usuario=self.admin_user)
        html = self.client.get(self._url()).content.decode()
        self.assertLess(html.index("A cargo actualmente"), html.index("Armamento en mano"))
        self.assertLess(html.index("Armamento en mano"), html.index("Últimos movimientos"))

    def test_soldado_sin_nada_muestra_estados_vacios(self):
        response = self.client.get(self._url())
        self.assertContains(response, "No tiene material a cargo.")
        self.assertContains(response, "No tiene armamento a cargo.")
        self.assertContains(response, "No tiene consumo a cargo.")
        self.assertContains(response, "Sin movimientos todavía.")

    def test_solo_muestra_lo_del_soldado(self):
        otra_arma = self._arma("GAL-002")
        otra_arma.entregar(soldado=self.otro, usuario=self.admin_user)
        self.cascos.entregar(soldado=self.otro, cantidad=2, usuario=self.admin_user)
        response = self.client.get(self._url())
        self.assertEqual(response.context["resumen"], [])
        self.assertEqual(response.context["historial"], [])

    def test_devolucion_parcial_actualiza_cantidad_e_historial(self):
        self.cascos.entregar(soldado=self.soldado, cantidad=15, usuario=self.admin_user)
        asignada = ExistenciaAsignada.objects.get(existencia=self.cascos)
        asignada.devolver(cantidad=5, usuario=self.admin_user, observacion="Sobraban")
        self._escalonar_fechas()
        response = self.client.get(self._url())
        self.assertEqual(response.context["resumen"][0]["cantidad"], 10)
        historial = response.context["historial"]
        self.assertEqual([(m.tipo, m.cantidad) for m in historial], [
            (MovimientoExistencia.Tipo.DEVOLUCION, 5),
            (MovimientoExistencia.Tipo.ENTREGA, 15),
        ])
        self.assertContains(response, "Observación: Sobraban")
        self.assertContains(response, "por admin@example.com")

    def test_historial_incluye_devolucion_de_arma_aunque_no_guarde_soldado(self):
        """`Armamento.devolver()` deja `soldado=None` en el Movimiento; la
        ficha la atribuye al soldado que tenía el arma."""
        self.arma.entregar(soldado=self.soldado, usuario=self.admin_user)
        self.arma.devolver(deposito=self.deposito, usuario=self.admin_user)
        # Después se entrega a otro y la devuelve: eso no es del soldado.
        self.arma.entregar(soldado=self.otro, usuario=self.admin_user)
        self.arma.devolver(deposito=self.deposito, usuario=self.admin_user)
        self._escalonar_fechas()
        response = self.client.get(self._url())
        self.assertEqual(
            [m.tipo for m in response.context["historial"]],
            [Movimiento.Tipo.DEVOLUCION, Movimiento.Tipo.ENTREGA],
        )
        self.assertEqual(response.context["armas"], [])
        self.assertContains(response, "Devolución de armamento")
        self.assertContains(response, "· a Apiay")

    def test_arma_dada_de_baja_en_mano_no_esta_a_cargo_pero_si_en_historial(self):
        self.arma.entregar(soldado=self.soldado, usuario=self.admin_user)
        self.arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.PERDIDA, fecha=date(2026, 10, 1),
            usuario=self.admin_user,
        )
        self._escalonar_fechas()
        response = self.client.get(self._url())
        self.assertEqual(response.context["armas"], [])
        self.assertEqual(response.context["resumen"], [])
        self.assertEqual(
            [m.tipo for m in response.context["historial"]],
            [Movimiento.Tipo.BAJA, Movimiento.Tipo.ENTREGA],
        )
        self.assertContains(response, "Baja de armamento")

    def test_historial_limitado_a_50(self):
        for _ in range(30):
            self.cartuchos_l1.entregar(soldado=self.soldado, cantidad=1, usuario=self.admin_user)
        for _ in range(13):
            self.arma.entregar(soldado=self.soldado, usuario=self.admin_user)
            self.arma.devolver(deposito=self.deposito, usuario=self.admin_user)
        response = self.client.get(self._url())
        self.assertEqual(len(response.context["historial"]), 50)

    def test_devolver_arma_desde_la_ficha_vuelve_a_la_ficha(self):
        self.arma.entregar(soldado=self.soldado, usuario=self.admin_user)
        response = self.client.get(self._url())
        devolver = reverse("inventory:armamento_devolver", args=[self.arma.pk])
        self.assertContains(response, f"{devolver}?next=")
        response = self.client.get(devolver, {"next": self._url()})
        self.assertContains(response, f'name="next" value="{self._url()}"')
        response = self.client.post(
            devolver, {"deposito": self.deposito.pk, "observacion": "", "next": self._url()}
        )
        self.assertRedirects(response, self._url())

    def test_devolver_municion_desde_la_ficha_vuelve_a_la_ficha(self):
        self.cascos.entregar(soldado=self.soldado, cantidad=3, usuario=self.admin_user)
        asignada = ExistenciaAsignada.objects.get(existencia=self.cascos)
        devolver = reverse("inventory:existencia_devolver", args=[asignada.pk])
        response = self.client.post(
            devolver, {"cantidad": 1, "observacion": "", "next": self._url()}
        )
        self.assertRedirects(response, self._url())

    def test_devolver_con_error_conserva_next(self):
        self.cascos.entregar(soldado=self.soldado, cantidad=3, usuario=self.admin_user)
        asignada = ExistenciaAsignada.objects.get(existencia=self.cascos)
        devolver = reverse("inventory:existencia_devolver", args=[asignada.pk])
        response = self.client.post(
            devolver, {"cantidad": 99, "observacion": "", "next": self._url()}
        )
        self.assertRedirects(
            response, f"{devolver}?next={self._url().replace('/', '%2F')}",
            fetch_redirect_response=False,
        )

    def test_devolver_sin_next_mantiene_el_redirect_de_siempre(self):
        self.arma.entregar(soldado=self.soldado, usuario=self.admin_user)
        devolver = reverse("inventory:armamento_devolver", args=[self.arma.pk])
        response = self.client.post(devolver, {"deposito": self.deposito.pk, "observacion": ""})
        self.assertRedirects(response, reverse("inventory:armamento_list"))

    def test_devolver_ignora_next_externo(self):
        self.arma.entregar(soldado=self.soldado, usuario=self.admin_user)
        devolver = reverse("inventory:armamento_devolver", args=[self.arma.pk])
        response = self.client.post(
            devolver,
            {"deposito": self.deposito.pk, "observacion": "", "next": "https://evil.example/"},
        )
        self.assertRedirects(response, reverse("inventory:armamento_list"))

    def test_enlace_ve_la_ficha_y_devolver_pero_no_editar(self):
        self.cascos.entregar(soldado=self.soldado, cantidad=3, usuario=self.admin_user)
        self._login(self.enlace)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Devolver")
        self.assertNotContains(
            response, reverse("inventory:soldado_editar", args=[self.soldado.pk])
        )

    def test_admin_ve_editar(self):
        response = self.client.get(self._url())
        self.assertContains(
            response, reverse("inventory:soldado_editar", args=[self.soldado.pk])
        )

    def test_ficha_de_soldado_de_otra_compania_se_puede_abrir(self):
        response = self.client.get(self._url(self.de_otra_compania))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TE Rada Pedro")

    def test_soldado_inexistente_da_404(self):
        response = self.client.get(reverse("inventory:soldado_detalle", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_navegacion_marca_soldados_como_activo(self):
        response = self.client.get(self._url())
        soldados = reverse("inventory:soldado_list")
        self.assertContains(
            response, f'siga-bottom-nav__item--active" href="{soldados}"'
        )


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class DevolucionPrestamoTests(TestCase):
    """Devolver préstamos de munición y resaltar lo prestado/recibido
    (issue #22, RF-22, ADR-0006)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.alcatraz = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.aspc = Compania.objects.create(unidad=self.unidad, nombre="ASPC")
        self.deposito = Deposito.objects.create(nombre="Caruru")
        self.municion = TipoArmamento.objects.create(
            nombre="MUNICION CAL 5.56MM", control=TipoArmamento.Control.CANTIDAD
        )
        self.origen = Existencia.objects.create(
            tipo=self.municion, compania=self.alcatraz, deposito=self.deposito,
            lote="P068", cantidad=2000,
        )
        self.usuario = get_user_model().objects.create_user(
            email="enlace@example.com", password="x"
        )
        self.prestamo = Prestamo(
            tipo=self.municion, deposito=self.deposito, lote="P068", cantidad=1500,
            compania_origen=self.alcatraz, compania_destino=self.aspc, usuario=self.usuario,
        )
        self.prestamo.full_clean()
        self.prestamo.save()
        self.destino = Existencia.objects.get(compania=self.aspc, tipo=self.municion)

    def _entrar(self, compania):
        self.client.force_login(self.usuario)
        session = self.client.session
        session[SESSION_KEY] = compania.pk
        session.save()

    def _refrescar(self):
        for obj in (self.prestamo, self.origen, self.destino):
            obj.refresh_from_db()

    def test_devolucion_parcial_ajusta_existencias_y_saldo(self):
        devolucion = self.prestamo.devolver(
            cantidad=500, usuario=self.usuario, observacion="Sobró del polígono"
        )
        self._refrescar()
        self.assertEqual(self.destino.cantidad, 1000)
        self.assertEqual(self.origen.cantidad, 1000)
        self.assertEqual(self.prestamo.saldo, 1000)
        self.assertEqual(devolucion.cantidad, 500)
        self.assertEqual(devolucion.observacion, "Sobró del polígono")

    def test_devolucion_total_deja_saldo_en_cero(self):
        self.prestamo.devolver(cantidad=600, usuario=self.usuario)
        self.prestamo.devolver(cantidad=900, usuario=self.usuario)
        self._refrescar()
        self.assertEqual(self.prestamo.saldo, 0)
        self.assertEqual(self.origen.cantidad, 2000)
        self.assertEqual(self.destino.cantidad, 0)
        self.assertEqual(
            self.prestamo.cantidad_devuelta,
            sum(d.cantidad for d in self.prestamo.devoluciones.all()),
        )

    def test_no_devuelve_mas_que_el_saldo(self):
        self.prestamo.devolver(cantidad=1000, usuario=self.usuario)
        with self.assertRaisesMessage(ValidationError, "Solo quedan 500 pendientes"):
            self.prestamo.devolver(cantidad=501, usuario=self.usuario)

    def test_no_devuelve_lo_que_esta_en_mano_de_soldados(self):
        peloton = Peloton.objects.create(compania=self.aspc, nombre="ASPC 1")
        soldado = Soldado.objects.create(
            apellidos_nombres="Ríos Carlos", compania=self.aspc, peloton=peloton
        )
        self.destino.entregar(soldado=soldado, cantidad=1200, usuario=self.usuario)
        with self.assertRaisesMessage(ValidationError, "ASPC solo tiene 300 en depósito"):
            self.prestamo.devolver(cantidad=400, usuario=self.usuario)
        self._refrescar()
        self.assertEqual(self.prestamo.saldo, 1500)

    def test_cantidad_cero_rechazada(self):
        with self.assertRaises(ValidationError):
            self.prestamo.devolver(cantidad=0, usuario=self.usuario)

    def test_municion_resalta_recibido_y_prestado(self):
        self._entrar(self.aspc)
        response = self.client.get(reverse("inventory:existencia_list"))
        self.assertContains(response, "siga-card--prestamo")
        self.assertContains(response, "En préstamo de <strong>Alcatraz</strong>: <strong>1500")
        self.assertContains(
            response, reverse("inventory:prestamo_devolver", args=[self.prestamo.pk])
        )

        self._entrar(self.alcatraz)
        response = self.client.get(reverse("inventory:existencia_list"))
        self.assertContains(response, "A <strong>ASPC</strong>: <strong>1500")

    def test_sin_resaltado_cuando_ya_se_devolvio(self):
        self.prestamo.devolver(cantidad=1500, usuario=self.usuario)
        self._entrar(self.aspc)
        response = self.client.get(reverse("inventory:existencia_list") + "?todas=1")
        self.assertNotContains(response, "siga-card--prestamo")

    def test_vista_devolver_registra_y_vuelve_a_municion(self):
        self._entrar(self.aspc)
        url = reverse("inventory:prestamo_devolver", args=[self.prestamo.pk])
        self.assertContains(self.client.get(url), 'value="1500"')
        municion = reverse("inventory:existencia_list")
        response = self.client.post(
            url, {"cantidad": "500", "observacion": "", "next": municion}
        )
        self.assertRedirects(response, municion)
        self._refrescar()
        self.assertEqual(self.prestamo.saldo, 1000)

    def test_vista_devolver_muestra_error_si_excede(self):
        self._entrar(self.aspc)
        url = reverse("inventory:prestamo_devolver", args=[self.prestamo.pk])
        response = self.client.post(url, {"cantidad": "9999"}, follow=True)
        self.assertContains(response, "Solo quedan 1500 pendientes")
        self._refrescar()
        self.assertEqual(self.prestamo.saldo, 1500)

    def test_lista_de_prestamos_muestra_estado(self):
        self._entrar(self.aspc)
        url = reverse("inventory:prestamo_list")
        self.assertContains(self.client.get(url), "Pendiente")
        self.prestamo.devolver(cantidad=500, usuario=self.usuario)
        self.assertContains(self.client.get(url), "Devuelto parcial")
        self.prestamo.devolver(cantidad=1000, usuario=self.usuario)
        response = self.client.get(url)
        self.assertContains(response, "Devuelto")
        self.assertNotContains(
            response, reverse("inventory:prestamo_devolver", args=[self.prestamo.pk])
        )

    def test_devolucion_aparece_en_movimientos(self):
        self.prestamo.devolver(cantidad=500, usuario=self.usuario, observacion="Parcial")
        self._entrar(self.aspc)
        url = reverse("inventory:movimiento_list")
        for params in ({}, {"clase": "PRESTAMO"}):
            response = self.client.get(url, params)
            self.assertContains(response, "Devolución de préstamo", msg_prefix=str(params))
            self.assertContains(response, "Parcial", msg_prefix=str(params))
        # "Devolución de préstamo" también es un tipo de movimiento de arma
        # (#23) y sale en el filtro de tipo: se busca la fila por su observación.
        response = self.client.get(url, {"clase": "MUNICION"})
        self.assertNotContains(response, "Parcial")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class PrestamoArmamentoTests(TestCase):
    """Préstamo temporal de armamento entre compañías (issue #23, RF-23,
    ADR-0007)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.alcatraz = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.aspc = Compania.objects.create(unidad=self.unidad, nombre="ASPC")
        self.deposito = Deposito.objects.create(nombre="Caruru")
        self.tipo = TipoArmamento.objects.create(
            nombre="FUSIL AR CAL. 5.56 MM", control=TipoArmamento.Control.SERIE
        )
        self.soldado_alcatraz = Soldado.objects.create(
            apellidos_nombres="Pérez Juan", compania=self.alcatraz,
            peloton=Peloton.objects.create(compania=self.alcatraz, nombre="AL 1"),
        )
        self.soldado_aspc = Soldado.objects.create(
            apellidos_nombres="Gómez Ana", compania=self.aspc,
            peloton=Peloton.objects.create(compania=self.aspc, nombre="AS 1"),
        )
        self.arma = self._arma("P-001")
        self.usuario = get_user_model().objects.create_user(
            email="enlace@example.com", password="x"
        )

    def _arma(self, serie):
        return Armamento.objects.create(
            numero_serie=serie, tipo=self.tipo, compania=self.alcatraz,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=self.deposito,
        )

    def _entrar(self, compania):
        self.client.force_login(self.usuario)
        session = self.client.session
        session[SESSION_KEY] = compania.pk
        session.save()

    def _prestar(self):
        self.arma.prestar(compania=self.aspc, usuario=self.usuario, observacion="Polígono")
        self.arma.refresh_from_db()

    def _dar_de_baja(self, arma):
        arma.dar_de_baja(
            motivo=Armamento.MotivoBaja.DANO, fecha=date.today(), usuario=self.usuario
        )

    def test_prestar_registra_movimiento_y_no_cambia_duena(self):
        self._prestar()
        self.assertEqual(self.arma.compania, self.alcatraz)
        self.assertEqual(self.arma.compania_poseedora, self.aspc)
        mov = self.arma.movimientos.get()
        self.assertEqual(mov.tipo, Movimiento.Tipo.PRESTAMO)
        self.assertEqual(mov.compania_en_prestamo, self.aspc)
        self.assertEqual(mov.usuario, self.usuario)
        self.assertEqual(mov.observacion, "Polígono")

    def test_no_presta_a_la_propia_compania(self):
        with self.assertRaises(ValidationError):
            self.arma.prestar(compania=self.alcatraz, usuario=self.usuario)

    def test_no_presta_un_arma_ya_prestada(self):
        self._prestar()
        tercera = Compania.objects.create(unidad=self.unidad, nombre="Tercera")
        with self.assertRaises(ValidationError):
            self.arma.prestar(compania=tercera, usuario=self.usuario)

    def test_no_presta_un_arma_en_mano(self):
        self.arma.entregar(soldado=self.soldado_alcatraz, usuario=self.usuario)
        with self.assertRaises(ValidationError):
            self.arma.prestar(compania=self.aspc, usuario=self.usuario)

    def test_no_presta_un_arma_de_baja(self):
        self._dar_de_baja(self.arma)
        with self.assertRaises(ValidationError):
            self.arma.prestar(compania=self.aspc, usuario=self.usuario)

    def test_receptora_entrega_y_duena_no(self):
        self._prestar()
        with self.assertRaises(ValidationError):
            self.arma.entregar(soldado=self.soldado_alcatraz, usuario=self.usuario)
        mov = self.arma.entregar(soldado=self.soldado_aspc, usuario=self.usuario)
        self.assertEqual(mov.compania_en_prestamo, self.aspc)
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.soldado, self.soldado_aspc)

    def test_devolver_prestamo_solo_en_deposito(self):
        self._prestar()
        self.arma.entregar(soldado=self.soldado_aspc, usuario=self.usuario)
        with self.assertRaisesMessage(ValidationError, "Primero devuelve el arma al depósito"):
            self.arma.devolver_prestamo(usuario=self.usuario)
        self.arma.devolver(deposito=self.deposito, usuario=self.usuario)
        self.arma.devolver_prestamo(usuario=self.usuario)
        self.arma.refresh_from_db()
        self.assertIsNone(self.arma.compania_en_prestamo)
        ultimo = self.arma.movimientos.order_by("-fecha", "-pk").first()
        self.assertEqual(ultimo.tipo, Movimiento.Tipo.DEV_PRESTAMO)
        self.assertEqual(ultimo.compania_en_prestamo, self.aspc)
        # Alcatraz vuelve a poder entregarla.
        self.arma.entregar(soldado=self.soldado_alcatraz, usuario=self.usuario)

    def test_no_se_da_de_baja_mientras_esta_prestada(self):
        self._prestar()
        with self.assertRaises(ValidationError):
            self._dar_de_baja(self.arma)

    def test_inventario_resalta_en_ambas_y_cuenta_en_la_receptora(self):
        self._prestar()
        self._entrar(self.aspc)
        resp = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(resp, "P-001")
        self.assertContains(resp, "Prestada por Alcatraz")
        self.assertEqual(resp.context["kpi_total"], 1)

        self._entrar(self.alcatraz)
        resp = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(resp, "P-001")
        self.assertContains(resp, "Prestada a ASPC")
        self.assertEqual(resp.context["kpi_total"], 0)

    def test_al_devolver_deja_de_aparecer_en_la_receptora(self):
        self._prestar()
        self.arma.devolver_prestamo(usuario=self.usuario)
        self._entrar(self.aspc)
        resp = self.client.get(reverse("inventory:armamento_list"))
        self.assertNotContains(resp, "P-001")

    def test_detalle_oculta_entregar_a_la_duena_mientras_esta_prestada(self):
        self._prestar()
        entregar = reverse("inventory:armamento_entregar", args=[self.arma.pk])
        detalle = reverse("inventory:armamento_detalle", args=[self.arma.pk])
        self._entrar(self.alcatraz)
        resp = self.client.get(detalle)
        self.assertNotContains(resp, entregar)
        self.assertContains(resp, "Devolver préstamo")
        self.assertContains(resp, "Prestada a ASPC")
        self._entrar(self.aspc)
        resp = self.client.get(detalle)
        self.assertContains(resp, entregar)
        self.assertContains(resp, "Prestada por Alcatraz")

    def test_selector_de_entrega_muestra_soldados_de_la_receptora(self):
        self._prestar()
        self._entrar(self.aspc)
        resp = self.client.get(reverse("inventory:armamento_entregar", args=[self.arma.pk]))
        self.assertContains(resp, "Gómez Ana")
        self.assertNotContains(resp, "Pérez Juan")

    def test_vistas_prestar_y_devolver(self):
        detalle = reverse("inventory:armamento_detalle", args=[self.arma.pk])
        self._entrar(self.alcatraz)
        resp = self.client.post(
            reverse("inventory:armamento_prestar", args=[self.arma.pk]),
            {"compania": self.aspc.pk, "observacion": "Apoyo"},
        )
        self.assertRedirects(resp, detalle)
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.compania_en_prestamo, self.aspc)

        resp = self.client.post(
            reverse("inventory:armamento_devolver_prestamo", args=[self.arma.pk]),
            {"observacion": "Fin del apoyo"},
        )
        self.assertRedirects(resp, detalle)
        self.arma.refresh_from_db()
        self.assertIsNone(self.arma.compania_en_prestamo)

    def test_vista_devolver_prestamo_en_mano_muestra_error(self):
        self._prestar()
        self.arma.entregar(soldado=self.soldado_aspc, usuario=self.usuario)
        self._entrar(self.aspc)
        url = reverse("inventory:armamento_devolver_prestamo", args=[self.arma.pk])
        resp = self.client.post(url, follow=True)
        self.assertContains(resp, "Primero devuelve el arma al depósito")
        self.arma.refresh_from_db()
        self.assertEqual(self.arma.compania_en_prestamo, self.aspc)

    def test_vista_no_presta_a_la_propia_compania(self):
        self._entrar(self.alcatraz)
        resp = self.client.post(
            reverse("inventory:armamento_prestar", args=[self.arma.pk]),
            {"compania": self.alcatraz.pk},
        )
        self.assertEqual(resp.status_code, 404)

    def test_historial_y_movimientos_muestran_el_prestamo(self):
        self._prestar()
        self.arma.entregar(soldado=self.soldado_aspc, usuario=self.usuario)
        self.arma.devolver(deposito=self.deposito, usuario=self.usuario)
        self.arma.devolver_prestamo(usuario=self.usuario)

        self._entrar(self.alcatraz)
        resp = self.client.get(reverse("inventory:armamento_detalle", args=[self.arma.pk]))
        self.assertContains(resp, "Préstamo a otra compañía")
        self.assertContains(resp, "De Alcatraz a ASPC")
        self.assertContains(resp, "De ASPC a Alcatraz")

        # ASPC ve en Movimientos lo que hizo con el arma prestada.
        self._entrar(self.aspc)
        resp = self.client.get(reverse("inventory:movimiento_list"))
        self.assertContains(resp, "P-001")
        self.assertContains(resp, "Devolución de préstamo")

    def test_ficha_del_soldado_receptor_muestra_el_arma_prestada(self):
        self._prestar()
        self.arma.entregar(soldado=self.soldado_aspc, usuario=self.usuario)
        self._entrar(self.aspc)
        resp = self.client.get(reverse("inventory:soldado_detalle", args=[self.soldado_aspc.pk]))
        self.assertContains(resp, "P-001")


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class SeleccionGlobalTests(TestCase):
    """Selección global de compañía y/o depósito (issue #25, RF-02/RF-24)."""

    def setUp(self):
        self.unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        self.alcatraz = Compania.objects.create(unidad=self.unidad, nombre="Alcatraz")
        self.bisonte = Compania.objects.create(unidad=self.unidad, nombre="Bisonte")
        self.apiay = Deposito.objects.create(nombre="Apiay")
        self.caruru = Deposito.objects.create(nombre="Caruru")
        peloton_a = Peloton.objects.create(compania=self.alcatraz, nombre="Alcatraz 1")
        peloton_b = Peloton.objects.create(compania=self.bisonte, nombre="Bisonte 1")
        self.soldado_a = Soldado.objects.create(
            apellidos_nombres="Rada Pedro", compania=self.alcatraz, peloton=peloton_a
        )
        self.soldado_b = Soldado.objects.create(
            apellidos_nombres="Gómez Luis", compania=self.bisonte, peloton=peloton_b
        )
        self.fusil = TipoArmamento.objects.create(
            nombre="FUSIL GALIL", control=TipoArmamento.Control.SERIE
        )
        self.cartucho = TipoArmamento.objects.create(
            nombre="CARTUCHO 5.56", control=TipoArmamento.Control.CANTIDAD
        )
        self.a_apiay = self._arma("A-APIAY", self.alcatraz, self.apiay)
        self.a_caruru = self._arma("A-CARURU", self.alcatraz, self.caruru)
        self.b_apiay = self._arma("B-APIAY", self.bisonte, self.apiay)
        self.a_en_mano = self._arma("A-MANO", self.alcatraz, self.apiay)
        self.usuario = get_user_model().objects.create_user(
            email="admin@example.com", password="x", role=get_user_model().Role.ADMIN
        )
        self.a_en_mano.entregar(soldado=self.soldado_a, usuario=self.usuario)
        self.client.force_login(self.usuario)

    def _arma(self, serie, compania, deposito):
        return Armamento.objects.create(
            numero_serie=serie, tipo=self.fusil, compania=compania,
            ubicacion=Armamento.Ubicacion.DEPOSITO, deposito=deposito,
        )

    def _seleccionar(self, compania=None, deposito=None):
        session = self.client.session
        for key, obj in ((SESSION_KEY, compania), (SESSION_KEY_DEPOSITO, deposito)):
            if obj:
                session[key] = obj.pk
            else:
                session.pop(key, None)
        session.save()

    # --- Pantalla de selección -------------------------------------------

    def test_selector_muestra_companias_y_depositos(self):
        response = self.client.get(reverse("inventory:elegir_compania"))
        self.assertContains(response, "Compañías")
        self.assertContains(response, "Depósitos")
        self.assertContains(response, "ALCATRAZ")
        self.assertContains(response, "CARURU")
        # Apiay: A-APIAY y B-APIAY en depósito; A-MANO está en mano.
        self.assertContains(response, "2 armas en depósito")

    def test_elegir_solo_deposito(self):
        response = self.client.post(
            reverse("inventory:elegir_compania"), {"compania": "", "deposito": self.apiay.pk}
        )
        self.assertRedirects(response, reverse("inventory:armamento_list"))
        self.assertEqual(self.client.session[SESSION_KEY_DEPOSITO], self.apiay.pk)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_elegir_compania_y_deposito(self):
        self.client.post(
            reverse("inventory:elegir_compania"),
            {"compania": self.alcatraz.pk, "deposito": self.caruru.pk},
        )
        self.assertEqual(self.client.session[SESSION_KEY], self.alcatraz.pk)
        self.assertEqual(self.client.session[SESSION_KEY_DEPOSITO], self.caruru.pk)

    def test_sin_ninguna_seleccion_muestra_error_y_no_guarda(self):
        response = self.client.post(
            reverse("inventory:elegir_compania"), {"compania": "", "deposito": ""}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elija al menos una compañía o un depósito.")
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY_DEPOSITO, self.client.session)

    def test_desmarcar_compania_la_quita_de_la_sesion(self):
        self._seleccionar(self.alcatraz, self.apiay)
        self.client.post(
            reverse("inventory:elegir_compania"), {"compania": "", "deposito": self.apiay.pk}
        )
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.session[SESSION_KEY_DEPOSITO], self.apiay.pk)

    def test_con_solo_deposito_el_middleware_no_redirige(self):
        self._seleccionar(deposito=self.apiay)
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertEqual(response.status_code, 200)

    def test_header_muestra_compania_y_deposito(self):
        self._seleccionar(deposito=self.apiay)
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, "Todas · Apiay")

    # --- Listados ------------------------------------------------------

    def test_inventario_con_deposito_solo_muestra_lo_que_esta_en_el(self):
        self._seleccionar(deposito=self.apiay)
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, "A-APIAY")
        self.assertContains(response, "B-APIAY")
        self.assertNotContains(response, "A-CARURU")
        self.assertNotContains(response, "A-MANO")
        self.assertEqual(response.context["kpi_en_mano"], 0)
        self.assertEqual(response.context["kpi_en_deposito"], 2)

    def test_inventario_con_compania_y_deposito_es_la_interseccion(self):
        self._seleccionar(self.alcatraz, self.apiay)
        response = self.client.get(reverse("inventory:armamento_list"))
        self.assertContains(response, "A-APIAY")
        self.assertNotContains(response, "B-APIAY")
        self.assertNotContains(response, "A-CARURU")
        self.assertContains(response, "Compañía Alcatraz · Depósito Apiay")

    def test_ver_todas_quita_ambos_filtros(self):
        self._seleccionar(self.alcatraz, self.apiay)
        response = self.client.get(reverse("inventory:armamento_list"), {"todas": "1"})
        for serie in ("A-APIAY", "B-APIAY", "A-CARURU", "A-MANO"):
            self.assertContains(response, serie)

    def test_soldados_no_se_filtran_por_deposito(self):
        self._seleccionar(deposito=self.apiay)
        response = self.client.get(reverse("inventory:soldado_list"))
        self.assertContains(response, "Rada Pedro")
        self.assertContains(response, "Gómez Luis")

    def test_municion_filtra_por_deposito_y_el_selector_lo_puede_quitar(self):
        Existencia.objects.create(
            tipo=self.cartucho, compania=self.alcatraz, deposito=self.apiay,
            lote="L-APIAY", cantidad=100,
        )
        Existencia.objects.create(
            tipo=self.cartucho, compania=self.alcatraz, deposito=self.caruru,
            lote="L-CARURU", cantidad=100,
        )
        self._seleccionar(deposito=self.apiay)
        response = self.client.get(reverse("inventory:existencia_list"))
        self.assertContains(response, "L-APIAY")
        self.assertNotContains(response, "L-CARURU")

        response = self.client.get(reverse("inventory:existencia_list"), {"deposito": ""})
        self.assertContains(response, "L-CARURU")

    def test_prestamos_filtran_por_deposito(self):
        for deposito, lote in ((self.apiay, "P-APIAY"), (self.caruru, "P-CARURU")):
            Existencia.objects.create(
                tipo=self.cartucho, compania=self.alcatraz, deposito=deposito,
                lote=lote, cantidad=100,
            )
            prestamo = Prestamo(
                tipo=self.cartucho, deposito=deposito, lote=lote, cantidad=10,
                compania_origen=self.alcatraz, compania_destino=self.bisonte,
                usuario=self.usuario,
            )
            prestamo.full_clean()
            prestamo.save()
        self._seleccionar(deposito=self.caruru)
        response = self.client.get(reverse("inventory:prestamo_list"))
        self.assertContains(response, "P-CARURU")
        self.assertNotContains(response, "P-APIAY")

    def test_movimientos_con_deposito_muestran_solo_lo_que_lo_toca(self):
        self.a_caruru.entregar(soldado=self.soldado_a, usuario=self.usuario)
        self.a_en_mano.devolver(deposito=self.apiay, usuario=self.usuario)
        self._seleccionar(deposito=self.apiay)
        response = self.client.get(reverse("inventory:movimiento_list"))
        # La devolución a Apiay sí; la entrega (sin depósito) no.
        self.assertContains(response, "A-MANO")
        self.assertNotContains(response, "A-CARURU")

    def test_municion_asignada_filtra_por_deposito_de_origen(self):
        en_apiay = Existencia.objects.create(
            tipo=self.cartucho, compania=self.alcatraz, deposito=self.apiay, cantidad=50
        )
        en_caruru = Existencia.objects.create(
            tipo=self.cartucho, compania=self.bisonte, deposito=self.caruru, cantidad=50
        )
        en_apiay.entregar(soldado=self.soldado_a, cantidad=5, usuario=self.usuario)
        en_caruru.entregar(soldado=self.soldado_b, cantidad=5, usuario=self.usuario)
        self._seleccionar(deposito=self.apiay)
        response = self.client.get(reverse("inventory:existencia_asignada_list"))
        self.assertContains(response, "Rada Pedro")
        self.assertNotContains(response, "Gómez Luis")

    # --- Formularios: preseleccionados, pero editables -------------------

    def test_devolver_arma_preselecciona_el_deposito(self):
        self._seleccionar(deposito=self.caruru)
        response = self.client.get(
            reverse("inventory:armamento_devolver", args=[self.a_en_mano.pk])
        )
        self.assertContains(response, f'<option value="{self.caruru.pk}" selected>')
        self.assertContains(response, f'<option value="{self.apiay.pk}">')

    def test_formularios_de_alta_y_prestamo_preseleccionan_el_alcance(self):
        self._seleccionar(self.bisonte, self.caruru)
        expected = {"compania": self.bisonte.pk, "deposito": self.caruru.pk}
        for url_name in ("inventory:armamento_crear", "inventory:existencia_crear"):
            form = self.client.get(reverse(url_name)).context["form"]
            self.assertEqual(form.initial, expected)
            self.assertEqual(form.fields["deposito"].queryset.count(), 2)

        form = self.client.get(reverse("inventory:prestamo_transferir")).context["form"]
        self.assertEqual(
            form.initial, {"compania_origen": self.bisonte.pk, "deposito": self.caruru.pk}
        )


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class RenombresTests(TestCase):
    """Issue #26: el módulo de existencias se llama "Consumo" en la UI y el
    login muestra el acrónimo SIGA completo."""

    def test_login_muestra_el_acronimo_completo(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, "Sistema de Inventario y Gestión de Armamento")

    def test_navegacion_y_pantalla_dicen_consumo(self):
        unidad = Unidad.objects.create(nombre="Batallón de Prueba")
        compania = Compania.objects.create(unidad=unidad, nombre="Alcatraz")
        usuario = get_user_model().objects.create_user(email="enlace@example.com", password="x")
        self.client.force_login(usuario)
        session = self.client.session
        session[SESSION_KEY] = compania.pk
        session.save()

        response = self.client.get(reverse("inventory:existencia_list"))
        self.assertContains(response, ">Consumo</h1>")
        self.assertContains(response, ">Consumo asignado</a>")
        self.assertNotContains(response, "Munición")
