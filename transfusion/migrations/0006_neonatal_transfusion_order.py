from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0005_transfusion_consent'),
        ('transfusion', '0005_donation_blood_grouping'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NeonatalTransfusionOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gestational_age_weeks', models.SmallIntegerField(null=True, blank=True)),
                ('postnatal_age_days', models.SmallIntegerField()),
                ('weight_kg', models.DecimalField(decimal_places=3, max_digits=5)),
                ('indication', models.CharField(
                    max_length=20,
                    choices=[
                        ('top_up', 'Top-up transfusion (anaemia of prematurity)'),
                        ('exchange', 'Exchange transfusion (HDN, hyperbilirubinaemia)'),
                        ('intrauterine', 'Intrauterine transfusion'),
                        ('hdn_treatment', 'HDN — Haemolytic Disease of Newborn'),
                        ('fnait', 'FNAIT — Foetal/Neonatal Alloimmune Thrombocytopenia'),
                        ('surgical', 'Peri-operative'),
                        ('other', 'Other'),
                    ],
                )),
                ('maternal_abo', models.CharField(blank=True, max_length=2)),
                ('maternal_rh_d', models.CharField(blank=True, max_length=10)),
                ('maternal_antibodies', models.JSONField(blank=True, default=list)),
                ('irradiation_required', models.BooleanField(default=True)),
                ('cmv_negative_required', models.BooleanField(default=True)),
                ('leukoreduced_required', models.BooleanField(default=True)),
                ('max_unit_age_days', models.SmallIntegerField(null=True, blank=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('blood_request', models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='neonatal_order',
                    to='transfusion.bloodrequest',
                )),
                ('created_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='neonatal_orders',
                    to='patients.patient',
                )),
            ],
        ),
    ]
