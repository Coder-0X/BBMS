import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='DemandFactDaily',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('component_class', models.CharField(max_length=5,
                    choices=[('RBC','Red Blood Cells'),('FFP','Fresh Frozen Plasma'),
                             ('PLT','Platelets'),('CRYO','Cryoprecipitate'),
                             ('WB','Whole Blood'),('GRAN','Granulocytes')])),
                ('fact_date', models.DateField(db_index=True)),
                ('units_issued', models.SmallIntegerField(default=0)),
                ('units_crossmatched', models.SmallIntegerField(default=0)),
                ('units_expired', models.SmallIntegerField(default=0)),
                ('units_discarded', models.SmallIntegerField(default=0)),
                ('units_received', models.SmallIntegerField(default=0)),
                ('opening_stock', models.SmallIntegerField(default=0)),
                ('closing_stock', models.SmallIntegerField(default=0)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='+', to='core.branch')),
            ],
            options={'ordering': ['-fact_date'], 'unique_together': {('branch', 'component_class', 'fact_date')}},
        ),
        migrations.CreateModel(
            name='Forecast',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('component_class', models.CharField(max_length=5,
                    choices=[('RBC','Red Blood Cells'),('FFP','Fresh Frozen Plasma'),
                             ('PLT','Platelets'),('CRYO','Cryoprecipitate'),
                             ('WB','Whole Blood'),('GRAN','Granulocytes')])),
                ('generated_on', models.DateField()),
                ('horizon_date', models.DateField()),
                ('predicted_units', models.DecimalField(decimal_places=2, max_digits=7)),
                ('lower_80', models.DecimalField(decimal_places=2, max_digits=7, null=True, blank=True)),
                ('upper_80', models.DecimalField(decimal_places=2, max_digits=7, null=True, blank=True)),
                ('model_params', models.JSONField(null=True, blank=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='+', to='core.branch')),
            ],
            options={'ordering': ['horizon_date'],
                     'unique_together': {('branch', 'component_class', 'generated_on', 'horizon_date')}},
        ),
        migrations.CreateModel(
            name='KpiDaily',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kpi_date', models.DateField()),
                ('ct_ratio_rbc', models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)),
                ('ct_ratio_plt', models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)),
                ('ct_ratio_ffp', models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)),
                ('wastage_pct_rbc', models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)),
                ('wastage_pct_plt', models.DecimalField(decimal_places=2, max_digits=5, null=True, blank=True)),
                ('days_supply_rbc', models.DecimalField(decimal_places=1, max_digits=5, null=True, blank=True)),
                ('days_supply_plt', models.DecimalField(decimal_places=1, max_digits=5, null=True, blank=True)),
                ('days_supply_ffp', models.DecimalField(decimal_places=1, max_digits=5, null=True, blank=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name='+', to='core.branch')),
            ],
            options={'ordering': ['-kpi_date'], 'unique_together': {('branch', 'kpi_date')}},
        ),
    ]
