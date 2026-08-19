from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class AddIndexConcurrentlyIfPostgres(AddIndexConcurrently):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            return super().database_forwards(app_label, schema_editor, from_state, to_state)
        return migrations.AddIndex.database_forwards(
            self, app_label, schema_editor, from_state, to_state
        )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            return super().database_backwards(app_label, schema_editor, from_state, to_state)
        return migrations.AddIndex.database_backwards(
            self, app_label, schema_editor, from_state, to_state
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("monitor", "0019_alert_admin_indexes"),
    ]

    operations = [
        AddIndexConcurrentlyIfPostgres(
            model_name="alert",
            index=models.Index(
                fields=["status", "created_at", "id"],
                name="alert_cleanup_idx",
            ),
        ),
        AddIndexConcurrentlyIfPostgres(
            model_name="productcheck",
            index=models.Index(fields=["checked_at", "id"], name="check_date_id_idx"),
        ),
        AddIndexConcurrentlyIfPostgres(
            model_name="monitorrun",
            index=models.Index(fields=["started_at", "id"], name="run_date_id_idx"),
        ),
    ]
