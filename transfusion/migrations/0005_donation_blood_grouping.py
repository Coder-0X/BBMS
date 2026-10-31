from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('donors', '0001_initial'),
        ('transfusion', '0004_bloodrequest_neonatal'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DonationBloodGrouping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('forward_a', models.CharField(blank=True, choices=[('pos', 'Pos'), ('neg', 'Neg')], max_length=3)),
                ('forward_b', models.CharField(blank=True, choices=[('pos', 'Pos'), ('neg', 'Neg')], max_length=3)),
                ('reverse_a_cells', models.CharField(blank=True, choices=[('pos', 'Pos'), ('neg', 'Neg')], max_length=3)),
                ('reverse_b_cells', models.CharField(blank=True, choices=[('pos', 'Pos'), ('neg', 'Neg')], max_length=3)),
                ('abo_result', models.CharField(choices=[('A', 'A'), ('B', 'B'), ('AB', 'AB'), ('O', 'O')], max_length=2)),
                ('rh_d_result', models.CharField(choices=[('pos', 'D Positive'), ('neg', 'D Negative'), ('weak_d', 'Weak D (Du)')], max_length=10)),
                ('weak_d_test_done', models.BooleanField(default=False, help_text='Weak D (Du) test performed (required for apparent Rh D negative donors)')),
                ('method', models.CharField(choices=[('tube', 'Tube method (manual)'), ('gel', 'Gel / column agglutination'), ('solid_phase', 'Solid phase red cell adherence'), ('automated', 'Automated analyser')], max_length=20)),
                ('reagent_lot', models.CharField(blank=True, max_length=100)),
                ('instrument', models.CharField(blank=True, max_length=100)),
                ('determination_status', models.CharField(choices=[('first', 'First determination only'), ('confirmed', 'Confirmed (≥2 concordant determinations)'), ('discrepant', 'Discrepant — requires investigation')], default='first', max_length=15)),
                ('notes', models.TextField(blank=True)),
                ('performed_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('donation', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='blood_groupings', to='donors.donation')),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('performed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sample', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='donation_groupings', to='transfusion.sample')),
            ],
            options={
                'ordering': ['-performed_at'],
            },
        ),
    ]
