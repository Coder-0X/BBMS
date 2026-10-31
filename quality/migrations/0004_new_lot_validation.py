from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0003_non_conformance_capa'),
        ('core', '0001_initial'),
        ('audit', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NewLotValidation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[
                    ('pending',   'Pending — not yet tested'),
                    ('in_review', 'Testing complete — awaiting review'),
                    ('approved',  'Approved for clinical use'),
                    ('rejected',  'Rejected — does not meet acceptance criteria'),
                ], default='pending', max_length=12)),
                ('initiated_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_notes', models.TextField(blank=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.branch')),
                ('esign', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='audit.electronicsignature')),
                ('initiated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('nc', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='lot_validations', to='quality.nonconformance')),
                ('new_lot', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='lot_validation', to='quality.reagentlot')),
                ('reference_lot', models.ForeignKey(blank=True, help_text='Current in-use lot used for parallel comparison', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='quality.reagentlot')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='LotValidationResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sample_label', models.CharField(help_text='e.g. "Known A2 cell", "Group O neg control"', max_length=100)),
                ('ref_grade', models.CharField(choices=[
                    ('0',  'Negative (0)'),
                    ('w+', 'Weak Positive (w+)'),
                    ('1+', '1+'),
                    ('2+', '2+'),
                    ('3+', '3+'),
                    ('4+', '4+ — Strong'),
                    ('hem', 'Haemolysis'),
                    ('mf',  'Mixed field'),
                ], max_length=5)),
                ('new_grade', models.CharField(choices=[
                    ('0',  'Negative (0)'),
                    ('w+', 'Weak Positive (w+)'),
                    ('1+', '1+'),
                    ('2+', '2+'),
                    ('3+', '3+'),
                    ('4+', '4+ — Strong'),
                    ('hem', 'Haemolysis'),
                    ('mf',  'Mixed field'),
                ], max_length=5)),
                ('passed', models.BooleanField(default=True)),
                ('comment', models.CharField(blank=True, max_length=200)),
                ('validation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='validation_results', to='quality.newlotvalidation')),
            ],
        ),
    ]
