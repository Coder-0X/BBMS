from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0008_therapeutic_phlebotomy_antenatal'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HaemolyticDiseaseCase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('antibody_specificity_text', models.CharField(blank=True, max_length=100)),
                ('gestational_age_wks', models.SmallIntegerField(blank=True, help_text='Gestation at delivery (weeks)', null=True)),
                ('birth_weight_g', models.SmallIntegerField(blank=True, help_text='Birth weight in grams', null=True)),
                ('cord_hb_g_dl', models.DecimalField(blank=True, decimal_places=1, help_text='Cord blood Hb at birth (g/dL)', max_digits=4, null=True)),
                ('direct_antiglobulin_test', models.CharField(choices=[('positive', 'Positive'), ('negative', 'Negative'), ('weakly_pos', 'Weakly Positive'), ('not_done', 'Not Done')], default='not_done', max_length=10)),
                ('peak_bilirubin_umol_l', models.SmallIntegerField(blank=True, help_text='Peak total bilirubin (µmol/L)', null=True)),
                ('hours_at_peak_bilirubin', models.SmallIntegerField(blank=True, help_text='Age at peak bilirubin (hours of life)', null=True)),
                ('severity', models.CharField(blank=True, choices=[('mild', 'Mild — phototherapy only'), ('moderate', 'Moderate — intensive phototherapy'), ('severe', 'Severe — exchange transfusion required'), ('iut', 'Severe — intrauterine transfusion required')], max_length=10)),
                ('phototherapy_started', models.BooleanField(default=False)),
                ('phototherapy_start_date', models.DateField(blank=True, null=True)),
                ('phototherapy_duration_h', models.SmallIntegerField(blank=True, help_text='Total phototherapy hours', null=True)),
                ('exchange_transfusion_done', models.BooleanField(default=False)),
                ('exchange_transfusion_date', models.DateField(blank=True, null=True)),
                ('num_exchange_volumes', models.SmallIntegerField(blank=True, help_text='Number of exchange transfusion volumes given', null=True)),
                ('iut_required', models.BooleanField(default=False, help_text='Intrauterine transfusion required in utero')),
                ('num_iut_procedures', models.SmallIntegerField(default=0, help_text='Number of IUT procedures performed')),
                ('ivig_given', models.BooleanField(default=False, help_text='Intravenous immunoglobulin given')),
                ('outcome', models.CharField(blank=True, choices=[('resolved', 'Resolved — no sequelae'), ('resolved_hearing', 'Resolved — hearing loss / bilirubin toxicity'), ('ongoing', 'Ongoing — under follow-up'), ('transferred', 'Transferred to tertiary centre'), ('neonatal_death', 'Neonatal death')], max_length=20)),
                ('clinical_notes', models.TextField(blank=True)),
                ('reported_to_haemovigilance', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('maternal_antibody', models.ForeignKey(blank=True, help_text='Causative maternal antibody', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='patients.patientantibody')),
                ('mother', models.ForeignKey(help_text='Maternal patient record', on_delete=django.db.models.deletion.PROTECT, related_name='hdfn_cases_mother', to='patients.patient')),
                ('neonate', models.ForeignKey(blank=True, help_text='Neonatal patient record (if registered)', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='hdfn_cases_neonate', to='patients.patient')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'HDFN Case',
                'verbose_name_plural': 'HDFN Cases',
                'ordering': ['-created_at'],
            },
        ),
    ]
