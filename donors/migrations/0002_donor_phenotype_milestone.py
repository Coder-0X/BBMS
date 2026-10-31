from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('donors', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DonorPhenotype',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('typed_at', models.DateTimeField()),
                ('method', models.CharField(choices=[('serology', 'Serology (tube/gel)'), ('molecular', 'Molecular genotyping')], default='serology', max_length=15)),
                ('C', models.BooleanField(blank=True, null=True)),
                ('c', models.BooleanField(blank=True, null=True)),
                ('E', models.BooleanField(blank=True, null=True)),
                ('e', models.BooleanField(blank=True, null=True)),
                ('K', models.BooleanField(blank=True, null=True)),
                ('k', models.BooleanField(blank=True, null=True)),
                ('Fya', models.BooleanField(blank=True, null=True)),
                ('Fyb', models.BooleanField(blank=True, null=True)),
                ('Jka', models.BooleanField(blank=True, null=True)),
                ('Jkb', models.BooleanField(blank=True, null=True)),
                ('M', models.BooleanField(blank=True, null=True)),
                ('N', models.BooleanField(blank=True, null=True)),
                ('S', models.BooleanField(blank=True, null=True)),
                ('s', models.BooleanField(blank=True, null=True)),
                ('Lea', models.BooleanField(blank=True, null=True)),
                ('Leb', models.BooleanField(blank=True, null=True)),
                ('P1', models.BooleanField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('donor', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='phenotype', to='donors.donor')),
                ('typed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='DonorMilestone',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('milestone_type', models.CharField(choices=[('first', '1st Donation'), ('fifth', '5th Donation'), ('tenth', '10th Donation'), ('25th', '25th Donation'), ('50th', '50th Donation'), ('100th', '100th Donation'), ('annual', 'Annual Donor')], max_length=10)),
                ('achieved_at', models.DateField()),
                ('notified', models.BooleanField(default=False)),
                ('certificate_generated', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('donor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='milestones', to='donors.donor')),
            ],
            options={'unique_together': {('donor', 'milestone_type')}},
        ),
    ]
