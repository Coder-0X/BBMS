from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('audit', '0001_initial'),
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Reagent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('category', models.CharField(choices=[('grouping', 'Blood Grouping Sera'), ('coombs', 'Antiglobulin (Coombs)'), ('screening', 'Screening Cells'), ('id_panel', 'Identification Panel Cells'), ('enzyme', 'Enzyme (Papain/Ficin)'), ('other', 'Other')], max_length=20)),
                ('reagent_code', models.CharField(max_length=30, unique=True)),
                ('manufacturer', models.CharField(blank=True, max_length=100)),
                ('qc_interval_hours', models.SmallIntegerField(default=24)),
                ('active', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name='ReagentLot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lot_number', models.CharField(max_length=50)),
                ('expiry_date', models.DateField()),
                ('received_at', models.DateField()),
                ('opened_at', models.DateField(blank=True, null=True)),
                ('in_use_expiry', models.DateField(blank=True, help_text='Expiry once opened', null=True)),
                ('status', models.CharField(choices=[('quarantined', 'Quarantined — awaiting QC'), ('in_use', 'In Use — QC passed'), ('depleted', 'Depleted'), ('recalled', 'Recalled by manufacturer'), ('expired', 'Expired'), ('rejected', 'Rejected — failed QC')], default='quarantined', max_length=15)),
                ('certificate_ok', models.BooleanField(default=False, help_text='Certificate of Analysis reviewed')),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('reagent', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lots', to='quality.reagent')),
                ('received_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('reagent', 'lot_number')},
            },
        ),
        migrations.CreateModel(
            name='QCRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_at', models.DateTimeField()),
                ('completed_at', models.DateTimeField()),
                ('overall_pass', models.BooleanField()),
                ('protocol', models.CharField(default='daily', max_length=50)),
                ('failure_action', models.TextField(blank=True, help_text='Action taken if QC failed')),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('lot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='qc_runs', to='quality.reagentlot')),
                ('performed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('reagent', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='qc_runs', to='quality.reagent')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='QCResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('control_type', models.CharField(choices=[('pos_control', 'Positive Control'), ('neg_control', 'Negative Control'), ('weak_d_ctrl', 'Weak D Control')], max_length=20)),
                ('expected_grade', models.CharField(choices=[('0', '0 — No agglutination'), ('w+', 'w+ — Weak'), ('1+', '1+'), ('2+', '2+'), ('3+', '3+'), ('4+', '4+ — Strong'), ('hem', 'Haemolysis'), ('mf', 'Mixed field')], max_length=5)),
                ('observed_grade', models.CharField(choices=[('0', '0 — No agglutination'), ('w+', 'w+ — Weak'), ('1+', '1+'), ('2+', '2+'), ('3+', '3+'), ('4+', '4+ — Strong'), ('hem', 'Haemolysis'), ('mf', 'Mixed field')], max_length=5)),
                ('passed', models.BooleanField()),
                ('comment', models.CharField(blank=True, max_length=200)),
                ('qc_run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='results', to='quality.qcrun')),
            ],
        ),
        migrations.CreateModel(
            name='EquipmentCalibration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('asset_id', models.CharField(max_length=50, unique=True)),
                ('equipment_type', models.CharField(choices=[('centrifuge', 'Centrifuge'), ('incubator', 'Incubator/Waterbath'), ('balance', 'Balance/Scale'), ('pipette', 'Pipette'), ('thermometer', 'Thermometer'), ('cell_washer', 'Cell Washer'), ('gel_centrifuge', 'Gel Card Centrifuge'), ('other', 'Other')], max_length=20)),
                ('last_calibrated', models.DateField()),
                ('next_due', models.DateField()),
                ('calibrated_by', models.CharField(max_length=100)),
                ('certificate_ref', models.CharField(blank=True, max_length=100)),
                ('within_spec', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
