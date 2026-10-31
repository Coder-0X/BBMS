from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transfusion', '0003_lookback'),
    ]

    operations = [
        migrations.AddField(
            model_name='bloodrequest',
            name='is_neonatal',
            field=models.BooleanField(
                default=False,
                help_text='Neonatal patient (< 4 months) — enforces irradiated, CMV-safe, small-volume aliquot',
            ),
        ),
        migrations.AddField(
            model_name='bloodrequest',
            name='neonatal_weight_kg',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Patient weight in kg — used to calculate max allowable volume (20 mL/kg)',
                max_digits=5,
                null=True,
            ),
        ),
    ]
