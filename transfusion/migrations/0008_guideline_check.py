from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transfusion', '0007_mtp_activation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TransfusionGuidelineCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('clinical_indication', models.CharField(choices=[
                    ('anaemia', 'Symptomatic Anaemia'),
                    ('acute_bleed', 'Acute Haemorrhage'),
                    ('surgical', 'Peri-operative / Surgical'),
                    ('mtp', 'Massive Transfusion Protocol (MTP)'),
                    ('chemotherapy', 'Chemotherapy / Haematology'),
                    ('icu', 'Critical Care / ICU'),
                    ('obstetric', 'Obstetric (PPH / antepartum)'),
                    ('neonatal', 'Neonatal / Paediatric'),
                    ('cardiac', 'Cardiac Surgery / ECMO'),
                    ('orthopaedic', 'Orthopaedic Surgery'),
                    ('neurosurgery', 'Neurosurgery / Ophthalmology'),
                    ('coagulopathy', 'Coagulopathy / DIC'),
                    ('other', 'Other / Not Listed'),
                ], max_length=20)),
                ('is_actively_bleeding', models.BooleanField(default=False)),
                ('is_critical_care', models.BooleanField(default=False)),
                ('is_cardiac_surgery', models.BooleanField(default=False)),
                ('is_orthopaedic', models.BooleanField(default=False)),
                ('is_neurosurgery', models.BooleanField(default=False)),
                ('is_obstetric', models.BooleanField(default=False)),
                ('pre_transfusion_hb_g_dl', models.DecimalField(blank=True, decimal_places=1, help_text='Pre-transfusion haemoglobin in g/dL (required for RBC)', max_digits=4, null=True)),
                ('pre_transfusion_plt_per_nl', models.SmallIntegerField(blank=True, help_text='Pre-transfusion platelet count ×10⁹/L (required for PLT)', null=True)),
                ('pre_transfusion_fibrinogen_g_l', models.DecimalField(blank=True, decimal_places=2, help_text='Pre-transfusion fibrinogen in g/L (required for CRYO)', max_digits=4, null=True)),
                ('pt_ratio', models.DecimalField(blank=True, decimal_places=2, help_text='PT as ratio of normal (e.g. 1.6 = 1.6× upper limit)', max_digits=4, null=True)),
                ('aptt_ratio', models.DecimalField(blank=True, decimal_places=2, help_text='APTT as ratio of normal', max_digits=4, null=True)),
                ('meets_guideline', models.BooleanField()),
                ('guideline_flags_json', models.JSONField(default=list)),
                ('summary', models.TextField(blank=True)),
                ('override_justification', models.TextField(blank=True, help_text='Mandatory if transfusion does not meet guideline thresholds')),
                ('assessed_at', models.DateTimeField(auto_now_add=True)),
                ('assessed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('request', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='guideline_check', to='transfusion.bloodrequest')),
            ],
        ),
    ]
