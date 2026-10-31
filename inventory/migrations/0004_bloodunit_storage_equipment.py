import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_alter_componenttype_code'),
        ('coldchain', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='bloodunit',
            name='storage_equipment',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='stored_units',
                to='coldchain.storageequipment',
            ),
        ),
    ]
