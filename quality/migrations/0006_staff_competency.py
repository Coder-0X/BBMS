from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0005_sop_internal_audit'),
        ('core', '0001_initial'),
        ('audit', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffCompetency',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_category', models.CharField(choices=[
                    ('blood_grouping',    'Blood Grouping & Antibody Screening'),
                    ('crossmatch',        'Crossmatch (Manual and Electronic)'),
                    ('component_prep',    'Component Preparation'),
                    ('reagent_qc',        'Reagent QC & Lot Release'),
                    ('equipment',         'Equipment Operation & Calibration'),
                    ('cold_chain',        'Cold Chain Monitoring'),
                    ('phlebotomy',        'Phlebotomy / Sample Collection'),
                    ('bedside_admin',     'Bedside Transfusion Administration'),
                    ('emergency_release', 'Emergency / O-neg Release Protocol'),
                    ('data_entry',        'LIS Data Entry & Record Management'),
                    ('other',             'Other'),
                ], max_length=25)),
                ('task_description', models.CharField(help_text='Specific task / SOP', max_length=200)),
                ('assessment_method', models.CharField(choices=[
                    ('direct_observation', 'Direct Observation of Work'),
                    ('review_records',     'Review of Recorded Results'),
                    ('blind_sample',       'Blind Sample / Proficiency Test'),
                    ('oral_exam',          'Oral Examination'),
                    ('written_exam',       'Written Examination'),
                    ('simulation',         'Simulation / Practical Assessment'),
                ], max_length=25)),
                ('assessed_at', models.DateTimeField()),
                ('outcome', models.CharField(choices=[
                    ('competent',             'Competent — approved for independent practice'),
                    ('competent_supervised',  'Competent Under Supervision Only'),
                    ('not_yet_competent',     'Not Yet Competent — retraining required'),
                    ('withdrawn',             'Withdrawn — competency revoked'),
                ], max_length=25)),
                ('score', models.SmallIntegerField(blank=True, null=True)),
                ('pass_threshold', models.SmallIntegerField(blank=True, null=True, default=80)),
                ('comments', models.TextField(blank=True)),
                ('reassessment_due', models.DateField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('assessed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('related_sop', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='competency_records', to='quality.standardoperatingprocedure')),
                ('staff_member', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='competencies', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-assessed_at']},
        ),
    ]
