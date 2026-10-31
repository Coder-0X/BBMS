from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_alter_wastagerecord_final_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='processingevent',
            name='blood_unit',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='processing_events',
                to='inventory.bloodunit',
            ),
        ),
    ]
