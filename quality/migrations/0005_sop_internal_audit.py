from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0004_new_lot_validation'),
        ('core', '0001_initial'),
        ('audit', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Create StandardOperatingProcedure WITHOUT the active_version FK
        migrations.CreateModel(
            name='StandardOperatingProcedure',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sop_code', models.CharField(help_text='e.g. BB-SOP-001', max_length=30, unique=True)),
                ('title', models.CharField(max_length=200)),
                ('category', models.CharField(choices=[
                    ('pre_transfusion',  'Pre-Transfusion Testing'),
                    ('blood_grouping',   'Blood Grouping & Antibody Screening'),
                    ('crossmatch',       'Crossmatch Procedures'),
                    ('component_prep',   'Component Preparation & Processing'),
                    ('cold_chain',       'Cold Chain & Storage'),
                    ('quality_control',  'Quality Control & Reagent Management'),
                    ('donor_screening',  'Donor Screening & TTI Testing'),
                    ('administration',   'Transfusion Administration'),
                    ('emergency',        'Emergency & MTP Procedures'),
                    ('waste_disposal',   'Waste Disposal & Spillage'),
                    ('equipment',        'Equipment Maintenance & Calibration'),
                    ('other',            'Other'),
                ], max_length=25)),
                ('status', models.CharField(choices=[
                    ('draft',      'Draft — under authoring'),
                    ('review',     'In Review — awaiting approval'),
                    ('active',     'Active — approved for use'),
                    ('superseded', 'Superseded — replaced by newer version'),
                    ('retired',    'Retired — withdrawn from use'),
                ], default='draft', max_length=12)),
                ('review_interval_months', models.SmallIntegerField(default=12)),
                ('next_review_due', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sops_created', to=settings.AUTH_USER_MODEL)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['sop_code']},
        ),
        # Step 2: Create SOPVersion (references StandardOperatingProcedure — that's fine now)
        migrations.CreateModel(
            name='SOPVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version_number', models.CharField(help_text='e.g. 1.0, 2.3', max_length=20)),
                ('status', models.CharField(choices=[
                    ('draft',    'Draft'),
                    ('review',   'In Review'),
                    ('approved', 'Approved'),
                    ('retired',  'Retired'),
                ], default='draft', max_length=10)),
                ('summary_of_changes', models.TextField(blank=True)),
                ('document_text', models.TextField(blank=True)),
                ('authored_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('authored_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sop', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='versions', to='quality.standardoperatingprocedure')),
            ],
            options={'ordering': ['-authored_at']},
        ),
        migrations.AlterUniqueTogether(
            name='sopversion',
            unique_together={('sop', 'version_number')},
        ),
        # Step 3: Add circular FK active_version to StandardOperatingProcedure (now SOPVersion exists)
        migrations.AddField(
            model_name='standardoperatingprocedure',
            name='active_version',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+', to='quality.sopversion',
            ),
        ),
        # InternalAudit
        migrations.CreateModel(
            name='InternalAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('audit_number', models.CharField(help_text='Auto-assigned e.g. AUD-2026-001', max_length=25, unique=True)),
                ('audit_type', models.CharField(choices=[
                    ('full_system',  'Full QMS System Audit'),
                    ('process',      'Process Audit (specific procedure)'),
                    ('follow_up',    'Follow-up Audit (verify CAPA effectiveness)'),
                    ('unannounced',  'Unannounced Spot Audit'),
                ], max_length=20)),
                ('scope', models.TextField()),
                ('status', models.CharField(choices=[
                    ('scheduled',   'Scheduled'),
                    ('in_progress', 'In Progress'),
                    ('complete',    'Complete — findings issued'),
                    ('closed',      'Closed — all findings resolved'),
                ], default='scheduled', max_length=15)),
                ('scheduled_date', models.DateField()),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('auditee_area', models.CharField(max_length=100)),
                ('closing_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='audits_created', to=settings.AUTH_USER_MODEL)),
                ('lead_auditor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('nc', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audits', to='quality.nonconformance')),
            ],
            options={'ordering': ['-scheduled_date']},
        ),
        # AuditFinding
        migrations.CreateModel(
            name='AuditFinding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.CharField(blank=True, help_text='ISO clause or AABB standard cited', max_length=30)),
                ('classification', models.CharField(choices=[
                    ('major',       'Major — direct impact on quality / safety'),
                    ('minor',       'Minor — deviation with limited impact'),
                    ('observation', 'Observation — opportunity for improvement'),
                ], max_length=15)),
                ('description', models.TextField()),
                ('status', models.CharField(choices=[
                    ('open',     'Open'),
                    ('capa',     'CAPA Raised'),
                    ('resolved', 'Resolved'),
                ], default='open', max_length=10)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('resolved_at', models.DateField(blank=True, null=True)),
                ('resolution', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('audit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='findings', to='quality.internalaudit')),
                ('nc', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_findings', to='quality.nonconformance')),
            ],
            options={'ordering': ['classification', '-created_at']},
        ),
    ]
