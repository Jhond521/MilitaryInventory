"""Siembra los datos maestros iniciales de SIGA (idempotente).

Uso:
    python manage.py seed_initial

Crea (si no existen): la unidad por defecto, las 7 compañías, los 2 depósitos
y los 23 tipos de armamento. Volver a correrlo no duplica nada.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.inventory.models import Compania, Deposito, TipoArmamento, Unidad

COMPANIAS = ["ASPC", "Alcatraz", "Bisonte", "Córsega", "Delta", "Escorpión", "IR"]

DEPOSITOS = [
    ("Apiay", "Cantón de Apiay"),
    ("Caruru", "Batallón (Caruru)"),
]

TIPOS_ARMAMENTO = [
    "MUNICION CAL 5.56MM",
    "MUNICION ESLABONADA CAL 5,56MM",
    "CARTUCHO CAL 12.7X99 MM ESLABONADA",
    "MUNICION CAL 09 MM",
    "MUNICION ESLABONADA CAL 7,62MM",
    "GRANADA 40MM 40X53 HE ESLABONADA",
    "GRANADA DE HUMO DE VARIOS COLORES",
    "GRANADA IMC 40 MM X 46 MM H.E.",
    "GRANADA IMC CAL 60 MM H.E. - T.C.",
    "GRANADA IMC CAL 81 MM H.E. - T.C.",
    "MAGAZINE,CARTRIDGE",
    "GRANADA DE MANO IM M26 H.E.",
    "CAÑONES DE REPUESTO",
    "FUSIL AR PLUS CAL. 5.56 MM",
    "FUSIL AR CAL. 5.56 MM",
    "AMETRALLADORA E-4 7,62MM",
    "AMETRALLADORA M-2 HB QCB 50 mm",
    "AMETRALLADORA M249 CAL 5.56MM",
    "LANZA GRANADA DE 40MM MK-19 MOD-3",
    "LANZA GRANADA DE 40MM MK1",
    "MORTERO C-06 L/A DE 60MM",
    "MORTERO SOLTAN",
    "MORTERO B-500",
]


class Command(BaseCommand):
    help = "Siembra unidad, compañías, depósitos y tipos de armamento iniciales."

    def handle(self, *args, **options):
        unidad, _ = Unidad.objects.get_or_create(nombre=settings.DEFAULT_UNIDAD)
        self.stdout.write(f"Unidad: {unidad}")

        for nombre in COMPANIAS:
            Compania.objects.get_or_create(unidad=unidad, nombre=nombre)
        self.stdout.write(f"Compañías: {Compania.objects.count()}")

        for nombre, descripcion in DEPOSITOS:
            Deposito.objects.get_or_create(nombre=nombre, defaults={"descripcion": descripcion})
        self.stdout.write(f"Depósitos: {Deposito.objects.count()}")

        for nombre in TIPOS_ARMAMENTO:
            TipoArmamento.objects.get_or_create(nombre=nombre)
        self.stdout.write(f"Tipos de armamento: {TipoArmamento.objects.count()}")

        self.stdout.write(self.style.SUCCESS("Siembra completada."))
