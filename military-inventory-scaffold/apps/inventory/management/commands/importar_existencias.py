"""Importa existencias por cantidad (munición, consumibles) desde un Excel
(RF-14, H-15).

Uso:
    python manage.py importar_existencias ruta/al/archivo.xlsx \
        [--deposito NOMBRE[,NOMBRE2]] [--dry-run]

Estructura real observada en el archivo de consumo de David
(`PROYECTO APP CONTROL MATERIAL DE CONSUMO.xlsx`, carpeta `test files/` —
RF-14, P-6 en docs/PRD.md, sin número de lote todavía):

- Una hoja por compañía, nombrada "CP <código>" — mismo mapeo de hoja a
  `Compania` que usa `importar_armamento` (ver `_excel_import_utils`).
- Un único encabezado por hoja ("No" / "MATERIAL" / "CARGOS SAP"), sin los
  bloques repetidos por categoría del archivo de armamento — "MATERIAL" debe
  coincidir (tras normalizar) con un `TipoArmamento` controlado por
  CANTIDAD; "CARGOS SAP" es la cantidad.
- Sin columna de depósito ni de lote en el archivo real: el lote queda en
  blanco (P-6, pendiente de que David lo agregue) y el depósito sale de
  `--deposito`, igual que en `importar_armamento` (uno o varios separados
  por coma, repartidos por turnos si son varios).
- Cada fila suma a la `Existencia` de (tipo, compañía, depósito, lote="") —
  si ya existía una existencia para esa combinación (de una carga previa o
  de los cascos SIN SERIE que carga `importar_armamento`), se le suma la
  cantidad en vez de reemplazarla.

Antes de crear/actualizar nada se valida el archivo completo (tipos o
depósitos no reconocidos, material o cantidad vacíos/negativos). Si hay
algún conflicto, no se modifica NINGÚN registro.
"""
from collections import defaultdict

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.models import Compania, Deposito, Existencia, TipoArmamento

from ._excel_import_utils import normalizar as _normalizar_base
from ._excel_import_utils import resolver_compania, resolver_depositos

COLUMNAS_MATERIAL = {"MATERIAL"}
COLUMNAS_CANTIDAD = {"CARGOS SAP"}


def normalizar(texto):
    return _normalizar_base(texto)


def _es_fila_encabezado(valores_normalizados):
    return bool(valores_normalizados & COLUMNAS_MATERIAL) and bool(
        valores_normalizados & COLUMNAS_CANTIDAD
    )


class Command(BaseCommand):
    help = "Importa existencias por cantidad (munición, consumibles) desde un Excel (RF-14)."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta al archivo .xlsx a importar.")
        parser.add_argument(
            "--deposito",
            default=None,
            help=(
                "Depósito(s) a usar (el archivo no trae columna de depósito). "
                "Uno o varios separados por coma; con varios, se reparten las "
                "filas por turnos entre ellos."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo valida y reporta; no crea ni actualiza nada.",
        )

    def handle(self, *args, **options):
        depositos_global = resolver_depositos(options["deposito"], Deposito)
        if not depositos_global:
            raise CommandError("Este archivo no trae depósito: usa --deposito.")

        ruta = options["archivo"]
        try:
            workbook = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        except FileNotFoundError as exc:
            raise CommandError(f"No se encontró el archivo: {ruta}") from exc

        try:
            advertencias, conflictos, filas_cantidad = self._leer_filas(
                workbook, depositos_global
            )
        finally:
            workbook.close()

        self._procesar(advertencias, conflictos, filas_cantidad, options["dry_run"])

    def _leer_filas(self, workbook, depositos_global):
        companias_por_nombre = {normalizar(c.nombre): c for c in Compania.objects.all()}
        tipos_por_nombre = {
            normalizar(t.nombre): t
            for t in TipoArmamento.objects.filter(control=TipoArmamento.Control.CANTIDAD)
        }

        advertencias = []
        conflictos = []
        filas_cantidad = defaultdict(int)  # (compania, tipo, deposito) -> cantidad
        contador_reparto = 0

        for hoja in workbook.worksheets:
            compania = resolver_compania(hoja.title, companias_por_nombre)
            if compania is None:
                advertencias.append(
                    f'Hoja "{hoja.title}" omitida: no coincide con ninguna compañía sembrada.'
                )
                continue

            columnas = None
            for num_fila, fila in enumerate(hoja.iter_rows(values_only=True), start=1):
                valores_no_none = [v for v in fila if v is not None]
                if not valores_no_none:
                    continue

                valores_normalizados = {normalizar(v) for v in valores_no_none}
                if _es_fila_encabezado(valores_normalizados):
                    columnas = {}
                    for indice, valor in enumerate(fila):
                        if valor is None:
                            continue
                        clave = normalizar(valor)
                        if clave in COLUMNAS_MATERIAL:
                            columnas["material"] = indice
                        elif clave in COLUMNAS_CANTIDAD:
                            columnas["cantidad"] = indice
                    continue

                if columnas is None:
                    continue  # fila antes del encabezado (p. ej. título/"No" suelto).

                referencia = f'hoja "{hoja.title}", fila {num_fila}'
                material_raw = (
                    fila[columnas["material"]] if columnas["material"] < len(fila) else None
                )
                if material_raw is None or not str(material_raw).strip():
                    continue  # fila sin material: separador o vacía, no es un conflicto.

                tipo = tipos_por_nombre.get(normalizar(material_raw))
                if tipo is None:
                    conflictos.append(
                        f'{referencia}: material no reconocido: "{material_raw}".'
                    )
                    continue

                cantidad_raw = (
                    fila[columnas["cantidad"]] if columnas["cantidad"] < len(fila) else None
                )
                try:
                    cantidad = int(cantidad_raw)
                except (TypeError, ValueError):
                    conflictos.append(
                        f'{referencia} ({material_raw}): CARGOS SAP inválido: "{cantidad_raw}".'
                    )
                    continue
                if cantidad < 0:
                    conflictos.append(f"{referencia} ({material_raw}): cantidad negativa.")
                    continue

                deposito = depositos_global[contador_reparto % len(depositos_global)]
                contador_reparto += 1
                filas_cantidad[(compania, tipo, deposito)] += cantidad

        return advertencias, conflictos, filas_cantidad

    def _procesar(self, advertencias, conflictos, filas_cantidad, dry_run):
        for advertencia in advertencias:
            self.stdout.write(self.style.WARNING(f"Aviso: {advertencia}"))

        if conflictos:
            self.stdout.write(
                self.style.ERROR(f"{len(conflictos)} conflicto(s) — no se modificó nada:")
            )
            for conflicto in conflictos:
                self.stdout.write(f"  - {conflicto}")
            raise CommandError("Corrige los conflictos y vuelve a correr el comando.")

        total = sum(filas_cantidad.values())
        self.stdout.write(f"{len(filas_cantidad)} existencia(s), {total} unidad(es) en total.")
        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: no se modificó nada."))
            return

        por_compania = defaultdict(int)
        with transaction.atomic():
            for (compania, tipo, deposito), cantidad in filas_cantidad.items():
                existencia, _creada = Existencia.objects.get_or_create(
                    tipo=tipo, compania=compania, deposito=deposito, lote="",
                    defaults={"cantidad": 0},
                )
                existencia.cantidad += cantidad
                existencia.full_clean()
                existencia.save()
                por_compania[compania.nombre] += cantidad

        for nombre, cantidad in sorted(por_compania.items()):
            self.stdout.write(f"  {nombre}: {cantidad}")
        self.stdout.write(self.style.SUCCESS(f"Importación completada: {total} unidad(es)."))
