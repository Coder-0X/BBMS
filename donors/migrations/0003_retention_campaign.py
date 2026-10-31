from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('donors', '0002_donor_phenotype_milestone'),
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RetentionCampaign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('segment', models.CharField(choices=[
                    ('lapsed_3m', 'Lapsed 3+ months'),
                    ('lapsed_6m', 'Lapsed 6+ months'),
                    ('lapsed_12m', 'Lapsed 12+ months'),
                    ('new_never_returned', 'First-time, never returned'),
                    ('specific_group', 'Specific blood group'),
                    ('high_value', 'Veteran donors (10+ donations)'),
                    ('custom', 'Custom'),
                ], max_length=30)),
                ('target_abo', models.CharField(blank=True, choices=[('A','A'),('B','B'),('AB','AB'),('O','O')], max_length=2, help_text='Leave blank for all ABO groups')),
                ('target_rh', models.CharField(blank=True, choices=[('pos','Positive'),('neg','Negative'),('','All')], max_length=10, help_text='Leave blank for all Rh types')),
                ('channel', models.CharField(choices=[
                    ('sms', 'SMS'),
                    ('email', 'Email'),
                    ('call', 'Phone Call'),
                    ('letter', 'Letter'),
                    ('mixed', 'Mixed'),
                ], max_length=10)),
                ('message_template', models.TextField(help_text='Use {name} and {last_donation} as placeholders.')),
                ('goal_donations', models.PositiveIntegerField(default=0, help_text='Target number of re-donations')),
                ('status', models.CharField(choices=[
                    ('draft', 'Draft'),
                    ('active', 'Active'),
                    ('paused', 'Paused'),
                    ('closed', 'Closed'),
                ], default='draft', max_length=10)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='retention_campaigns', to='core.branch')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='CampaignEnrollment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[
                    ('enrolled', 'Enrolled — not yet contacted'),
                    ('contacted', 'Contacted'),
                    ('responded', 'Responded'),
                    ('appointment_booked', 'Appointment Booked'),
                    ('donated', 'Re-donated'),
                    ('declined', 'Declined'),
                    ('unreachable', 'Unreachable'),
                    ('ineligible', 'Became Ineligible'),
                ], default='enrolled', max_length=20)),
                ('enrolled_at', models.DateTimeField(auto_now_add=True)),
                ('contacted_at', models.DateTimeField(blank=True, null=True)),
                ('responded_at', models.DateTimeField(blank=True, null=True)),
                ('donated_at', models.DateTimeField(blank=True, null=True)),
                ('outcome_notes', models.TextField(blank=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='enrollments', to='donors.retentioncampaign')),
                ('donor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='campaign_enrollments', to='donors.donor')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('campaign', 'donor')},
            },
        ),
    ]
