from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0006_staff_competency'),
        ('core', '0001_initial'),
        ('audit', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TransfusionCommittee',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('meeting_type', models.CharField(choices=[
                    ('quarterly', 'Quarterly Clinical Governance Review'),
                    ('annual',    'Annual Governance & Audit Review'),
                    ('ad_hoc',   'Ad-Hoc / Special Meeting'),
                ], max_length=15)),
                ('scheduled_date', models.DateField()),
                ('actual_date', models.DateField(blank=True, null=True)),
                ('attendees_text', models.TextField(help_text='List of attendees — one per line: "Name, Role"')),
                ('quorum_met', models.BooleanField(default=True)),
                ('status', models.CharField(choices=[
                    ('planned',          'Planned'),
                    ('held',             'Meeting Held — minutes pending'),
                    ('minutes_draft',    'Minutes in Draft'),
                    ('minutes_approved', 'Minutes Approved'),
                ], default='planned', max_length=20)),
                ('qi_reviewed', models.JSONField(blank=True, default=list)),
                ('agenda_text', models.TextField(blank=True)),
                ('minutes_text', models.TextField(blank=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name='committee_meetings', to='core.branch')),
                ('chair', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                             related_name='+', to=settings.AUTH_USER_MODEL)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                   related_name='+', to=settings.AUTH_USER_MODEL)),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                             related_name='+', to='audit.electronicsignature')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                  related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-scheduled_date']},
        ),
        migrations.CreateModel(
            name='CommitteeAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.TextField()),
                ('owner_name', models.CharField(max_length=200)),
                ('due_date', models.DateField()),
                ('status', models.CharField(choices=[
                    ('open',        'Open'),
                    ('in_progress', 'In Progress'),
                    ('completed',   'Completed'),
                    ('deferred',    'Deferred to Next Meeting'),
                ], default='open', max_length=15)),
                ('completion_notes', models.TextField(blank=True)),
                ('completed_at', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('meeting', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                               related_name='actions', to='quality.transfusioncommittee')),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                             related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['due_date']},
        ),
    ]
