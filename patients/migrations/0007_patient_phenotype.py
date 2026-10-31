from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0006_blood_group_discrepancy_investigation'),
        ('audit', '0001_initial'),
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PatientPhenotype',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('method', models.CharField(choices=[('serology', 'Serology (tube/gel)'), ('molecular', 'Molecular genotyping')], default='serology', max_length=15)),
                ('typed_at', models.DateTimeField()),
                # Rh
                ('C',   models.BooleanField(blank=True, null=True)),
                ('c',   models.BooleanField(blank=True, null=True)),
                ('E',   models.BooleanField(blank=True, null=True)),
                ('e',   models.BooleanField(blank=True, null=True)),
                # Kell
                ('K',   models.BooleanField(blank=True, null=True)),
                ('k',   models.BooleanField(blank=True, null=True)),
                # Duffy
                ('Fya', models.BooleanField(blank=True, null=True)),
                ('Fyb', models.BooleanField(blank=True, null=True)),
                # Kidd
                ('Jka', models.BooleanField(blank=True, null=True)),
                ('Jkb', models.BooleanField(blank=True, null=True)),
                # MNS
                ('M',   models.BooleanField(blank=True, null=True)),
                ('N',   models.BooleanField(blank=True, null=True)),
                ('S',   models.BooleanField(blank=True, null=True)),
                ('s',   models.BooleanField(blank=True, null=True)),
                # Lewis
                ('Lea', models.BooleanField(blank=True, null=True)),
                ('Leb', models.BooleanField(blank=True, null=True)),
                # P1PK
                ('P1',  models.BooleanField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='phenotype', to='patients.patient')),
                ('typed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
            ],
        ),
    ]
