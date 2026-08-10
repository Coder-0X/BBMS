from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM inventory_bloodcomponent LIKE 'shelf_life_days'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE inventory_bloodcomponent ADD COLUMN shelf_life_days INT NOT NULL DEFAULT 35;")
            cursor.execute("SHOW COLUMNS FROM inventory_bloodcomponent LIKE 'ml_per_unit'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE inventory_bloodcomponent ADD COLUMN ml_per_unit INT NOT NULL DEFAULT 450;")
            cursor.execute("SHOW COLUMNS FROM inventory_bloodcomponent LIKE 'split_percentage'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE inventory_bloodcomponent ADD COLUMN split_percentage DECIMAL(5,2) NULL;")
            cursor.execute("SHOW COLUMNS FROM inventory_bloodcomponent LIKE 'is_active'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE inventory_bloodcomponent ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1;")

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
        ('inventory', '0001_initial'),
        ('donors', '0002_fix_schema'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

