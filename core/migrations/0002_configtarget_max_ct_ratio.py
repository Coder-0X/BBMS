from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='configtarget',
            name='max_ct_ratio',
            field=models.DecimalField(
                decimal_places=2,
                default=2.5,
                help_text='Crossmatch-to-transfusion ratio above which an alert fires',
                max_digits=5,
            ),
        ),
    ]
