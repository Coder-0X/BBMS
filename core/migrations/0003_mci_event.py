from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
        ('core', '0002_configtarget_max_ct_ratio'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MCIEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('level', models.CharField(choices=[('1', 'Level 1 — Internal (single ward)'), ('2', 'Level 2 — Major (multi-ward / hospital-wide)'), ('3', 'Level 3 — Mass Casualty (>20 casualties)')], default='2', max_length=1)),
                ('incident_name', models.CharField(blank=True, max_length=200)),
                ('status', models.CharField(choices=[('active', 'Active'), ('stood_down', 'Stood Down')], default='active', max_length=15)),
                ('activated_at', models.DateTimeField()),
                ('stood_down_at', models.DateTimeField(blank=True, null=True)),
                ('preallocated_unit_pks', models.JSONField(default=list)),
                ('notes', models.TextField(blank=True)),
                ('activated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='mci_events', to='core.branch')),
                ('esign_activate', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('esign_standdown', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('stood_down_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-activated_at']},
        ),
    ]
