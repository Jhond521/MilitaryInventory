"""Issues #33/#34 (RF-26/RF-27): full backup to Excel, and restore from it."""
import json
from datetime import date, timedelta
from io import BytesIO, StringIO
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.inventory import respaldo
from apps.inventory.models import (
    Armamento,
    CampoPersonalizado,
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
EXPORTAR = reverse("inventory:respaldo_exportar")
REESTABLECER = reverse("inventory:respaldo_reestablecer")
CONFIRMAR = reverse("inventory:respaldo_confirmar")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HOJAS_ESPERADAS = [
    "_meta", "Unidad", "Compania", "Deposito", "Peloton", "TipoArmamento",
    "CampoPersonalizado", "Usuario", "Soldado", "Armamento", "Movimiento", "Existencia",
    "ExistenciaAsignada", "MovimientoExistencia", "Prestamo", "DevolucionPrestamo",
]


def _conteos():
    return {h: m.objects.count() for h, m in respaldo.MODELOS_RESPALDO}


def _hoja(wb, nombre):
    filas = list(wb[nombre].iter_rows(values_only=True))
    return filas[0], filas[1:]


def _como_dicts(wb, nombre):
    encabezado, filas = _hoja(wb, nombre)
    return [dict(zip(encabezado, f, strict=False)) for f in filas]


def _meta(wb):
    return {k: v for k, v in list(wb["_meta"].iter_rows(values_only=True))[1:]}


@override_settings(STORAGES=_PLAIN_STATIC_STORAGE)
class RespaldoBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="admin@example.com", password="clave-larga-1", role=User.Role.ADMIN,
            first_name="Ana", last_name="Admin",
        )
        cls.enlace = User.objects.create_user(
            email="enlace@example.com", password="clave-larga-1", role=User.Role.ENLACE
        )
        cls.consulta = User.objects.create_user(
            email="lector@example.com", password="clave-larga-1", role=User.Role.CONSULTA
        )
        u = Unidad.objects.create(nombre="Batallón 52")
        cls.c1 = Compania.objects.create(unidad=u, nombre="Alcatraz")
        cls.c2 = Compania.objects.create(unidad=u, nombre="Bisonte")
        cls.dep = Deposito.objects.create(nombre="Apiay", descripcion="=CMD|' /C calc'!A0")
        p1 = Peloton.objects.create(compania=cls.c1, nombre="P1")
        p2 = Peloton.objects.create(compania=cls.c2, nombre="P1")
        cls.fusil = TipoArmamento.objects.create(nombre="Fusil Galil", control="SERIE")
        cls.mun = TipoArmamento.objects.create(nombre="Cartucho 5.56", control="CANTIDAD")
        CampoPersonalizado.objects.create(nombre="Mira", tipo="TEXTO")
        cls.s1 = Soldado.objects.create(
            apellidos_nombres="Peña Núñez José", cedula="1001", compania=cls.c1, peloton=p1
        )
        cls.s_sin_cedula = Soldado.objects.create(
            apellidos_nombres="Antiguo Sin Cédula", compania=cls.c1, peloton=p1
        )
        cls.s2 = Soldado.objects.create(
            apellidos_nombres="Bravo Otra", cedula="2002", compania=cls.c2, peloton=p2
        )
        cls.a_mano = Armamento.objects.create(
            numero_serie="SER-1", tipo=cls.fusil, compania=cls.c1, ubicacion="DEPOSITO",
            deposito=cls.dep, datos_extra={"Mira": "Óptica señal"},
        )
        cls.a_mano.entregar(soldado=cls.s1, usuario=cls.admin, observacion="+57 entrega")
        cls.a_dep = Armamento.objects.create(
            numero_serie="SER-2", tipo=cls.fusil, compania=cls.c1, ubicacion="DEPOSITO",
            deposito=cls.dep,
        )
        cls.a_prestada = Armamento.objects.create(
            numero_serie="SER-3", tipo=cls.fusil, compania=cls.c1, ubicacion="DEPOSITO",
            deposito=cls.dep,
        )
        cls.a_prestada.prestar(compania=cls.c2, usuario=cls.enlace)
        cls.a_otra = Armamento.objects.create(
            numero_serie="OTRA-1", tipo=cls.fusil, compania=cls.c2, ubicacion="DEPOSITO",
            deposito=cls.dep,
        )
        cls.ex = Existencia.objects.create(
            tipo=cls.mun, compania=cls.c1, deposito=cls.dep, lote="L-1", cantidad=100
        )
        cls.ex.entregar(soldado=cls.s1, cantidad=10, usuario=cls.admin)
        pr = Prestamo(
            tipo=cls.mun, deposito=cls.dep, lote="L-1", cantidad=20, compania_origen=cls.c1,
            compania_destino=cls.c2, usuario=cls.enlace,
        )
        pr.full_clean()
        pr.save()
        pr.devolver(cantidad=5, usuario=cls.enlace)
        cls.prestamo = pr
        # Old dates, so a restore that loses them (auto_now_add) shows up.
        hace = timezone.now() - timedelta(days=40)
        Movimiento.objects.update(fecha=hace)
        MovimientoExistencia.objects.update(fecha=hace)
        Prestamo.objects.update(fecha=hace)
        DevolucionPrestamo.objects.update(fecha=hace)
        Armamento.objects.update(creado=hace, actualizado=hace)

    def entrar(self, user=None):
        self.client.force_login(user or self.admin)
        s = self.client.session
        s[SESSION_KEY] = self.c1.pk
        s.save()

    def exportar_bytes(self):
        self.entrar()
        r = self.client.get(EXPORTAR)
        self.assertEqual(r.status_code, 200)
        return r.content

    def libro(self, contenido):
        return load_workbook(BytesIO(contenido), read_only=True)

    def subir(self, contenido, nombre="respaldo.xlsx"):
        return self.client.post(
            REESTABLECER, {"archivo": SimpleUploadedFile(nombre, contenido, content_type=XLSX)}
        )

    def restaurar(self, contenido):
        r = self.subir(contenido)
        self.assertEqual(r.status_code, 200, getattr(r, "context", {}) and r.context.get("errores"))
        return self.client.post(CONFIRMAR, {"confirmacion": "REESTABLECER"})


# ------------------------------------------------------------------ #33 export


class ExportarRespaldoTests(RespaldoBase):
    def test_tarjeta_solo_para_admin(self):
        """#33 AC-1 — Ajustes muestra "Exportar respaldo" solo al ADMIN."""
        self.entrar()
        self.assertContains(self.client.get(reverse("inventory:ajustes")), f'href="{EXPORTAR}"')
        for u in (self.enlace, self.consulta):
            self.entrar(u)
            r = self.client.get(reverse("inventory:ajustes"))
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, f'href="{EXPORTAR}"')
            self.assertNotContains(r, "Exportar respaldo")

    def test_exportar_prohibido_para_enlace_y_consulta(self):
        """#33 AC-2 — ENLACE y CONSULTA reciben 403; sin sesión, al login."""
        for u in (self.enlace, self.consulta):
            self.entrar(u)
            self.assertEqual(self.client.get(EXPORTAR).status_code, 403)
        self.client.logout()
        r = self.client.get(EXPORTAR)
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])

    def test_descarga_xlsx_con_nombre(self):
        """#33 AC-3 — 200, Content-Type de xlsx, attachment SIGA-respaldo-AAAAMMDD-HHMM.xlsx."""
        self.entrar()
        r = self.client.get(EXPORTAR)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], XLSX)
        self.assertRegex(
            r["Content-Disposition"], r'^attachment; filename="SIGA-respaldo-\d{8}-\d{4}\.xlsx"$'
        )
        self.libro(r.content)  # opens with openpyxl

    def test_hojas_y_encabezados(self):
        """#33 AC-4 — _meta + 15 hojas en orden; fila 1 = nombres técnicos, empieza por id."""
        wb = self.libro(self.exportar_bytes())
        self.assertEqual(wb.sheetnames, HOJAS_ESPERADAS)
        for hoja, model in respaldo.MODELOS_RESPALDO:
            encabezado, _ = _hoja(wb, hoja)
            self.assertEqual(encabezado[0], "id", hoja)
            self.assertEqual(list(encabezado), respaldo.columnas(model), hoja)
        encabezado, _ = _hoja(wb, "Armamento")
        for col in ("numero_serie", "tipo_id", "compania_id", "compania_en_prestamo_id"):
            self.assertIn(col, encabezado)

    def test_conteos_y_meta(self):
        """#33 AC-5.

        filas por hoja == count() == _meta; _meta con formato, fecha, correo, migraciones.
        """
        wb = self.libro(self.exportar_bytes())
        meta = _meta(wb)
        for hoja, model in respaldo.MODELOS_RESPALDO:
            _, filas = _hoja(wb, hoja)
            self.assertEqual(len(filas), model.objects.count(), hoja)
            self.assertEqual(meta[f"filas_{hoja}"], model.objects.count(), hoja)
        self.assertEqual(meta["formato"], 1)
        self.assertEqual(meta["generado_por"], "admin@example.com")
        self.assertIsNotNone(timezone.datetime.fromisoformat(meta["generado"]).tzinfo)
        self.assertEqual(meta["migracion_inventory"], respaldo.ultimas_migraciones()["inventory"])
        self.assertEqual(meta["migracion_accounts"], respaldo.ultimas_migraciones()["accounts"])
        self.assertTrue(meta["migracion_accounts"].startswith("0002"))

    def test_relaciones_por_id(self):
        """#33 AC-6 — FKs como <campo>_id; cada id no vacío existe en su hoja."""
        wb = self.libro(self.exportar_bytes())
        armas = {a["numero_serie"]: a for a in _como_dicts(wb, "Armamento")}
        en_mano = armas["SER-1"]
        self.assertEqual(en_mano["compania_id"], self.c1.pk)
        self.assertEqual(en_mano["soldado_id"], self.s1.pk)
        self.assertEqual(en_mano["tipo_id"], self.fusil.pk)
        self.assertIsNone(en_mano["deposito_id"])
        self.assertEqual(armas["SER-3"]["compania_en_prestamo_id"], self.c2.pk)
        (pr,) = _como_dicts(wb, "Prestamo")
        self.assertEqual(
            (pr["compania_origen_id"], pr["compania_destino_id"], pr["deposito_id"],
             pr["tipo_id"], pr["usuario_id"]),
            (self.c1.pk, self.c2.pk, self.dep.pk, self.mun.pk, self.enlace.pk),
        )
        hoja_de = {m: h for h, m in respaldo.MODELOS_RESPALDO}
        ids = {h: {r["id"] for r in _como_dicts(wb, h)} for h in respaldo.HOJAS}
        for hoja, model in respaldo.MODELOS_RESPALDO:
            for f in respaldo.campos(model):
                if not f.is_relation:
                    continue
                for fila in _como_dicts(wb, hoja):
                    if fila[f.attname] is not None:
                        self.assertIn(fila[f.attname], ids[hoja_de[f.related_model]])

    def test_valores_intactos(self):
        """#33 AC-7.

        tildes/ñ, texto con = como texto, JSON sin escapar, ISO con zona, cédula nula vacía.
        """
        wb = self.libro(self.exportar_bytes())
        soldados = {s["id"]: s for s in _como_dicts(wb, "Soldado")}
        self.assertEqual(soldados[self.s1.pk]["apellidos_nombres"], "Peña Núñez José")
        self.assertIsNone(soldados[self.s_sin_cedula.pk]["cedula"])
        (dep,) = _como_dicts(wb, "Deposito")
        self.assertEqual(dep["descripcion"], "=CMD|' /C calc'!A0")
        celda = next(
            c for c in list(wb["Deposito"].iter_rows(min_row=2))[0] if c.value == dep["descripcion"]
        )
        self.assertEqual(celda.data_type, "s")
        arma = next(a for a in _como_dicts(wb, "Armamento") if a["numero_serie"] == "SER-1")
        self.assertIn("Óptica señal", arma["datos_extra"])
        self.assertEqual(json.loads(arma["datos_extra"]), {"Mira": "Óptica señal"})
        mov = _como_dicts(wb, "Movimiento")[0]
        fecha = timezone.datetime.fromisoformat(mov["fecha"])
        self.assertIsNotNone(fecha.tzinfo)
        self.assertRegex(mov["fecha"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*-05:00$")
        obs = {m["observacion"] for m in _como_dicts(wb, "Movimiento")}
        self.assertIn("+57 entrega", obs)

    def test_usuario_sin_password(self):
        """#33 AC-8 — hoja Usuario: exactamente las 7 columnas, sin hash."""
        contenido = self.exportar_bytes()
        wb = self.libro(contenido)
        encabezado, filas = _hoja(wb, "Usuario")
        self.assertEqual(
            list(encabezado),
            ["id", "email", "first_name", "last_name", "role", "is_active", "date_joined"],
        )
        hashes = [u.password for u in User.objects.all()]
        for fila in filas:
            for valor in fila:
                self.assertNotIn(valor, hashes)
        for h in hashes:
            self.assertNotIn(h.encode(), contenido)

    def test_exportar_no_cambia_nada(self):
        """#33 AC-9 — conteos iguales antes/después; ningún Movimiento nuevo."""
        antes = _conteos()
        self.exportar_bytes()
        self.assertEqual(_conteos(), antes)

    def test_respaldo_completo_ignora_alcance(self):
        """#33 AC-10 — con compañía de trabajo, salen también las otras compañías."""
        wb = self.libro(self.exportar_bytes())  # session compañía = c1
        series = {a["numero_serie"] for a in _como_dicts(wb, "Armamento")}
        self.assertIn("OTRA-1", series)
        self.assertIn(self.s2.pk, {s["id"] for s in _como_dicts(wb, "Soldado")})

    def test_todo_modelo_de_inventory_esta_en_el_respaldo(self):
        """#33 AC-12 — un modelo nuevo de inventory sin hoja de respaldo rompe este test."""
        modelos = set(apps.get_app_config("inventory").get_models())
        self.assertEqual(modelos, {m for _, m in respaldo.MODELOS_INVENTARIO})

    def test_sin_migraciones_pendientes(self):
        """#33 AC-12 / #34 AC-14 — makemigrations --check limpio."""
        call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())


# ----------------------------------------------------------------- #34 restore


class ReestablecerRespaldoTests(RespaldoBase):
    def _modificar_datos(self):
        nueva = Armamento.objects.create(
            numero_serie="NUEVA-9", tipo=self.fusil, compania=self.c1, ubicacion="DEPOSITO",
            deposito=self.dep,
        )
        Armamento.objects.get(pk=self.a_dep.pk).entregar(soldado=self.s1, usuario=self.admin)
        Soldado.objects.filter(pk=self.s2.pk).delete()
        pr = Prestamo(
            tipo=self.mun, deposito=self.dep, lote="L-1", cantidad=3, compania_origen=self.c1,
            compania_destino=self.c2, usuario=self.admin,
        )
        pr.full_clean()
        pr.save()
        return nueva

    def test_tarjeta_solo_para_admin(self):
        """#34 AC-1 — Ajustes muestra "Reestablecer respaldo" solo al ADMIN."""
        self.entrar()
        self.assertContains(
            self.client.get(reverse("inventory:ajustes")), f'href="{REESTABLECER}"'
        )
        for u in (self.enlace, self.consulta):
            self.entrar(u)
            r = self.client.get(reverse("inventory:ajustes"))
            self.assertNotContains(r, f'href="{REESTABLECER}"')
            self.assertNotContains(r, "Reestablecer respaldo")

    def test_reestablecer_prohibido_para_enlace_y_consulta(self):
        """#34 AC-2 — GET/POST como ENLACE o CONSULTA → 403 sin cambios; sin sesión → login."""
        contenido = self.exportar_bytes()
        Armamento.objects.create(
            numero_serie="NUEVA-9", tipo=self.fusil, compania=self.c1, ubicacion="DEPOSITO",
            deposito=self.dep,
        )
        antes = _conteos()
        for u in (self.enlace, self.consulta):
            self.entrar(u)
            self.assertEqual(self.client.get(REESTABLECER).status_code, 403)
            self.assertEqual(self.subir(contenido).status_code, 403)
            r = self.client.post(CONFIRMAR, {"confirmacion": "REESTABLECER"})
            self.assertEqual(r.status_code, 403)
        self.assertEqual(_conteos(), antes)
        self.client.logout()
        for r in (self.client.get(REESTABLECER), self.client.post(CONFIRMAR)):
            self.assertEqual(r.status_code, 302)
            self.assertIn(reverse("accounts:login"), r["Location"])

    def test_ida_y_vuelta_identica(self):
        """#34 AC-3.

        exportar, modificar, restaurar y re-exportar da hojas idénticas celda por celda.
        """
        original = self.exportar_bytes()
        self._modificar_datos()
        r = self.restaurar(original)
        self.assertEqual(r.status_code, 302)
        de_nuevo = self.exportar_bytes()
        wb1, wb2 = self.libro(original), self.libro(de_nuevo)
        for hoja in respaldo.HOJAS:
            self.assertEqual(
                list(wb1[hoja].iter_rows(values_only=True)),
                list(wb2[hoja].iter_rows(values_only=True)),
                hoja,
            )

    def test_restaurar_no_aplica_logica_de_negocio(self):
        """#34 AC-4.

        saldos, ubicaciones y préstamos quedan como en el archivo; no hay movimientos de más.
        """
        original = self.exportar_bytes()
        esperado = {
            "existencias": dict(Existencia.objects.values_list("pk", "cantidad")),
            "asignadas": dict(ExistenciaAsignada.objects.values_list("pk", "cantidad")),
            "devuelto": dict(Prestamo.objects.values_list("pk", "cantidad_devuelta")),
            "armas": {
                a.pk: (a.ubicacion, a.soldado_id, a.deposito_id, a.compania_en_prestamo_id)
                for a in Armamento.objects.all()
            },
            "movs": (Movimiento.objects.count(), MovimientoExistencia.objects.count()),
        }
        self._modificar_datos()
        self.restaurar(original)
        self.assertEqual(dict(Existencia.objects.values_list("pk", "cantidad")),
                         esperado["existencias"])
        self.assertEqual(dict(ExistenciaAsignada.objects.values_list("pk", "cantidad")),
                         esperado["asignadas"])
        self.assertEqual(dict(Prestamo.objects.values_list("pk", "cantidad_devuelta")),
                         esperado["devuelto"])
        self.assertEqual(
            {a.pk: (a.ubicacion, a.soldado_id, a.deposito_id, a.compania_en_prestamo_id)
             for a in Armamento.objects.all()},
            esperado["armas"],
        )
        self.assertEqual(
            (Movimiento.objects.count(), MovimientoExistencia.objects.count()), esperado["movs"]
        )

    def test_secuencias_reajustadas(self):
        """#34 AC-5 — tras restaurar, un registro nuevo recibe id mayor al máximo del archivo."""
        original = self.exportar_bytes()
        self.restaurar(original)
        maximo = max(Soldado.objects.values_list("pk", flat=True))
        s = Soldado.objects.create(
            apellidos_nombres="Nuevo", cedula="3003", compania=self.c1,
            peloton=Peloton.objects.filter(compania=self.c1).first(),
        )
        self.assertGreater(s.pk, maximo)
        m = Armamento.objects.get(pk=self.a_dep.pk).entregar(soldado=s, usuario=self.admin)
        movs = _como_dicts(self.libro(original), "Movimiento")
        self.assertGreater(m.pk, max(r["id"] for r in movs))

    def _archivo_modificado(self, original, cambio):
        """Rewrites the backup with `cambio(dict_of_sheets)` applied."""
        wb_in = load_workbook(BytesIO(original))
        hojas = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb_in}
        cambio(hojas)
        wb = Workbook()
        wb.remove(wb.active)
        for nombre, filas in hojas.items():
            ws = wb.create_sheet(nombre)
            for f in filas:
                ws.append(f)
                for c in ws[ws.max_row]:
                    if isinstance(c.value, str):
                        c.data_type = "s"
        out = BytesIO()
        wb.save(out)
        return out.getvalue()

    def _col(self, hojas, hoja, columna):
        return hojas[hoja][0].index(columna)

    def test_archivos_invalidos_rechazados_sin_cambios(self):
        """#34 AC-6.

        (a) a (g): rechazo en el paso 1 con hoja/fila/columna en español, sin cambios.
        """
        original = self.exportar_bytes()

        def sin_meta(h):
            del h["_meta"]

        def formato_2(h):
            h["_meta"][1][1] = 2

        def otra_migracion(h):
            for fila in h["_meta"]:
                if fila[0] == "migracion_inventory":
                    fila[1] = "0001_initial"

        def sin_hoja(h):
            del h["Prestamo"]

        def sin_columna(h):
            i = self._col(h, "Armamento", "numero_serie")
            for fila in h["Armamento"]:
                del fila[i]

        def fk_rota(h):
            h["Armamento"][1][self._col(h, "Armamento", "compania_id")] = 9999

        def serie_repetida(h):
            i = self._col(h, "Armamento", "numero_serie")
            h["Armamento"][2][i] = h["Armamento"][1][i]

        def fecha_mala(h):
            h["Movimiento"][1][self._col(h, "Movimiento", "fecha")] = "ayer por la tarde"

        casos = [
            ("a", b"esto no es un excel", "no es un Excel"),
            ("b", self._archivo_modificado(original, sin_meta), "Falta la hoja «_meta»"),
            ("b2", self._archivo_modificado(original, formato_2), "Formato de respaldo «2»"),
            ("c", self._archivo_modificado(original, otra_migracion), "otra versión de la base"),
            ("d", self._archivo_modificado(original, sin_hoja), "Faltan hojas: Prestamo"),
            ("d2", self._archivo_modificado(original, sin_columna),
             "Hoja Armamento, fila 1: columnas incorrectas (faltan numero_serie)"),
            ("e", self._archivo_modificado(original, fk_rota),
             "Hoja Armamento, fila 2, columna compania_id: el id 9999 no existe en la hoja "
             "Compania"),
            ("f", self._archivo_modificado(original, serie_repetida),
             "Hoja Armamento, fila 3, columna numero_serie: valor repetido"),
            ("g", self._archivo_modificado(original, fecha_mala),
             "Hoja Movimiento, fila 2, columna fecha: «ayer por la tarde» no es una fecha"),
        ]
        Armamento.objects.create(
            numero_serie="NUEVA-9", tipo=self.fusil, compania=self.c1, ubicacion="DEPOSITO",
            deposito=self.dep,
        )
        antes = _conteos()
        for caso, contenido, mensaje in casos:
            with self.subTest(caso=caso):
                r = self.subir(contenido)
                self.assertEqual(r.status_code, 400)
                self.assertContains(r, "No se puede reestablecer este archivo", status_code=400)
                self.assertTrue(
                    any(mensaje in e for e in r.context["errores"]), r.context["errores"]
                )
                self.assertEqual(_conteos(), antes)

    def test_regla_de_dominio_rechazada(self):
        """#34 AC-6 — un arma EN_MANO sin soldado se rechaza en la prueba en seco, con su fila."""
        original = self.exportar_bytes()

        def sin_soldado(h):
            i = self._col(h, "Armamento", "soldado_id")
            for fila in h["Armamento"][1:]:
                if fila[self._col(h, "Armamento", "ubicacion")] == "EN_MANO":
                    fila[i] = None

        antes = _conteos()
        r = self.subir(self._archivo_modificado(original, sin_soldado))
        self.assertEqual(r.status_code, 400)
        self.assertTrue(
            any("Hoja Armamento, fila" in e and "soldado" in e for e in r.context["errores"])
        )
        self.assertEqual(_conteos(), antes)

    def test_vista_previa_sin_cambios(self):
        """#34 AC-7.

        archivo válido → tabla actual→archivo, fecha/correo del _meta, aviso; nada cambió.
        """
        original = self.exportar_bytes()
        self._modificar_datos()
        antes = _conteos()
        r = self.subir(original)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "inventory/respaldo_confirmar.html")
        filas = {f["hoja"]: f for f in r.context["filas"]}
        self.assertEqual(filas["Armamento"]["actual"], antes["Armamento"])
        self.assertEqual(filas["Armamento"]["archivo"], antes["Armamento"] - 1)
        self.assertContains(r, "Se reemplazarán TODOS los datos actuales")
        self.assertContains(r, "admin@example.com")
        self.assertContains(r, f"{antes['Armamento']} → {antes['Armamento'] - 1}")
        self.assertContains(r, timezone.localtime().strftime("%Y-%m-%d"))
        self.assertContains(r, f'href="{EXPORTAR}"')
        self.assertEqual(_conteos(), antes)

    def test_palabra_de_confirmacion_incorrecta(self):
        """#34 AC-8.

        sin REESTABLECER exacto no se restaura y se repite la vista previa con error.
        """
        original = self.exportar_bytes()
        nueva = self._modificar_datos()
        self.subir(original)
        for palabra in ("", "reestablecer", "SI"):
            r = self.client.post(CONFIRMAR, {"confirmacion": palabra})
            self.assertEqual(r.status_code, 200)
            self.assertTemplateUsed(r, "inventory/respaldo_confirmar.html")
            self.assertContains(r, "Escribe exactamente REESTABLECER")
            self.assertTrue(Armamento.objects.filter(pk=nueva.pk).exists())

    def test_cancelar_no_cambia_nada(self):
        original = self.exportar_bytes()
        nueva = self._modificar_datos()
        self.subir(original)
        r = self.client.post(CONFIRMAR, {"cancelar": "1"})
        self.assertRedirects(r, reverse("inventory:ajustes"))
        self.assertTrue(Armamento.objects.filter(pk=nueva.pk).exists())
        r = self.client.post(CONFIRMAR, {"confirmacion": "REESTABLECER"})
        self.assertEqual(r.status_code, 400)  # token discarded
        self.assertTrue(Armamento.objects.filter(pk=nueva.pk).exists())

    def test_todo_o_nada(self):
        """#34 AC-9 — si falla una inserción a mitad del paso 3, la BD queda como estaba."""
        original = self.exportar_bytes()
        nueva = self._modificar_datos()
        self.subir(original)
        antes = _conteos()
        cantidades = dict(Existencia.objects.values_list("pk", "cantidad"))
        with mock.patch.object(
            Prestamo.objects, "bulk_create", side_effect=IntegrityError("falla forzada")
        ):
            r = self.client.post(CONFIRMAR, {"confirmacion": "REESTABLECER"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(any("falla forzada" in e for e in r.context["errores"]))
        self.assertEqual(_conteos(), antes)
        self.assertTrue(Armamento.objects.filter(pk=nueva.pk).exists())
        self.assertEqual(dict(Existencia.objects.values_list("pk", "cantidad")), cantidades)

    def test_usuarios_por_correo(self):
        """#34 AC-10.

        existentes intactos, faltantes inactivos sin clave, nadie se borra, FKs por correo.
        """
        fantasma = User.objects.create_user(
            email="fantasma@example.com", password="clave-larga-1", role=User.Role.ENLACE
        )
        m = Movimiento.objects.filter(armamento=self.a_mano).first()
        Movimiento.objects.filter(pk=m.pk).update(usuario=fantasma)
        original = self.exportar_bytes()
        # The ghost user disappears from this DB and the enlace changes.
        Movimiento.objects.filter(pk=m.pk).update(usuario=self.admin)
        fantasma.delete()
        self.enlace.role = User.Role.CONSULTA
        self.enlace.is_active = False
        self.enlace.set_password("otra-clave-larga-2")
        self.enlace.save()
        nuevo = User.objects.create_user(email="nuevo@example.com", password="x-clave-larga-3")
        hash_enlace = self.enlace.password

        r = self.restaurar(original)
        self.assertEqual(r.status_code, 302)
        enlace = User.objects.get(pk=self.enlace.pk)
        self.assertEqual(
            (enlace.role, enlace.is_active, enlace.password),
            (User.Role.CONSULTA, False, hash_enlace),
        )
        self.assertTrue(User.objects.filter(pk=nuevo.pk).exists())
        recreado = User.objects.get(email="fantasma@example.com")
        self.assertFalse(recreado.is_active)
        self.assertFalse(recreado.has_usable_password())
        self.assertEqual(Movimiento.objects.get(pk=m.pk).usuario, recreado)
        self.assertEqual(
            Prestamo.objects.get(pk=self.prestamo.pk).usuario.email, "enlace@example.com"
        )
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_textos_y_json_identicos(self):
        """#34 AC-11 — texto con =, tildes, ñ y datos_extra vuelven idénticos."""
        original = self.exportar_bytes()
        Deposito.objects.filter(pk=self.dep.pk).update(descripcion="cambiada")
        Soldado.objects.filter(pk=self.s1.pk).update(apellidos_nombres="Otro")
        Armamento.objects.filter(pk=self.a_mano.pk).update(datos_extra={})
        self.restaurar(original)
        self.assertEqual(Deposito.objects.get(pk=self.dep.pk).descripcion, "=CMD|' /C calc'!A0")
        self.assertEqual(Soldado.objects.get(pk=self.s1.pk).apellidos_nombres, "Peña Núñez José")
        self.assertEqual(
            Armamento.objects.get(pk=self.a_mano.pk).datos_extra, {"Mira": "Óptica señal"}
        )
        self.assertIsNone(Soldado.objects.get(pk=self.s_sin_cedula.pk).cedula)
        self.assertEqual(
            Armamento.objects.get(pk=self.a_mano.pk).creado.date(),
            (timezone.now() - timedelta(days=40)).date(),
        )

    def test_mensaje_final_y_sesion(self):
        """#34 AC-12.

        redirige con "Respaldo del … reestablecido: N registros"; sesión activa; compañía
        inexistente → /compania/.
        """
        original = self.exportar_bytes()
        total = sum(_conteos().values())
        r = self.restaurar(original)
        self.assertRedirects(r, reverse("inventory:ajustes"), fetch_redirect_response=False)
        r = self.client.get(reverse("inventory:ajustes"))
        self.assertRegex(
            r.content.decode(),
            rf"Respaldo del \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}} "
            rf"reestablecido: {total} registros",
        )
        # A compañía created after the backup no longer exists once it's restored.
        extra = Compania.objects.create(unidad=self.c1.unidad, nombre="Temporal")
        s = self.client.session
        s[SESSION_KEY] = extra.pk
        s.save()
        r = self.restaurar(original)
        self.assertRedirects(r, reverse("inventory:ajustes"), fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)
        r = self.client.get(reverse("inventory:ajustes"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(reverse("inventory:elegir_compania")))

    def test_baja_y_fechas_sobreviven(self):
        """#34 AC-3 — un arma de baja (fecha_baja date) también vuelve igual."""
        self.a_dep.dar_de_baja(motivo="DANO", fecha=date(2026, 1, 15), usuario=self.admin)
        original = self.exportar_bytes()
        Armamento.objects.filter(pk=self.a_dep.pk).update(fecha_baja=date(2026, 2, 1))
        self.restaurar(original)
        self.assertEqual(Armamento.objects.get(pk=self.a_dep.pk).fecha_baja, date(2026, 1, 15))

    def test_prueba_en_seco_no_reajusta_secuencias(self):
        """#34 AC-5 — setval() de Postgres no se deshace con rollback: solo la restauración real
        reajusta las secuencias, nunca la validación del paso 1."""
        original = self.exportar_bytes()
        with mock.patch(
            "apps.inventory.respaldo.connection.ops.sequence_reset_sql", return_value=[]
        ) as reset:
            self.subir(original)
            reset.assert_not_called()
            self.client.post(CONFIRMAR, {"confirmacion": "REESTABLECER"})
            reset.assert_called_once()
