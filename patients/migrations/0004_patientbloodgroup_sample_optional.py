from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0003_patient_declared_blood_type'),
        ('transfusion', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='patientbloodgroup',
            name='sample',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='+',
                to='transfusion.sample',
            ),
        ),
    ]
