from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM staff_staffprofile LIKE 'role_name'")
            if cursor.fetchone():
                cursor.execute("ALTER TABLE staff_staffprofile CHANGE COLUMN role_name role VARCHAR(20) NOT NULL DEFAULT '';")


class Migration(migrations.Migration):

    dependencies = [
        ('staff', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

