from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transfusion', '0008_guideline_check'),
        ('transfusion', '0004_donation_blood_grouping'),
        ('patients', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PostTransfusionOutcome',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('post_hb_g_dl', models.DecimalField(blank=True, decimal_places=1, help_text='Post-transfusion haemoglobin (g/dL)', max_digits=4, null=True)),
                ('post_hb_date', models.DateField(blank=True, null=True)),
                ('clinical_response', models.CharField(blank=True, choices=[('as_expected', 'As Expected (≥1 g/dL per unit RBC)'), ('above_expected', 'Above Expected'), ('below_expected', 'Below Expected — investigate'), ('deteriorated', 'Deteriorated — possible adverse event')], max_length=20)),
                ('further_transfusion_planned', models.BooleanField(default=False)),
                ('reaction_occurred', models.BooleanField(default=False)),
                ('notes', models.TextField(blank=True)),
                ('recorded_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='post_outcomes', to='patients.patient')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('request', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='post_outcome', to='transfusion.bloodrequest')),
            ],
        ),
    ]
