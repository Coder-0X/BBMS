from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='reagent',
            name='minimum_lots',
            field=models.SmallIntegerField(default=1, help_text='Alert when fewer than this many lots are available (in_use + quarantined)'),
        ),
    ]
