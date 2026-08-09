from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM inventory_bloodunit LIKE 'collected_at'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE inventory_bloodunit ADD COLUMN collected_at DATETIME(6) NULL;")
            cursor.execute("SHOW COLUMNS FROM inventory_bloodunit LIKE 'donation_id'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE inventory_bloodunit ADD COLUMN donation_id BIGINT NULL;")
                try:
                    cursor.execute(
                        "ALTER TABLE inventory_bloodunit ADD CONSTRAINT "
                        "fk_bloodunit_donation FOREIGN KEY (donation_id) "
                        "REFERENCES donors_donation (id) ON DELETE CASCADE;"
                    )
                except Exception:
                    pass
            cursor.execute("ALTER TABLE inventory_bloodunit MODIFY COLUMN expiry_date DATE NULL;")


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_seed_components'),
        ('donors', '0002_fix_schema'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

