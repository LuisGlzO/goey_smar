from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.models import Q


class PortableAddIndexConcurrently(AddIndexConcurrently):
    """Build online in PostgreSQL while remaining usable by the SQLite test suite."""

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

    dependencies = [("monitor", "0012_cartsnapshotitem")]

    operations = [
        PortableAddIndexConcurrently(
            model_name="alert",
            index=models.Index(
                fields=("product", "-created_at", "-id"),
                condition=Q(status="sent"),
                name="alert_sent_prod_date_idx",
            ),
        ),
        PortableAddIndexConcurrently(
            model_name="alert",
            index=models.Index(
                fields=("product", "reservation_expires_at"),
                condition=Q(status="processing"),
                name="alert_processing_res_idx",
            ),
        ),
        PortableAddIndexConcurrently(
            model_name="productcheck",
            index=models.Index(
                fields=("product", "source", "-checked_at"),
                name="check_prod_source_date_idx",
            ),
        ),
    ]
