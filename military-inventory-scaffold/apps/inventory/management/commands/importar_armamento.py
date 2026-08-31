"""Importa el inventario serializado inicial desde un Excel (RF-13, H-13).

Uso:
    python manage.py importar_armamento ruta/al/archivo.xlsx \
        [--deposito NOMBRE[,NOMBRE2]] [--dry-run]

Estructura real observada en el Excel de David (`ACTIVOS FIJOS COMPAÑIA.xlsx`,
carpeta `test files/` — RF-13, P-1/P-6 en docs/PRD.md):

- Una hoja por compañía, nombrada "CP <código>" (p. ej. "CP A", "CP ASPC") —
  se resuelve contra `Compania.nombre` intentando primero un match directo y
  luego quitando el prefijo "CP ".
- Dentro de cada hoja, **varios bloques repetidos por categoría**: título de
  categoría (una sola celda, p. ej. "FUSILES ACE"), luego una fila de
  encabezado ("Denominación" / "Número de serie" / "Compañía"), luego las
  filas de datos de esa categoría, y así se repite para cada categoría de la
  hoja. El importador vuelve a detectar el encabezado cada vez que aparece
  una fila que contiene los nombres de columna reconocidos — no asume que
  todo el archivo tiene un único encabezado al principio.
- Columnas reconocidas (por nombre, sin distinguir mayúsculas):
    - "Serie" / "Número de serie" (obligatoria).
    - "Denominación" / "Tipo" (obligatoria): debe coincidir, tras normalizar
      errores de tipeo conocidos del Excel real (ver TYPO_FIXES, docs/PRD.md
      §12 Riesgos), con el nombre de un `TipoArmamento` controlado por SERIE.
    - "Depósito" (opcional): si la hoja no la trae, se usa `--deposito` para
      toda la hoja.
- Filas con serie "SIN SERIE" (p. ej. los cascos) no son armamento
  serializado — RF-14 pide llevarlos por **cantidad**. Este comando las
  cuenta por (compañía, tipo, depósito) y crea/actualiza el `Existencia`
  correspondiente en vez de un `Armamento`; el tipo debe existir como
  `TipoArmamento` controlado por CANTIDAD (no por SERIE).
- Todo lo importado (serializado o por cantidad) queda "en depósito" — RF-13
  pide la "ubicación inicial (depósito)"; asignar soldados es un paso
  posterior (RF-10), no de esta carga.
- `--deposito` acepta uno o varios nombres separados por coma (p. ej.
  `--deposito "Apiay,Caruru"`); si son varios, cada fila válida se reparte
  entre ellos por turnos (round-robin), en el orden en que aparecen en el
  archivo — ninguno de los dos Excel reales trae una columna de depósito, así
  que esto es lo único disponible para repartir la carga inicial entre los
  depósitos ya sembrados.

Antes de crear nada se valida el archivo completo (series repetidas en el
archivo o ya existentes en la base, tipos o depósitos no reconocidos, series
o denominaciones vacías) y se reportan todos los conflictos encontrados. Si
hay alguno, no se crea NINGÚN registro — corrige el archivo y vuelve a correr
el comando.
"""
from collections import defaultdict

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.models import Armamento, Compania, Deposito, Existencia, TipoArmamento

from ._excel_import_utils import normalizar as _normalizar_base
from ._excel_import_utils import resolver_compania, resolver_depositos

# Errores de tipeo / variantes conocidas en los Excel reales (docs/PRD.md §12 Riesgos).
TYPO_FIXES = {
    "VOSIRES": "VISORES",
    "AMETRALALDORAS": "AMETRALLADORAS",
    "ACE -23": "ACE-23",
}

SIN_SERIE = "SIN SERIE"

COLUMNAS_SERIE = {"SERIE", "NUMERO DE SERIE", "N SERIE", "N. SERIE"}
COLUMNAS_TIPO = {"DENOMINACION", "TIPO"}
COLUMNAS_DEPOSITO = {"DEPOSITO"}


def normalizar(texto):
    return _normalizar_base(texto, TYPO_FIXES)


def _es_fila_encabezado(valores_normalizados):
    tiene_serie = bool(valores_normalizados & COLUMNAS_SERIE)
    tiene_tipo = bool(valores_normalizados & COLUMNAS_TIPO)
    return tiene_serie and tiene_tipo


class Command(BaseCommand):
    help = "Importa armamento (por serie) y cascos SIN SERIE (por cantidad) desde un Excel (RF-13)."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta al archivo .xlsx a importar.")
        parser.add_argument(
            "--deposito",
            default=None,
            help=(
                "Depósito(s) a usar en las hojas que no traen columna Depósito. "
                "Uno o varios separados por coma; con varios, se reparten las "
                "filas por turnos entre ellos."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo valida y reporta; no crea nada aunque no haya conflictos.",
        )

    def handle(self, *args, **options):
        depositos_global = resolver_depositos(options["deposito"], Deposito)

        ruta = options["archivo"]
        try:
            workbook = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        except FileNotFoundError as exc:
            raise CommandError(f"No se encontró el archivo: {ruta}") from exc

        try:
            advertencias, conflictos, filas_validas, filas_cantidad = self._leer_filas(
                workbook, depositos_global
            )
        finally:
            workbook.close()  # en modo read_only, el archivo queda abierto si no se cierra.

        self._procesar(
            advertencias, conflictos, filas_validas, filas_cantidad, options["dry_run"]
        )

    def _leer_filas(self, workbook, depositos_global):
        companias_por_nombre = {normalizar(c.nombre): c for c in Compania.objects.all()}
        tipos_serie_por_nombre = {
            normalizar(t.nombre): t
            for t in TipoArmamento.objects.filter(control=TipoArmamento.Control.SERIE)
        }
        tipos_cantidad_por_nombre = {
            normalizar(t.nombre): t
            for t in TipoArmamento.objects.filter(control=TipoArmamento.Control.CANTIDAD)
        }
        depositos_por_nombre = {normalizar(d.nombre): d for d in Deposito.objects.all()}

        advertencias = []
        conflictos = []
        filas_validas = []  # (compania, tipo, deposito, numero_serie) — Armamento
        filas_cantidad = defaultdict(int)  # (compania, tipo, deposito) -> cantidad — Existencia
        series_en_archivo = {}  # numero_serie -> "hoja X, fila Y" de la primera aparición
        contador_reparto = 0  # para el round-robin de --deposito con varios valores

        for hoja in workbook.worksheets:
            compania = resolver_compania(hoja.title, companias_por_nombre, TYPO_FIXES)
            if compania is None:
                advertencias.append(
                    f'Hoja "{hoja.title}" omitida: no coincide con ninguna compañía sembrada.'
                )
                continue

            columnas = None
            for num_fila, fila in enumerate(hoja.iter_rows(values_only=True), start=1):
                valores_no_none = [v for v in fila if v is not None]
                if not valores_no_none:
                    continue  # fila en blanco: separador entre bloques de categoría.

                valores_normalizados = {normalizar(v) for v in valores_no_none}
                if _es_fila_encabezado(valores_normalizados):
                    columnas = {}
                    for indice, valor in enumerate(fila):
                        if valor is None:
                            continue
                        clave = normalizar(valor)
                        if clave in COLUMNAS_SERIE:
                            columnas["serie"] = indice
                        elif clave in COLUMNAS_TIPO:
                            columnas["tipo"] = indice
                        elif clave in COLUMNAS_DEPOSITO:
                            columnas["deposito"] = indice
                    continue

                if len(valores_no_none) == 1:
                    continue  # título de categoría (p. ej. "FUSILES ACE"), no es un dato.

                if columnas is None:
                    conflictos.append(
                        f'Hoja "{hoja.title}", fila {num_fila}: hay datos antes de un '
                        f"encabezado reconocido (Serie y Denominación/Tipo)."
                    )
                    continue

                referencia = f'hoja "{hoja.title}", fila {num_fila}'
                serie_raw = fila[columnas["serie"]] if columnas["serie"] < len(fila) else None
                if serie_raw is None or not str(serie_raw).strip():
                    conflictos.append(f"{referencia}: serie vacía.")
                    continue
                numero_serie = str(serie_raw).strip()
                es_sin_serie = normalizar(numero_serie) == SIN_SERIE

                tipo_raw = fila[columnas["tipo"]] if columnas["tipo"] < len(fila) else None
                if tipo_raw is None or not str(tipo_raw).strip():
                    conflictos.append(f"{referencia} (serie {numero_serie}): denominación vacía.")
                    continue
                tipos_dict = tipos_cantidad_por_nombre if es_sin_serie else tipos_serie_por_nombre
                tipo = tipos_dict.get(normalizar(tipo_raw))
                if tipo is None:
                    control = "por cantidad" if es_sin_serie else "por serie"
                    conflictos.append(
                        f'{referencia} (serie {numero_serie}): tipo no reconocido ({control}): '
                        f'"{tipo_raw}".'
                    )
                    continue

                deposito = None
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
                    if depositos_global:
                        deposito = depositos_global[contador_reparto % len(depositos_global)]
                        contador_reparto += 1
                    else:
                        conflictos.append(
                            f"{referencia} (serie {numero_serie}): sin depósito "
                            f"(agrega la columna Depósito o usa --deposito)."
                        )
                        continue

                if es_sin_serie:
                    filas_cantidad[(compania, tipo, deposito)] += 1
                    continue

                if numero_serie in series_en_archivo:
                    conflictos.append(
                        f'Serie duplicada en el archivo: "{numero_serie}" '
                        f"({referencia} y {series_en_archivo[numero_serie]})."
                    )
                    continue
                series_en_archivo[numero_serie] = referencia

                filas_validas.append((compania, tipo, deposito, numero_serie))

        return advertencias, conflictos, filas_validas, filas_cantidad

    def _procesar(self, advertencias, conflictos, filas_validas, filas_cantidad, dry_run):
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

        total_cantidad = sum(filas_cantidad.values())
        self.stdout.write(
            f"{len(filas_validas)} elemento(s) serializados y {total_cantidad} "
            f"elemento(s) sin serie (por cantidad) listos para crear."
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: no se creó nada."))
            return

        armamento_por_compania = defaultdict(int)
        cantidad_por_compania = defaultdict(int)
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
                armamento_por_compania[compania.nombre] += 1

            for (compania, tipo, deposito), cantidad in filas_cantidad.items():
                existencia, _creada = Existencia.objects.get_or_create(
                    tipo=tipo, compania=compania, deposito=deposito, lote="",
                    defaults={"cantidad": 0},
                )
                existencia.cantidad += cantidad
                existencia.full_clean()
                existencia.save()
                cantidad_por_compania[compania.nombre] += cantidad

        companias_nombres = sorted(set(armamento_por_compania) | set(cantidad_por_compania))
        for nombre in companias_nombres:
            self.stdout.write(
                f"  {nombre}: {armamento_por_compania[nombre]} serializado(s), "
                f"{cantidad_por_compania[nombre]} sin serie"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Importación completada: {len(filas_validas)} serializado(s), "
                f"{total_cantidad} sin serie (por cantidad)."
            )
        )
