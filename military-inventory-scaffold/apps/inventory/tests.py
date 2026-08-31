import json
import os
import tempfile
from datetime import date

import openpyxl
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Armamento,
    CampoPersonalizado,
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
        self.assertEqual(TipoArmamento.objects.count(), 29)

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
