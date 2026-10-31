from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('donors', '0001_initial'),
        ('patients', '0004_patientbloodgroup_sample_optional'),
        ('transfusion', '0002_transfusion_administration'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LookbackCampaign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('triggered_by_test', models.CharField(help_text='Test code that triggered this (e.g. HIV-1/2, HCV-Ab)', max_length=100)),
                ('triggered_at', models.DateTimeField()),
                ('status', models.CharField(choices=[('open', 'Open — recipients being identified'), ('notified', 'All recipients notified'), ('closed', 'Closed — investigation complete')], default='open', max_length=10)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('lookback_from', models.DateField(help_text='Earliest donation date in scope')),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('donor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lookback_campaigns', to='donors.donor')),
                ('initiated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='LookbackNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('unit_did', models.CharField(help_text='DID of the potentially infectious unit', max_length=12)),
                ('transfusion_date', models.DateField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('notified', 'Notified — clinician informed'), ('tested', 'Patient tested — result pending'), ('result_neg', 'Patient tested — Negative'), ('result_pos', 'Patient tested — Positive (reported)'), ('deceased', 'Patient deceased — no notification possible'), ('untraceable', 'Patient untraceable'), ('waived', 'Notification waived — clinical decision')], default='pending', max_length=15)),
                ('notified_at', models.DateTimeField(blank=True, null=True)),
                ('clinician_name', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to='transfusion.lookbackcampaign')),
                ('issue_tx', models.ForeignKey(help_text='The original issue transaction for the suspect unit', on_delete=django.db.models.deletion.PROTECT, related_name='+', to='transfusion.issuetransaction')),
                ('notified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lookback_notifications', to='patients.patient')),
            ],
        ),
    ]
