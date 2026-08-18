from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("monitor", "0018_product_intentionally_not_in_cart"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="alert",
            index=models.Index(fields=["status", "-id"], name="alert_status_id_idx"),
        ),
        AddIndexConcurrently(
            model_name="alert",
            index=models.Index(fields=["source", "-id"], name="alert_source_id_idx"),
        ),
        AddIndexConcurrently(
            model_name="alert",
            index=models.Index(fields=["reason", "-id"], name="alert_reason_id_idx"),
        ),
    ]
