from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='patient',
            name='abo',
            field=models.CharField(
                blank=True,
                choices=[('A', 'A'), ('B', 'B'), ('AB', 'AB'), ('O', 'O')],
                max_length=2,
            ),
        ),
        migrations.AddField(
            model_name='patient',
            name='rh_d',
            field=models.CharField(
                blank=True,
                choices=[('pos', 'Positive'), ('neg', 'Negative'), ('weak_d', 'Weak D'), ('unknown', 'Unknown')],
                max_length=10,
            ),
        ),
    ]
