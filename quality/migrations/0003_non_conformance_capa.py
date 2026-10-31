from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0002_reagent_minimum_lots'),
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NonConformance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nc_number', models.CharField(help_text='Auto-assigned e.g. NC-2026-0001', max_length=20, unique=True)),
                ('nc_type', models.CharField(choices=[('reagent_failure', 'Reagent failure / QC failure'), ('clerical_error', 'Clerical / labelling error'), ('procedure_deviation', 'SOP deviation — procedure not followed'), ('equipment_failure', 'Equipment failure / malfunction'), ('sample_issue', 'Sample integrity / mislabelling (WBIT)'), ('cold_chain_breach', 'Cold chain / temperature excursion'), ('compatibility_near_miss', 'Compatibility near-miss'), ('transfusion_reaction', 'Transfusion reaction — possible NC component'), ('documentation_error', 'Documentation / record-keeping error'), ('supply_shortage', 'Supply chain / reagent shortage'), ('other', 'Other (see description)')], max_length=30)),
                ('severity', models.CharField(choices=[('near_miss', 'Near-miss — detected before patient impact'), ('minor', 'Minor — no patient harm, limited impact'), ('significant', 'Significant — potential for patient harm'), ('serious', 'Serious — patient harm occurred'), ('critical', 'Critical — death or permanent harm')], max_length=15)),
                ('status', models.CharField(choices=[('open', 'Open'), ('under_review', 'Under Review — root cause analysis in progress'), ('capa_open', 'CAPA Open — corrective actions assigned'), ('capa_verify', 'CAPA Verification — checking effectiveness'), ('closed', 'Closed — verified effective')], default='open', max_length=15)),
                ('description', models.TextField()),
                ('immediate_action', models.TextField(blank=True)),
                ('related_blood_unit_did', models.CharField(blank=True, max_length=20)),
                ('related_patient_id', models.IntegerField(blank=True, null=True)),
                ('related_donor_id', models.IntegerField(blank=True, null=True)),
                ('shot_reportable', models.BooleanField(default=False)),
                ('shot_reference', models.CharField(blank=True, max_length=50)),
                ('event_date', models.DateField()),
                ('reported_at', models.DateTimeField(auto_now_add=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('reported_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('related_qc_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='nonconformances', to='quality.qcrun')),
            ],
            options={
                'ordering': ['-reported_at'],
            },
        ),
        migrations.CreateModel(
            name='CorrectiveAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_type', models.CharField(choices=[('corrective', 'Corrective — fixes the specific instance'), ('preventive', 'Preventive — prevents recurrence system-wide'), ('systemic', 'Systemic — process / SOP change')], max_length=15)),
                ('status', models.CharField(choices=[('assigned', 'Assigned'), ('in_progress', 'In Progress'), ('completed', 'Completed — awaiting verification'), ('verified', 'Verified Effective'), ('ineffective', 'Verified — Ineffective (re-open NC)')], default='assigned', max_length=15)),
                ('description', models.TextField()),
                ('due_date', models.DateField()),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('verification_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('nc', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='actions', to='quality.nonconformance')),
                ('assigned_to', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('completed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('verified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['due_date'],
            },
        ),
    ]
