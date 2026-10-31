from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
        ('core', '0003_mci_event'),
        ('patients', '0004_patientbloodgroup_sample_optional'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TransfusionConsent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('consent_type', models.CharField(choices=[('written', 'Written — signed consent form'), ('verbal', 'Verbal — witnessed'), ('implied', 'Implied — patient unable to consent (emergency)'), ('parent_guardian', 'Parent/Guardian (minor or incapacitated)')], max_length=20)),
                ('status', models.CharField(choices=[('active', 'Active'), ('withdrawn', 'Withdrawn by patient'), ('expired', 'Expired (>30 days)')], default='active', max_length=10)),
                ('alternatives_discussed', models.BooleanField(default=False)),
                ('risks_explained', models.BooleanField(default=False)),
                ('questions_answered', models.BooleanField(default=False)),
                ('obtained_at', models.DateTimeField()),
                ('form_reference', models.CharField(blank=True, max_length=100)),
                ('emergency_justification', models.TextField(blank=True)),
                ('valid_until', models.DateField(blank=True, null=True)),
                ('withdrawn_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('obtained_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='consents', to='patients.patient')),
                ('withdrawn_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
