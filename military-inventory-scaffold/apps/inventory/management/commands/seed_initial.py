"""Siembra los datos maestros iniciales de SIGA (idempotente).

Uso:
    python manage.py seed_initial

Crea (si no existen): la unidad por defecto, las 7 compañías, los 2 depósitos,
4 pelotones por compañía y los tipos de armamento (con su forma de control:
SERIE o CANTIDAD). Volver a correrlo no duplica nada.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.inventory.models import Compania, Deposito, Peloton, TipoArmamento, Unidad

COMPANIAS = ["ASPC", "Alcatraz", "Bisonte", "Córsega", "Delta", "Escorpión", "IR"]

PELOTONES_POR_COMPANIA = 4

DEPOSITOS = [
    ("Apiay", "Cantón de Apiay"),
    ("Caruru", "Batallón (Caruru)"),
]

# (nombre, forma de control) — ver docs/PRD.md, RF-05 y Anexo A.
TIPOS_ARMAMENTO = [
    ("MUNICION CAL 5.56MM", TipoArmamento.Control.CANTIDAD),
    ("MUNICION ESLABONADA CAL 5,56MM", TipoArmamento.Control.CANTIDAD),
    ("CARTUCHO CAL 12.7X99 MM ESLABONADA", TipoArmamento.Control.CANTIDAD),
    ("MUNICION CAL 09 MM", TipoArmamento.Control.CANTIDAD),
    ("MUNICION ESLABONADA CAL 7,62MM", TipoArmamento.Control.CANTIDAD),
    ("GRANADA 40MM 40X53 HE ESLABONADA", TipoArmamento.Control.CANTIDAD),
    ("GRANADA DE HUMO DE VARIOS COLORES", TipoArmamento.Control.CANTIDAD),
    ("GRANADA IMC 40 MM X 46 MM H.E.", TipoArmamento.Control.CANTIDAD),
    ("GRANADA IMC CAL 60 MM H.E. - T.C.", TipoArmamento.Control.CANTIDAD),
    ("GRANADA IMC CAL 81 MM H.E. - T.C.", TipoArmamento.Control.CANTIDAD),
    ("MAGAZINE,CARTRIDGE", TipoArmamento.Control.CANTIDAD),
    ("GRANADA DE MANO IM M26 H.E.", TipoArmamento.Control.CANTIDAD),
    ("CAÑONES DE REPUESTO", TipoArmamento.Control.CANTIDAD),
    ("BALISTICO HELMET KEVLAR N. III (SIN SERIE)", TipoArmamento.Control.CANTIDAD),
    ("FUSIL AR PLUS CAL. 5.56 MM", TipoArmamento.Control.SERIE),
    ("FUSIL AR CAL. 5.56 MM", TipoArmamento.Control.SERIE),
    ("AMETRALLADORA E-4 7,62MM", TipoArmamento.Control.SERIE),
    ("AMETRALLADORA M-2 HB QCB 50 mm", TipoArmamento.Control.SERIE),
    ("AMETRALLADORA M249 CAL 5.56MM", TipoArmamento.Control.SERIE),
    ("LANZA GRANADA DE 40MM MK-19 MOD-3", TipoArmamento.Control.SERIE),
    ("LANZA GRANADA DE 40MM MK1", TipoArmamento.Control.SERIE),
    ("MORTERO C-06 L/A DE 60MM", TipoArmamento.Control.SERIE),
    ("MORTERO SOLTAN", TipoArmamento.Control.SERIE),
    ("MORTERO B-500", TipoArmamento.Control.SERIE),
]


class Command(BaseCommand):
    help = "Siembra unidad, compañías, depósitos, pelotones y tipos de armamento iniciales."

    def handle(self, *args, **options):
        unidad, _ = Unidad.objects.get_or_create(nombre=settings.DEFAULT_UNIDAD)
        self.stdout.write(f"Unidad: {unidad}")

        companias = []
        for nombre in COMPANIAS:
            compania, _ = Compania.objects.get_or_create(unidad=unidad, nombre=nombre)
            companias.append(compania)
        self.stdout.write(f"Compañías: {Compania.objects.count()}")

        for compania in companias:
            for n in range(1, PELOTONES_POR_COMPANIA + 1):
                Peloton.objects.get_or_create(compania=compania, nombre=f"{compania.nombre} {n}")
        self.stdout.write(f"Pelotones: {Peloton.objects.count()}")

        for nombre, descripcion in DEPOSITOS:
            Deposito.objects.get_or_create(nombre=nombre, defaults={"descripcion": descripcion})
        self.stdout.write(f"Depósitos: {Deposito.objects.count()}")

        for nombre, control in TIPOS_ARMAMENTO:
            TipoArmamento.objects.update_or_create(nombre=nombre, defaults={"control": control})
        self.stdout.write(f"Tipos de armamento: {TipoArmamento.objects.count()}")

        self.stdout.write(self.style.SUCCESS("Siembra completada."))
