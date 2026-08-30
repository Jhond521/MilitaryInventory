"""Importa el inventario serializado inicial desde un Excel (RF-13, H-13).

Uso:
    python manage.py importar_armamento ruta/al/archivo.xlsx [--deposito NOMBRE] [--dry-run]

El archivo real de David (`ACTIVOS FIJOS COMPAÑIA.xlsx`) todavía no está
disponible al escribir este comando (P-1/P-6 en docs/PRD.md siguen
pendientes), así que este importador asume una estructura normalizada
razonable, documentada aquí para poder adaptarlo rápido en cuanto llegue el
archivo real:

- Una hoja de cálculo (worksheet) por compañía. El NOMBRE de la hoja debe
  coincidir (sin distinguir mayúsculas, tildes ni espacios extra) con el
  nombre de una `Compania` ya sembrada (ver `seed_initial`). Una hoja que no
  coincide con ninguna compañía se **omite con una advertencia**, no bloquea
  el resto del archivo (podría ser una pestaña de notas/resumen).
- Primera fila de cada hoja reconocida: encabezados. Columnas reconocidas
  (por nombre, sin distinguir mayúsculas):
    - "Serie" / "Número de serie" (obligatoria).
    - "Denominación" / "Tipo" (obligatoria): debe coincidir, tras normalizar
      errores de tipeo conocidos del Excel real (ver TYPO_FIXES, docs/PRD.md
      §12 Riesgos), con el nombre de un `TipoArmamento` controlado por SERIE.
    - "Depósito" (opcional): si la hoja no la trae, se usa `--deposito` para
      toda la hoja.
- Todo lo importado queda "en depósito" — RF-13 pide la "ubicación inicial
  (depósito)"; asignar soldados es un paso posterior (RF-10), no de esta carga.

Antes de crear nada se valida el archivo completo (series repetidas en el
archivo o ya existentes en la base, tipos o depósitos no reconocidos, series
o denominaciones vacías) y se reportan todos los conflictos encontrados. Si
hay alguno, no se crea NINGÚN registro — corrige el archivo y vuelve a correr
el comando.
"""
import unicodedata
from collections import defaultdict

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.models import Armamento, Compania, Deposito, TipoArmamento

# Errores de tipeo conocidos en el Excel real (docs/PRD.md §12 Riesgos).
TYPO_FIXES = {
    "VOSIRES": "VISORES",
    "AMETRALALDORAS": "AMETRALLADORAS",
}

COLUMNAS_SERIE = {"SERIE", "NUMERO DE SERIE", "N SERIE", "N. SERIE"}
COLUMNAS_TIPO = {"DENOMINACION", "TIPO"}
COLUMNAS_DEPOSITO = {"DEPOSITO"}


def normalizar(texto):
    """Mayúsculas, sin tildes y sin espacios repetidos, para comparar nombres
    de compañía/tipo/depósito y encabezados de columna sin depender de cómo
    se hayan escrito exactamente (RF-13, docs/PRD.md §12 Riesgos)."""
    t = " ".join(str(texto).strip().upper().split())
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    for malo, bueno in TYPO_FIXES.items():
        t = t.replace(malo, bueno)
    return t


class Command(BaseCommand):
    help = "Importa armamento serializado desde un Excel, una hoja por compañía (RF-13)."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta al archivo .xlsx a importar.")
        parser.add_argument(
            "--deposito",
            default=None,
            help="Depósito a usar en las hojas que no traen columna Depósito.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo valida y reporta; no crea nada aunque no haya conflictos.",
        )

    def handle(self, *args, **options):
        deposito_global = None
        if options["deposito"]:
            try:
                deposito_global = Deposito.objects.get(nombre__iexact=options["deposito"].strip())
            except Deposito.DoesNotExist:
                raise CommandError(f"Depósito no encontrado: {options['deposito']}") from None

        ruta = options["archivo"]
        try:
            workbook = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        except FileNotFoundError as exc:
            raise CommandError(f"No se encontró el archivo: {ruta}") from exc

        try:
            advertencias, conflictos, filas_validas = self._leer_filas(workbook, deposito_global)
        finally:
            workbook.close()  # en modo read_only, el archivo queda abierto si no se cierra.

        self._procesar(advertencias, conflictos, filas_validas, options["dry_run"])

    def _leer_filas(self, workbook, deposito_global):
        companias_por_nombre = {normalizar(c.nombre): c for c in Compania.objects.all()}
        tipos_por_nombre = {
            normalizar(t.nombre): t
            for t in TipoArmamento.objects.filter(control=TipoArmamento.Control.SERIE)
        }
        depositos_por_nombre = {normalizar(d.nombre): d for d in Deposito.objects.all()}

        advertencias = []
        conflictos = []
        filas_validas = []  # (compania, tipo, deposito, numero_serie)
        series_en_archivo = {}  # numero_serie -> "hoja X, fila Y" de la primera aparición

        for hoja in workbook.worksheets:
            compania = companias_por_nombre.get(normalizar(hoja.title))
            if compania is None:
                advertencias.append(
                    f'Hoja "{hoja.title}" omitida: no coincide con ninguna compañía sembrada.'
                )
                continue

            filas = hoja.iter_rows(values_only=True)
            encabezados = next(filas, None)
            if encabezados is None:
                advertencias.append(f'Hoja "{hoja.title}" omitida: está vacía.')
                continue

            columnas = {}
            for indice, valor in enumerate(encabezados):
                if valor is None:
                    continue
                clave = normalizar(valor)
                if clave in COLUMNAS_SERIE:
                    columnas["serie"] = indice
                elif clave in COLUMNAS_TIPO:
                    columnas["tipo"] = indice
                elif clave in COLUMNAS_DEPOSITO:
                    columnas["deposito"] = indice

            if "serie" not in columnas or "tipo" not in columnas:
                conflictos.append(
                    f'Hoja "{hoja.title}": faltan columnas obligatorias '
                    f"(Serie y Denominación/Tipo)."
                )
                continue

            for num_fila, fila in enumerate(filas, start=2):
                if fila is None or all(valor is None for valor in fila):
                    continue

                referencia = f'hoja "{hoja.title}", fila {num_fila}'
                serie_raw = fila[columnas["serie"]] if columnas["serie"] < len(fila) else None
                if serie_raw is None or not str(serie_raw).strip():
                    conflictos.append(f"{referencia}: serie vacía.")
                    continue
                numero_serie = str(serie_raw).strip()

                tipo_raw = fila[columnas["tipo"]] if columnas["tipo"] < len(fila) else None
                if tipo_raw is None or not str(tipo_raw).strip():
                    conflictos.append(f"{referencia} (serie {numero_serie}): denominación vacía.")
                    continue
                tipo = tipos_por_nombre.get(normalizar(tipo_raw))
                if tipo is None:
                    conflictos.append(
                        f'{referencia} (serie {numero_serie}): tipo no reconocido: "{tipo_raw}".'
                    )
                    continue

                deposito = deposito_global
                if "deposito" in columnas:
                    deposito_raw = (
                        fila[columnas["deposito"]] if columnas["deposito"] < len(fila) else None
                    )
                    if deposito_raw is not None and str(deposito_raw).strip():
                        deposito = depositos_por_nombre.get(normalizar(deposito_raw))
                        if deposito is None:
                            conflictos.append(
                                f"{referencia} (serie {numero_serie}): depósito no "
                                f'reconocido: "{deposito_raw}".'
                            )
                            continue
                if deposito is None:
                    conflictos.append(
                        f"{referencia} (serie {numero_serie}): sin depósito "
                        f"(agrega la columna Depósito o usa --deposito)."
                    )
                    continue

                if numero_serie in series_en_archivo:
                    conflictos.append(
                        f'Serie duplicada en el archivo: "{numero_serie}" '
                        f"({referencia} y {series_en_archivo[numero_serie]})."
                    )
                    continue
                series_en_archivo[numero_serie] = referencia

                filas_validas.append((compania, tipo, deposito, numero_serie))

        return advertencias, conflictos, filas_validas

    def _procesar(self, advertencias, conflictos, filas_validas, dry_run):
        if filas_validas:
            existentes = set(
                Armamento.objects.filter(
                    numero_serie__in=[fila[3] for fila in filas_validas]
                ).values_list("numero_serie", flat=True)
            )
            for numero_serie in sorted(existentes):
                conflictos.append(f'Serie ya existe en la base de datos: "{numero_serie}".')
            filas_validas = [fila for fila in filas_validas if fila[3] not in existentes]

        for advertencia in advertencias:
            self.stdout.write(self.style.WARNING(f"Aviso: {advertencia}"))

        if conflictos:
            self.stdout.write(
                self.style.ERROR(f"{len(conflictos)} conflicto(s) — no se creó nada:")
            )
            for conflicto in conflictos:
                self.stdout.write(f"  - {conflicto}")
            raise CommandError("Corrige los conflictos y vuelve a correr el comando.")

        self.stdout.write(f"{len(filas_validas)} elemento(s) listos para crear.")
        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: no se creó nada."))
            return

        por_compania = defaultdict(int)
        with transaction.atomic():
            for compania, tipo, deposito, numero_serie in filas_validas:
                arma = Armamento(
                    numero_serie=numero_serie,
                    tipo=tipo,
                    compania=compania,
                    ubicacion=Armamento.Ubicacion.DEPOSITO,
                    deposito=deposito,
                )
                arma.full_clean()
                arma.save()
                por_compania[compania.nombre] += 1

        for nombre, cantidad in sorted(por_compania.items()):
            self.stdout.write(f"  {nombre}: {cantidad}")
        self.stdout.write(
            self.style.SUCCESS(f"Importación completada: {len(filas_validas)} elemento(s).")
        )
