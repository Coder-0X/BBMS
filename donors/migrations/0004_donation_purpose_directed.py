from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('donors', '0003_retention_campaign'),
        ('patients', '0008_therapeutic_phlebotomy_antenatal'),
    ]

    operations = [
        migrations.AddField(
            model_name='donation',
            name='donation_purpose',
            field=models.CharField(
                choices=[
                    ('allogeneic', 'Allogeneic (Routine)'),
                    ('autologous', 'Pre-deposit Autologous'),
                    ('directed', 'Directed (for named recipient)'),
                ],
                default='allogeneic',
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name='donation',
            name='intended_recipient',
            field=models.ForeignKey(
                blank=True,
                help_text='Named recipient for directed or autologous donations',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='directed_donations',
                to='patients.patient',
            ),
        ),
    ]
