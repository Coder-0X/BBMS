from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0005_transfusion_consent'),
        ('audit', '0001_initial'),
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BloodGroupDiscrepancyInvestigation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('open', 'Open — under investigation'), ('resolved', 'Resolved — root cause identified'), ('escalated', 'Escalated — requires senior review / SHOT report')], default='open', max_length=20)),
                ('root_cause', models.CharField(blank=True, choices=[('clerical_sample', 'Clerical error — wrong sample label'), ('clerical_request', 'Clerical error — patient ID mismatch on request form'), ('technical_reagent', 'Technical error — reagent failure or deterioration'), ('technical_technique', 'Technical error — procedural / technique issue'), ('wbc_interference', 'Interference — WBC, rouleaux, cold agglutinin, DSTR'), ('recent_transfusion', 'Recent transfusion — mixed-field from allogeneic RBC'), ('hsct', 'Post-HSCT — donor chimaerism / engraftment'), ('genuine_change', 'Genuine phenotypic change (rare, document fully)'), ('patient_misid', 'Patient misidentification — WBIT event'), ('other', 'Other — see notes')], max_length=30)),
                ('resolution_action', models.TextField(blank=True)),
                ('shot_reportable', models.BooleanField(default=False)),
                ('wbit_event', models.BooleanField(default=False)),
                ('notes', models.TextField(blank=True)),
                ('opened_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='discrepancy_investigations', to='patients.patient')),
                ('discrepant_group', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='investigation_as_discrepant', to='patients.patientbloodgroup')),
                ('prior_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='investigation_as_prior', to='patients.patientbloodgroup')),
                ('confirmed_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='investigation_as_confirmed', to='patients.patientbloodgroup')),
                ('investigated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('resolved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
            ],
            options={
                'ordering': ['-opened_at'],
            },
        ),
    ]
