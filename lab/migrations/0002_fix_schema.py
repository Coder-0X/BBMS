from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM lab_bloodtest LIKE 'tested_by'")
            if cursor.fetchone():
                cursor.execute("ALTER TABLE lab_bloodtest DROP COLUMN tested_by;")
            cursor.execute("SHOW COLUMNS FROM lab_bloodtest LIKE 'tested_at'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE lab_bloodtest ADD COLUMN tested_at DATETIME(6) NOT NULL DEFAULT '2026-01-01 00:00:00.000000';")


class Migration(migrations.Migration):

    dependencies = [
        ('lab', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

