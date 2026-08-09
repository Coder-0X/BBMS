from decimal import Decimal

from django.db import migrations


COMPONENTS = [
    {
        'component_name': 'Whole Blood',
        'description': 'Unseparated whole blood. Available for manual '
        'stock entry; not produced by auto-separation.',
        'shelf_life_days': 35,
        'ml_per_unit': 450,
        'split_percentage': None,
    },
    {
        'component_name': 'Packed Red Blood Cells',
        'description': 'Red cell concentrate auto-separated from a '
        'whole-blood donation after it passes lab screening.',
        'shelf_life_days': 42,
        'ml_per_unit': 250,
        'split_percentage': Decimal('55.00'),
    },
    {
        'component_name': 'Fresh Frozen Plasma',
        'description': 'Plasma fraction auto-separated from a '
        'whole-blood donation after it passes lab screening. Shelf life '
        'assumes it stays frozen.',
        'shelf_life_days': 365,
        'ml_per_unit': 200,
        'split_percentage': Decimal('40.00'),
    },
    {
        'component_name': 'Platelets',
        'description': 'Platelet concentrate auto-separated from a '
        'whole-blood donation after it passes lab screening.',
        'shelf_life_days': 5,
        'ml_per_unit': 50,
        'split_percentage': Decimal('5.00'),
    },
    {
        'component_name': 'Cryoprecipitate',
        'description': 'Derived from further processing frozen plasma. '
        'Available for manual stock entry; not produced by the '
        'single-donation auto-separation step.',
        'shelf_life_days': 365,
        'ml_per_unit': 15,
        'split_percentage': None,
    },
]


def seed_components(apps, schema_editor):
    BloodComponent = apps.get_model('inventory', 'BloodComponent')
    for data in COMPONENTS:
        BloodComponent.objects.get_or_create(
            component_name=data['component_name'],
            defaults=data,
        )


def remove_components(apps, schema_editor):
    BloodComponent = apps.get_model('inventory', 'BloodComponent')
    BloodComponent.objects.filter(
        component_name__in=[c['component_name'] for c in COMPONENTS],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_components, remove_components),
    ]
