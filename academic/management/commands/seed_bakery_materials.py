"""Carga ingredientes frecuentes como catálogo inicial sin inventar existencias."""

from decimal import Decimal

from django.core.management.base import BaseCommand

from academic.models import Material


class Command(BaseCommand):
    help = 'Agrega ingredientes comunes de pastelería con stock inicial cero.'

    materials = [
        ('Harina de trigo', 'kg', '5'),
        ('Azúcar granulada', 'kg', '3'),
        ('Azúcar flor', 'kg', '2'),
        ('Huevos', 'unidades', '30'),
        ('Mantequilla', 'kg', '2'),
        ('Leche', 'L', '5'),
        ('Crema para batir', 'L', '2'),
        ('Chocolate de cobertura', 'kg', '2'),
        ('Cacao amargo', 'kg', '1'),
        ('Polvo de hornear', 'kg', '1'),
        ('Levadura seca', 'kg', '1'),
        ('Sal', 'kg', '1'),
        ('Esencia de vainilla', 'L', '0.5'),
        ('Manjar', 'kg', '2'),
        ('Maicena', 'kg', '1'),
        ('Queso crema', 'kg', '1'),
        ('Frutillas', 'kg', '2'),
        ('Aceite vegetal', 'L', '2'),
        ('Coco rallado', 'kg', '1'),
        ('Nueces', 'kg', '1'),
        ('Gelatina sin sabor', 'kg', '0.5'),
        ('Colorantes alimentarios', 'unidades', '3'),
    ]

    def handle(self, *args, **options):
        created_count = 0
        for name, unit, minimum_stock in self.materials:
            _, created = Material.objects.get_or_create(
                name=name,
                defaults={
                    'stock': Decimal('0'),
                    'minimum_stock': Decimal(minimum_stock),
                    'unit': unit,
                    'is_active': True,
                },
            )
            created_count += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f'Catálogo listo: {created_count} ingredientes agregados; '
                f'{len(self.materials) - created_count} ya existían y se conservaron.'
            )
        )
