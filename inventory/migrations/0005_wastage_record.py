from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_bloodunit_storage_equipment'),
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WastageRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason_code', models.CharField(choices=[
                    ('expired_unused', 'Expired — unused (not issued)'),
                    ('expired_issued', 'Expired — issued but not transfused'),
                    ('unit_returned_late', 'Unit returned — exceeded 30-min rule'),
                    ('temperature_excursion', 'Temperature excursion during storage'),
                    ('temperature_transport', 'Temperature excursion during transport'),
                    ('tti_reactive', 'TTI reactive result post-release'),
                    ('failed_qc_processing', 'Failed QC — processing / component defect'),
                    ('failed_qc_appearance', 'Failed QC — visual inspection (clots, haemolysis)'),
                    ('recall', 'Recalled — donor lookback'),
                    ('ordering_error', 'Ordering error — wrong component requested'),
                    ('clinical_cancelled', 'Clinical decision — transfusion cancelled'),
                    ('satellite_expired', 'Expired at satellite/ward'),
                    ('tech_error', 'Technical/labelling error'),
                    ('other', 'Other (see notes)'),
                ], max_length=30)),
                ('final_status', models.CharField(max_length=25)),
                ('notes', models.TextField(blank=True)),
                ('avoidable', models.BooleanField(blank=True, help_text='Was this wastage preventable?', null=True)),
                ('value_gbp', models.DecimalField(blank=True, decimal_places=2, help_text='Estimated cost in GBP (for financial reporting)', max_digits=8, null=True)),
                ('recorded_at', models.DateTimeField(auto_now_add=True)),
                ('blood_unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='wastage_records', to='inventory.bloodunit')),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
