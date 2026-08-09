from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            # BloodRequest
            cursor.execute("SHOW COLUMNS FROM patients_bloodrequest LIKE 'required_component'")
            if cursor.fetchone():
                cursor.execute("ALTER TABLE patients_bloodrequest DROP COLUMN required_component;")
            cursor.execute("SHOW COLUMNS FROM patients_bloodrequest LIKE 'required_component_id'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE patients_bloodrequest ADD COLUMN required_component_id BIGINT NOT NULL DEFAULT 1;")
                try:
                    cursor.execute(
                        "ALTER TABLE patients_bloodrequest ADD CONSTRAINT "
                        "fk_bloodrequest_component FOREIGN KEY (required_component_id) "
                        "REFERENCES inventory_bloodcomponent (id);"
                    )
                except Exception:
                    pass

            # Crossmatch
            cursor.execute("SHOW COLUMNS FROM patients_crossmatch LIKE 'blood_unit_id'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE patients_crossmatch ADD COLUMN blood_unit_id BIGINT NOT NULL DEFAULT 0;")
                try:
                    cursor.execute(
                        "ALTER TABLE patients_crossmatch ADD CONSTRAINT "
                        "fk_crossmatch_bloodunit FOREIGN KEY (blood_unit_id) "
                        "REFERENCES inventory_bloodunit (id);"
                    )
                except Exception:
                    pass
            cursor.execute("SHOW COLUMNS FROM patients_crossmatch LIKE 'crossmatch_status'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE patients_crossmatch ADD COLUMN crossmatch_status VARCHAR(20) NOT NULL DEFAULT 'Booked';")
            cursor.execute("SHOW COLUMNS FROM patients_crossmatch LIKE 'booked_at'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE patients_crossmatch ADD COLUMN booked_at DATETIME(6) NOT NULL DEFAULT '2026-01-01 00:00:00.000000';")
            cursor.execute("ALTER TABLE patients_crossmatch MODIFY COLUMN crossmatched_at DATETIME(6) NULL;")


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0001_initial'),
        ('inventory', '0003_fix_schema'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

