from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0007_patient_phenotype'),
        ('donors', '0003_retention_campaign'),
        ('core', '0001_initial'),
        ('audit', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # TherapeuticPhlebotomy
        migrations.CreateModel(
            name='TherapeuticPhlebotomy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('indication', models.CharField(choices=[
                    ('haemochromatosis', 'Hereditary Haemochromatosis (HFE)'),
                    ('polycythaemia_vera', 'Polycythaemia Vera'),
                    ('secondary_eryth', 'Secondary Erythrocytosis'),
                    ('haemosiderosis', 'Secondary Haemosiderosis (transfusion-dependent)'),
                    ('porphyria', 'Porphyria Cutanea Tarda'),
                    ('other', 'Other'),
                ], max_length=25)),
                ('indication_notes', models.CharField(blank=True, max_length=500)),
                ('scheduled_date', models.DateField()),
                ('performed_date', models.DateField(blank=True, null=True)),
                ('target_volume_ml', models.SmallIntegerField(default=450)),
                ('actual_volume_ml', models.SmallIntegerField(blank=True, null=True)),
                ('hb_pre_g_dl', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('hb_post_g_dl', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('haematocrit_pre', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('haematocrit_post', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('ferritin_pre_ug_l', models.DecimalField(blank=True, decimal_places=1, max_digits=8, null=True)),
                ('bp_systolic', models.SmallIntegerField(blank=True, null=True)),
                ('bp_diastolic', models.SmallIntegerField(blank=True, null=True)),
                ('pulse_bpm', models.SmallIntegerField(blank=True, null=True)),
                ('weight_kg', models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ('status', models.CharField(choices=[
                    ('scheduled', 'Scheduled'),
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                    ('declined', 'Patient Declined'),
                ], default='scheduled', max_length=15)),
                ('disposition', models.CharField(choices=[
                    ('discard', 'Discard (not suitable for transfusion)'),
                    ('manufacture', 'Manufacture into Allogeneic Component'),
                ], default='discard', max_length=15)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name='therapeutic_phlebotomies', to='patients.patient')),
                ('donation', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                   related_name='therapeutic_phlebotomy', to='donors.donation')),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                    related_name='+', to=settings.AUTH_USER_MODEL)),
                ('authorised_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                     related_name='+', to=settings.AUTH_USER_MODEL)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name='+', to='core.branch')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                  related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-scheduled_date']},
        ),
        # AntenatalRecord
        migrations.CreateModel(
            name='AntenatalRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('edd', models.DateField(help_text='Estimated Date of Delivery')),
                ('gestation_at_booking_wks', models.SmallIntegerField(blank=True, null=True)),
                ('abo', models.CharField(blank=True, choices=[('A','A'),('B','B'),('AB','AB'),('O','O')], max_length=2)),
                ('rh_d', models.CharField(blank=True, choices=[
                    ('pos','Positive'),('neg','Negative'),('weak_d','Weak D'),('unknown','Unknown'),
                ], max_length=10)),
                ('rh_d_confirmed_at', models.DateField(blank=True, null=True)),
                ('is_rh_d_negative', models.BooleanField(default=False)),
                ('partner_rh_d', models.CharField(blank=True, choices=[
                    ('pos','Positive'),('neg','Negative'),('unknown','Unknown'),
                ], max_length=10)),
                ('outcome', models.CharField(choices=[
                    ('ongoing', 'Ongoing Pregnancy'),
                    ('delivered', 'Delivered'),
                    ('miscarriage', 'Miscarriage / TFMR'),
                    ('stillbirth', 'Stillbirth'),
                    ('ectopic', 'Ectopic Pregnancy'),
                ], default='ongoing', max_length=15)),
                ('delivery_date', models.DateField(blank=True, null=True)),
                ('cord_blood_group_abo', models.CharField(blank=True, max_length=2)),
                ('cord_blood_group_rh', models.CharField(blank=True, max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name='antenatal_records', to='patients.patient')),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name='+', to='core.branch')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                  related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-edd']},
        ),
        # AntiDProphylaxis
        migrations.CreateModel(
            name='AntiDProphylaxis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('indication', models.CharField(choices=[
                    ('raadp_28w',       'Routine Antenatal — 28 weeks (RAADP)'),
                    ('raadp_34w',       'Routine Antenatal — 34 weeks (RAADP)'),
                    ('postnatal',       'Postnatal — within 72 h of delivery'),
                    ('pse_amnio',       'PSE — Amniocentesis / Chorionic Villus Sampling'),
                    ('pse_aph',         'PSE — Antepartum Haemorrhage'),
                    ('pse_ecv',         'PSE — External Cephalic Version'),
                    ('pse_miscarriage', 'PSE — Miscarriage / TFMR (> 12 weeks)'),
                    ('pse_trauma',      'PSE — Abdominal Trauma'),
                    ('pse_other',       'PSE — Other'),
                ], max_length=20)),
                ('product', models.CharField(choices=[
                    ('anti_d_500iu',   'Anti-D 500 IU (Rh(D) Immunoglobulin)'),
                    ('anti_d_1500iu',  'Anti-D 1500 IU'),
                    ('anti_d_2500iu',  'Anti-D 2500 IU'),
                    ('anti_d_custom',  'Anti-D Custom Dose (calculated from Kleihauer)'),
                ], max_length=20)),
                ('dose_iu', models.SmallIntegerField()),
                ('batch_number', models.CharField(max_length=100)),
                ('expiry_date', models.DateField()),
                ('administered_at', models.DateTimeField()),
                ('kleihauer_done', models.BooleanField(default=False)),
                ('kleihauer_result_pct', models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ('fmh_volume_ml', models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ('additional_dose_required', models.BooleanField(default=False)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('antenatal_record', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                        related_name='anti_d_doses', to='patients.antenatalrecord')),
                ('administered_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                       related_name='+', to=settings.AUTH_USER_MODEL)),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                             related_name='+', to='audit.electronicsignature')),
            ],
            options={'ordering': ['-administered_at']},
        ),
    ]
