from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0005_transfusion_consent'),
        ('transfusion', '0006_neonatal_transfusion_order'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MTPActivation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trigger_type', models.CharField(
                    max_length=15,
                    choices=[
                        ('trauma', 'Trauma'),
                        ('obstetric', 'Obstetric haemorrhage (PPH)'),
                        ('surgical', 'Surgical bleeding'),
                        ('gi_bleed', 'GI Bleed'),
                        ('haematology', 'Haematology (coagulopathy)'),
                        ('other', 'Other'),
                    ],
                )),
                ('activated_at', models.DateTimeField()),
                ('stand_down_at', models.DateTimeField(null=True, blank=True)),
                ('status', models.CharField(
                    default='active',
                    max_length=15,
                    choices=[
                        ('active', 'Active — ongoing haemorrhage'),
                        ('stand_down', 'Stood Down — haemorrhage controlled'),
                        ('completed', 'Completed — documentation done'),
                    ],
                )),
                ('packs_issued', models.SmallIntegerField(default=0)),
                ('rbc_units_issued', models.SmallIntegerField(default=0)),
                ('ffp_units_issued', models.SmallIntegerField(default=0)),
                ('plt_units_issued', models.SmallIntegerField(default=0)),
                ('cryo_units_issued', models.SmallIntegerField(default=0)),
                ('patient_survived', models.BooleanField(null=True, blank=True)),
                ('retrospective_xm_completed', models.BooleanField(default=False)),
                ('clinical_notes', models.TextField(blank=True)),
                ('reported_to_haemovigilance', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('activated_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='mtp_activations',
                    to='core.branch',
                )),
                ('esign', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to='audit.electronicsignature',
                )),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='mtp_activations',
                    to='patients.patient',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
    ]
