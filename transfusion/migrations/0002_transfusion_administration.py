from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transfusion', '0001_initial'),
        ('inventory', '0004_bloodunit_storage_equipment'),
        ('patients', '0003_patient_declared_blood_type'),
        ('core', '0001_initial'),
        ('audit', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TransfusionAdministration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bedside_verify_pass', models.BooleanField(default=False)),
                ('patient_scan_id', models.CharField(blank=True, max_length=100)),
                ('unit_scan_did', models.CharField(blank=True, max_length=12)),
                ('start_at', models.DateTimeField()),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('volume_given_ml', models.SmallIntegerField(blank=True, null=True)),
                ('outcome', models.CharField(choices=[
                    ('completed', 'Completed — full volume given'),
                    ('stopped_reaction', 'Stopped — Adverse Reaction'),
                    ('stopped_patient', 'Stopped — Patient Request'),
                    ('incomplete', 'Incomplete — clinical decision'),
                ], max_length=20)),
                ('vitals_json', models.JSONField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('admin_staff_1', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('admin_staff_2', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('blood_unit', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='administrations',
                    to='inventory.bloodunit',
                )),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to='core.branch',
                )),
                ('esign', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='+',
                    to='audit.electronicsignature',
                )),
                ('issue', models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='administration',
                    to='transfusion.issuetransaction',
                )),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='administrations',
                    to='patients.patient',
                )),
            ],
        ),
    ]
