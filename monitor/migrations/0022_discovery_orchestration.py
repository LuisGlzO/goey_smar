from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0021_discoveryevent_discoveryproduct_discoveryrun_and_more")]

    operations = [
        migrations.AddField(
            model_name="discoverysource",
            name="interval_minutes",
            field=models.PositiveIntegerField(default=30),
        ),
        migrations.AddField(
            model_name="discoverysource",
            name="next_run_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="discoverysource",
            name="dispatch_reserved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="discoverynotification",
            name="telegram_message_id",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
