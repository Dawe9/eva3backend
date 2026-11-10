"""Carga opciones de tortas habituales para los formularios de pedidos."""

from django.core.management.base import BaseCommand

from academic.models import BakeryProductOption


class Command(BaseCommand):
    help = 'Carga diez tortas comunes y la opción de torta personalizada.'

    products = [
        ('Torta de chocolate', 14990),
        ('Torta de vainilla', 13990),
        ('Torta tres leches', 16990),
        ('Torta selva negra', 18990),
        ('Torta red velvet', 18990),
        ('Torta de zanahoria', 16990),
        ('Torta de frutilla', 14990),
        ('Torta mil hojas', 15990),
        ('Torta de panqueque naranja', 18990),
        ('Cheesecake', 18990),
        ('Torta personalizada', None),
    ]

    def handle(self, *args, **options):
        created_count = 0
        for name, default_price in self.products:
            _, created = BakeryProductOption.objects.get_or_create(
                name=name,
                defaults={
                    'default_price': default_price,
                    'is_customized': name == 'Torta personalizada',
                    'is_active': True,
                },
            )
            created_count += int(created)
        self.stdout.write(
            self.style.SUCCESS(
                f'Catálogo listo: {created_count} opciones agregadas; '
                f'{len(self.products) - created_count} ya existían. '
                'Los precios existentes se conservaron.'
            )
        )
