from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM donors_donation LIKE 'units_generated'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE donors_donation ADD COLUMN units_generated TINYINT(1) NOT NULL DEFAULT 0;")
            cursor.execute("SHOW COLUMNS FROM donors_donor LIKE 'national_id'")
            if cursor.fetchone():
                cursor.execute("ALTER TABLE donors_donor DROP COLUMN national_id;")


class Migration(migrations.Migration):

    dependencies = [
        ('donors', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

