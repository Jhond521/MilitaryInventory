"""Utilidades compartidas por `importar_armamento` e `importar_existencias`
(RF-13/RF-14) — no es un management command en sí (el prefijo `_` lo excluye
del autodescubrimiento de Django), solo el código común entre ambos.
"""
import unicodedata

# Prefijos de nombre de hoja que no forman parte del nombre de la compañía
# (p. ej. "CP A" -> "A", que tampoco es el nombre sembrado — _resolver_compania
# prueba con y sin este prefijo, y luego contra CODIGOS_COMPANIA).
PREFIJOS_HOJA = ["CP "]

# Código de una letra -> nombre de compañía sembrado. Mismo mapeo de trabajo
# que ya usa la pantalla de selección de compañía (issue #6, PRD RF-03: "ASPC,
# A (Alcatraz), B (Bisonte), C (Córsega), D (Delta), E (Escorpión), IR") — aún
# sin confirmar oficialmente por David (P-5), pero es lo único disponible.
CODIGOS_COMPANIA = {
    "A": "ALCATRAZ",
    "B": "BISONTE",
    "C": "CORSEGA",
    "D": "DELTA",
    "E": "ESCORPION",
}


def normalizar(texto, typo_fixes=None):
    """Mayúsculas, sin tildes y sin espacios repetidos, para comparar nombres
    de compañía/tipo/depósito y encabezados de columna sin depender de cómo
    se hayan escrito exactamente (RF-13, docs/PRD.md §12 Riesgos)."""
    t = " ".join(str(texto).strip().upper().split())
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    for malo, bueno in (typo_fixes or {}).items():
        t = t.replace(malo, bueno)
    return t


def resolver_compania(nombre_hoja, companias_por_nombre, typo_fixes=None):
    """Match directo primero; si no, probar quitando un prefijo de hoja
    conocido (p. ej. "CP A" -> "A") y luego CODIGOS_COMPANIA — el Excel real
    nombra las hojas "CP <código>", que no es el nombre de compañía tal cual
    está sembrado."""
    clave = normalizar(nombre_hoja, typo_fixes)
    if clave in companias_por_nombre:
        return companias_por_nombre[clave]
    for prefijo in PREFIJOS_HOJA:
        prefijo_norm = normalizar(prefijo)
        if not clave.startswith(prefijo_norm):
            continue
        clave_sin_prefijo = clave[len(prefijo_norm) :].strip()
        if clave_sin_prefijo in companias_por_nombre:
            return companias_por_nombre[clave_sin_prefijo]
        nombre_por_codigo = CODIGOS_COMPANIA.get(clave_sin_prefijo)
        if nombre_por_codigo and nombre_por_codigo in companias_por_nombre:
            return companias_por_nombre[nombre_por_codigo]
    return None


def resolver_depositos(valor_flag, deposito_model):
    """Parsea `--deposito "Apiay,Caruru"` en una lista de instancias de
    Deposito; levanta CommandError (import diferido para no crear un ciclo)
    si algún nombre no existe."""
    from django.core.management.base import CommandError

    depositos = []
    if not valor_flag:
        return depositos
    for nombre in valor_flag.split(","):
        nombre = nombre.strip()
        if not nombre:
            continue
        try:
            depositos.append(deposito_model.objects.get(nombre__iexact=nombre))
        except deposito_model.DoesNotExist:
            raise CommandError(f"Depósito no encontrado: {nombre}") from None
    return depositos
