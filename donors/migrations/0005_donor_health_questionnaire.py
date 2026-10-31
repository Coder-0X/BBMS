from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('donors', '0004_donation_purpose_directed'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DonorHealthQuestionnaire',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('completed_at', models.DateTimeField()),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('weight_kg', models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ('hb_g_dl', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('bp_systolic', models.SmallIntegerField(blank=True, null=True)),
                ('bp_diastolic', models.SmallIntegerField(blank=True, null=True)),
                ('pulse', models.SmallIntegerField(blank=True, null=True)),
                ('temperature_c', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('feeling_well', models.BooleanField()),
                ('recent_illness', models.BooleanField()),
                ('recent_illness_detail', models.TextField(blank=True)),
                ('on_antibiotics', models.BooleanField()),
                ('on_other_medications', models.BooleanField()),
                ('medications_detail', models.TextField(blank=True)),
                ('donated_elsewhere_recently', models.BooleanField()),
                ('donated_elsewhere_detail', models.TextField(blank=True)),
                ('recent_infection', models.BooleanField()),
                ('recent_infection_detail', models.TextField(blank=True)),
                ('travel_risk', models.CharField(
                    choices=[
                        ('none', 'No travel to risk areas'),
                        ('malaria_zone', 'Travel to malaria-endemic area'),
                        ('cjd_risk', 'Lived in UK 1980–1996 (vCJD risk)'),
                        ('other_risk', 'Other risk-area travel'),
                    ],
                    default='none', max_length=15,
                )),
                ('travel_detail', models.TextField(blank=True)),
                ('malaria_history', models.BooleanField()),
                ('tattoo_or_piercing_12m', models.BooleanField()),
                ('needlestick_12m', models.BooleanField()),
                ('sti_history', models.BooleanField()),
                ('new_sexual_partner_3m', models.BooleanField()),
                ('sexual_contact_risk_3m', models.BooleanField()),
                ('sex_for_money_or_drugs', models.BooleanField()),
                ('iv_drug_use_ever', models.BooleanField()),
                ('prior_transfusion', models.BooleanField()),
                ('prior_transfusion_date', models.DateField(blank=True, null=True)),
                ('prior_transplant', models.BooleanField()),
                ('prior_transplant_detail', models.TextField(blank=True)),
                ('pregnancy_6m', models.BooleanField()),
                ('cancer_history', models.BooleanField()),
                ('heart_disease_history', models.BooleanField()),
                ('bleeding_disorder', models.BooleanField()),
                ('diabetes', models.BooleanField()),
                ('cjd_risk_factor', models.BooleanField()),
                ('outcome', models.CharField(
                    blank=True,
                    choices=[
                        ('eligible', 'Eligible — donation proceeded'),
                        ('deferred_temp', 'Temporarily Deferred'),
                        ('deferred_perm', 'Permanently Deferred'),
                        ('self_excluded', 'Self-Excluded (donor withdrew)'),
                    ],
                    max_length=15,
                )),
                ('deferral_reasons', models.TextField(blank=True)),
                ('donor_signature', models.BooleanField(default=False)),
                ('staff_signature', models.BooleanField(default=False)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('donation', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='health_questionnaire',
                    to='donors.donation',
                )),
                ('donor', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='health_questionnaires',
                    to='donors.donor',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-completed_at']},
        ),
    ]
