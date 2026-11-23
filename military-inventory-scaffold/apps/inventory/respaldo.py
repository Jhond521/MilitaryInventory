"""Full-database backup to Excel and restore from it (issues #33/#34, RF-26/RF-27).

The workbook format is a contract between export and restore. Everything that
defines it lives here, so the two can't drift apart:

- Sheet ``_meta`` (two columns, ``clave``/``valor``): ``formato`` (`FORMATO`),
  ``generado`` (ISO 8601 with offset), ``generado_por`` (email), ``migracion_<app>``
  (latest migration of each app in `APPS_MIGRACIONES`) and ``filas_<Hoja>`` (row
  count of every model sheet).
- One sheet per model, in `MODELOS_RESPALDO` order (dependency order: every FK
  points to an earlier sheet). Row 1 holds the technical column names: each
  concrete field's ``attname``, so FKs are ``<campo>_id``. Data rows are ordered by
  ``id``.
- Cell values: ``None`` → empty cell. Datetimes → ISO 8601 in local time with
  offset. Dates → ``AAAA-MM-DD``. JSON → JSON text with accents unescaped. Every
  string is written with ``data_type = "s"``, so a text starting with ``=`` stays text
  (no formula injection) and comes back unchanged, with no prefix to strip.
- The ``Usuario`` sheet carries only `USUARIO_CAMPOS`, never the password hash.

Restore (`restaurar`) is a **full replace** of the `inventory` data, not a merge.
It runs in one transaction and keeps the original ids and dates. It never runs
domain logic: ``Prestamo.save()`` would move stock, and ``entregar()`` would log
movements. The file is a consistent snapshot, so rows are inserted with
``bulk_create`` and ``auto_now``/``auto_now_add`` are switched off while it runs.
Users are matched by email, never by id:

- An existing user is left untouched.
- A missing user is created inactive, with an unusable password, only to keep
  history.
- No user is ever deleted.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.color import no_style
from django.db import DatabaseError, connection, models, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from .models import (
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
    UnicodeJSONEncoder,
    Unidad,
)

logger = logging.getLogger(__name__)

FORMATO = 1
HOJA_META = "_meta"
HOJA_USUARIO = "Usuario"
APPS_MIGRACIONES = ("inventory", "accounts")
USUARIO_CAMPOS = ["id", "email", "first_name", "last_name", "role", "is_active", "date_joined"]
PALABRA_CONFIRMACION = "REESTABLECER"

User = get_user_model()

# (sheet name, model). Dependency order: insert top to bottom, delete bottom to top.
MODELOS_RESPALDO = [
    ("Unidad", Unidad),
    ("Compania", Compania),
    ("Deposito", Deposito),
    ("Peloton", Peloton),
    ("TipoArmamento", TipoArmamento),
    ("CampoPersonalizado", CampoPersonalizado),
    (HOJA_USUARIO, User),
    ("Soldado", Soldado),
    ("Armamento", Armamento),
    ("Movimiento", Movimiento),
    ("Existencia", Existencia),
    ("ExistenciaAsignada", ExistenciaAsignada),
    ("MovimientoExistencia", MovimientoExistencia),
    ("Prestamo", Prestamo),
    ("DevolucionPrestamo", DevolucionPrestamo),
]
HOJAS = [hoja for hoja, _ in MODELOS_RESPALDO]
MODELOS_INVENTARIO = [(h, m) for h, m in MODELOS_RESPALDO if m is not User]

# Domain rules that only look at the row itself and its relations. They're checked
# after inserting, inside the transaction. Rules that depend on live stock (such as
# `Prestamo.clean()`, which requires available origin stock) are skipped on purpose:
# the file is a snapshot, and its stock is already the result of those loans.
MODELOS_CON_CLEAN = {
    Soldado: ("peloton",),
    Armamento: ("tipo", "soldado", "compania", "compania_en_prestamo"),
    Existencia: ("tipo",),
}


def campos(model) -> list[models.Field]:
    """Concrete fields exported for `model`, in column order."""
    if model is User:
        return [model._meta.get_field(n) for n in USUARIO_CAMPOS]
    return list(model._meta.concrete_fields)


def columnas(model) -> list[str]:
    return [f.attname for f in campos(model)]


def ultimas_migraciones() -> dict[str, str]:
    """Latest migration on disk for each app (prod runs `migrate` on release,
    so the code and the DB agree)."""
    grafo = MigrationLoader(None, ignore_no_migrations=True).graph
    return {
        app: ",".join(sorted(nombre for _, nombre in grafo.leaf_nodes(app)))
        for app in APPS_MIGRACIONES
    }


# ---------------------------------------------------------------- export (#33)


def _a_celda(f: models.Field, valor):
    if valor is None:
        return None
    if isinstance(f, models.JSONField):
        return json.dumps(valor, cls=UnicodeJSONEncoder)
    if isinstance(valor, datetime):
        return timezone.localtime(valor).isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def nombre_archivo(cuando: datetime | None = None) -> str:
    cuando = timezone.localtime(cuando or timezone.now())
    return f"SIGA-respaldo-{cuando:%Y%m%d-%H%M}.xlsx"


def exportar(archivo, usuario) -> dict[str, int]:
    """Writes the whole backup workbook to `archivo` (a binary file object).
    Returns the row count of each sheet."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    wb = Workbook(write_only=True)
    meta = wb.create_sheet(HOJA_META)
    hojas = {hoja: wb.create_sheet(hoja) for hoja in HOJAS}
    conteos = {}

    def celda(ws, valor):
        c = WriteOnlyCell(ws, value=valor)
        if isinstance(valor, str):
            c.data_type = "s"  # never a formula
        return c

    with transaction.atomic():  # one consistent snapshot of every table
        for hoja, model in MODELOS_RESPALDO:
            ws = hojas[hoja]
            fs = campos(model)
            ws.append([f.attname for f in fs])
            n = 0
            for obj in model.objects.order_by("pk").iterator(chunk_size=1000):
                ws.append([celda(ws, _a_celda(f, getattr(obj, f.attname))) for f in fs])
                n += 1
            conteos[hoja] = n

    meta.append(["clave", "valor"])
    filas_meta = [
        ("formato", FORMATO),
        ("generado", timezone.localtime().isoformat()),
        ("generado_por", usuario.email),
    ]
    filas_meta += [(f"migracion_{app}", m) for app, m in ultimas_migraciones().items()]
    filas_meta += [(f"filas_{hoja}", n) for hoja, n in conteos.items()]
    for clave, valor in filas_meta:
        meta.append([celda(meta, clave), celda(meta, valor)])

    wb.save(archivo)
    logger.info("Respaldo exportado por %s: %s", usuario.email, conteos)
    return conteos


# ------------------------------------------------------------- restore (#34)


class ErrorRespaldo(Exception):
    def __init__(self, errores):
        self.errores = list(errores)
        super().__init__("; ".join(self.errores))


@dataclass
class Respaldo:
    meta: dict = field(default_factory=dict)
    # sheet -> list of (excel row number, {attname: python value})
    filas: dict[str, list[tuple[int, dict]]] = field(default_factory=dict)

    def conteo(self, hoja: str) -> int:
        return len(self.filas.get(hoja, []))

    @property
    def generado(self) -> datetime | None:
        try:
            return datetime.fromisoformat(str(self.meta.get("generado")))
        except ValueError:
            return None


def _ubicacion(hoja: str, fila: int, columna: str | None = None) -> str:
    return f"Hoja {hoja}, fila {fila}" + (f", columna {columna}" if columna else "")


def _mensajes(exc: ValidationError) -> str:
    return " ".join(str(m) for m in exc.messages)


def _de_celda(f: models.Field, crudo):
    """Cell value → Python value for `f`. Raises ValidationError."""
    if isinstance(crudo, str) and crudo == "":
        crudo = None
    if crudo is None:
        if f.null:
            return None
        if isinstance(f, models.CharField | models.TextField):
            return ""
        raise ValidationError("Falta el valor.")
    if f.is_relation:
        try:
            return int(crudo)
        except (TypeError, ValueError):
            raise ValidationError(f"«{crudo}» no es un id válido.") from None
    if isinstance(f, models.JSONField):
        try:
            valor = json.loads(crudo) if isinstance(crudo, str) else crudo
        except ValueError:
            raise ValidationError("No es un JSON válido.") from None
    elif isinstance(f, models.DateTimeField):
        try:
            valor = crudo if isinstance(crudo, datetime) else datetime.fromisoformat(str(crudo))
        except ValueError:
            raise ValidationError(f"«{crudo}» no es una fecha y hora válida.") from None
        if timezone.is_naive(valor):
            valor = timezone.make_aware(valor)
        return valor
    elif isinstance(f, models.DateField):
        if isinstance(crudo, datetime):
            return crudo.date()
        try:
            return date.fromisoformat(str(crudo))
        except ValueError:
            raise ValidationError(f"«{crudo}» no es una fecha válida.") from None
    elif isinstance(f, models.CharField | models.TextField) and not isinstance(crudo, str):
        valor = str(crudo)  # e.g. a cédula typed as a number
    else:
        valor = crudo
    return f.clean(valor, None)  # to_python + choices + max_length + validators


def leer(archivo) -> Respaldo:
    """Reads and validates the whole workbook in memory. It never touches the DB
    except to compare migrations. Raises `ErrorRespaldo` with every problem found,
    each one with its sheet, row and column."""
    from zipfile import BadZipFile

    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = load_workbook(archivo, read_only=True, data_only=False)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError):
        raise ErrorRespaldo(["El archivo no es un Excel (.xlsx) válido."]) from None

    try:
        return _leer_libro(wb)
    finally:
        wb.close()


def _leer_libro(wb) -> Respaldo:
    respaldo = Respaldo()
    if HOJA_META not in wb.sheetnames:
        raise ErrorRespaldo(
            [f"Falta la hoja «{HOJA_META}»: el archivo no es un respaldo de SIGA."]
        )
    for fila in wb[HOJA_META].iter_rows(min_row=2, values_only=True):
        if fila and fila[0] is not None:
            respaldo.meta[str(fila[0])] = fila[1] if len(fila) > 1 else None

    formato = respaldo.meta.get("formato")
    if str(formato) != str(FORMATO):
        raise ErrorRespaldo(
            [f"Formato de respaldo «{formato}» no soportado (se espera {FORMATO})."]
        )
    errores = []
    for app, esperada in ultimas_migraciones().items():
        del_archivo = respaldo.meta.get(f"migracion_{app}")
        if str(del_archivo) != esperada:
            errores.append(
                f"El respaldo es de otra versión de la base ({app}: «{del_archivo}», "
                f"la actual es «{esperada}»)."
            )
    faltan = [h for h in HOJAS if h not in wb.sheetnames]
    if faltan:
        errores.append("Faltan hojas: " + ", ".join(faltan) + ".")
    if errores:
        raise ErrorRespaldo(errores)

    for hoja, model in MODELOS_RESPALDO:
        fs = campos(model)
        esperadas = [f.attname for f in fs]
        filas = wb[hoja].iter_rows(values_only=True)
        encabezado = [c for c in next(filas, ()) if c is not None]
        if encabezado != esperadas:
            faltantes = [c for c in esperadas if c not in encabezado]
            sobrantes = [c for c in encabezado if c not in esperadas]
            detalle = []
            if faltantes:
                detalle.append("faltan " + ", ".join(faltantes))
            if sobrantes:
                detalle.append("sobran " + ", ".join(map(str, sobrantes)))
            if not detalle:
                detalle.append("el orden no es el esperado")
            errores.append(
                f"Hoja {hoja}, fila 1: columnas incorrectas ({'; '.join(detalle)})."
            )
            continue
        datos = []
        for n, valores in enumerate(filas, start=2):
            valores = tuple(valores) + (None,) * (len(fs) - len(valores))
            if all(v is None or v == "" for v in valores):
                continue  # trailing blank rows
            fila = {}
            for f, crudo in zip(fs, valores, strict=False):
                try:
                    fila[f.attname] = _de_celda(f, crudo)
                except ValidationError as exc:
                    errores.append(f"{_ubicacion(hoja, n, f.attname)}: {_mensajes(exc)}")
            datos.append((n, fila))
        respaldo.filas[hoja] = datos

    if not errores:
        errores += _validar_relaciones(respaldo)
    if errores:
        raise ErrorRespaldo(errores)
    return respaldo


def _validar_relaciones(respaldo: Respaldo) -> list[str]:
    """In-memory checks: duplicate ids, FKs that point to a missing row, and every
    unique field or UniqueConstraint."""
    errores = []
    ids = {}
    hoja_de_modelo = {m: h for h, m in MODELOS_RESPALDO}
    for hoja in HOJAS:
        vistos = set()
        for n, fila in respaldo.filas[hoja]:
            if fila["id"] in vistos:
                errores.append(f"{_ubicacion(hoja, n, 'id')}: id {fila['id']} repetido.")
            vistos.add(fila["id"])
        ids[hoja] = vistos

    for hoja, model in MODELOS_RESPALDO:
        fs = campos(model)
        fks = [f for f in fs if f.is_relation]
        unicos = [(f.attname,) for f in fs if f.unique and not f.primary_key]
        unicos += [
            tuple(model._meta.get_field(c).attname for c in uc.fields)
            for uc in model._meta.constraints
            if isinstance(uc, models.UniqueConstraint) and uc.fields
        ]
        vistos = {u: {} for u in unicos}
        for n, fila in respaldo.filas[hoja]:
            for f in fks:
                destino = hoja_de_modelo[f.related_model]
                valor = fila[f.attname]
                if valor is not None and valor not in ids[destino]:
                    errores.append(
                        f"{_ubicacion(hoja, n, f.attname)}: el id {valor} no existe en la "
                        f"hoja {destino}."
                    )
            for u in unicos:
                clave = tuple(
                    fila[c].lower() if model is User and c == "email" else fila[c] for c in u
                )
                if any(v is None for v in clave):
                    continue  # NULLs never collide (e.g. old soldiers without cédula)
                if clave in vistos[u]:
                    errores.append(
                        f"{_ubicacion(hoja, n, ', '.join(u))}: valor repetido "
                        f"({', '.join(map(str, clave))}), ya está en la fila {vistos[u][clave]}."
                    )
                else:
                    vistos[u][clave] = n
    return errores


@contextmanager
def _sin_auto_now():
    """bulk_create still runs `pre_save()`, which would overwrite `auto_now` and
    `auto_now_add` dates with "now". Switch them off while restoring, so the file's
    dates survive. The app runs on sync gunicorn workers (one request per process),
    so nothing else sees the change."""
    cambiados = []
    for _, model in MODELOS_INVENTARIO:
        for f in model._meta.concrete_fields:
            if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
                cambiados.append((f, f.auto_now, f.auto_now_add))
                f.auto_now = f.auto_now_add = False
    try:
        yield
    finally:
        for f, auto_now, auto_now_add in cambiados:
            f.auto_now, f.auto_now_add = auto_now, auto_now_add


def _mapear_usuarios(respaldo: Respaldo) -> dict[int, int]:
    """File user id → real user id, matched by email. Creates missing users inactive
    with an unusable password. Never modifies or deletes anyone."""
    existentes = {u.email.lower(): u.pk for u in User.objects.all()}
    mapa = {}
    for _, fila in respaldo.filas[HOJA_USUARIO]:
        email = fila["email"].lower()
        if email not in existentes:
            nuevo = User(
                email=email,
                first_name=fila["first_name"],
                last_name=fila["last_name"],
                role=fila["role"],
                is_active=False,
                date_joined=fila["date_joined"],
            )
            nuevo.set_unusable_password()
            nuevo.save()
            existentes[email] = nuevo.pk
        mapa[fila["id"]] = existentes[email]
    return mapa


def _aplicar(respaldo: Respaldo, *, reajustar_secuencias: bool) -> None:
    mapa_usuarios = _mapear_usuarios(respaldo)
    for _, model in reversed(MODELOS_INVENTARIO):
        model.objects.all().delete()

    fila_por_id = {}
    with _sin_auto_now():
        for hoja, model in MODELOS_INVENTARIO:
            objs = []
            for n, fila in respaldo.filas[hoja]:
                fila = dict(fila)
                for f in campos(model):
                    if f.is_relation and f.related_model is User and fila[f.attname] is not None:
                        fila[f.attname] = mapa_usuarios[fila[f.attname]]
                objs.append(model(**fila))
                fila_por_id[(hoja, fila["id"])] = n
            model.objects.bulk_create(objs, batch_size=500)

    errores = []
    for model, relacionados in MODELOS_CON_CLEAN.items():
        hoja = next(h for h, m in MODELOS_RESPALDO if m is model)
        for obj in model.objects.select_related(*relacionados).order_by("pk").iterator(
            chunk_size=1000
        ):
            try:
                obj.clean()
            except ValidationError as exc:
                n = fila_por_id[(hoja, obj.pk)]
                errores.append(f"{_ubicacion(hoja, n)}: {_mensajes(exc)}")
    if errores:
        raise ErrorRespaldo(errores)

    if not reajustar_secuencias:
        return
    with connection.cursor() as cursor:
        for sql in connection.ops.sequence_reset_sql(no_style(), [m for _, m in MODELOS_RESPALDO]):
            cursor.execute(sql)


def probar(respaldo: Respaldo) -> None:
    """Dry run: applies the backup and always rolls back. Raises `ErrorRespaldo` if
    the domain rules or the DB reject it."""
    try:
        with transaction.atomic():
            # Postgres `setval()` is NOT undone by a rollback: resetting sequences
            # to an older file's max ids here would make the next real insert
            # collide with an existing row. Only the real restore resets them.
            _aplicar(respaldo, reajustar_secuencias=False)
            transaction.set_rollback(True)
    except DatabaseError as exc:
        raise ErrorRespaldo([f"La base de datos rechazó el respaldo: {exc}"]) from None


def restaurar(respaldo: Respaldo, usuario) -> dict[str, int]:
    """Replaces every `inventory` table with the backup, all or nothing."""
    try:
        with transaction.atomic():
            _aplicar(respaldo, reajustar_secuencias=True)
    except DatabaseError as exc:
        raise ErrorRespaldo([f"La base de datos rechazó el respaldo: {exc}"]) from None
    conteos = {hoja: respaldo.conteo(hoja) for hoja in HOJAS}
    logger.warning(
        "Respaldo del %s (generado por %s) reestablecido por %s: %s",
        respaldo.meta.get("generado"),
        respaldo.meta.get("generado_por"),
        usuario.email,
        conteos,
    )
    return conteos
