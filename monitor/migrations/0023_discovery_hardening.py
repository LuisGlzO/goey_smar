from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0022_discovery_orchestration")]

    operations = [
        migrations.AddField(
            model_name="discoveryrun", name="is_diagnostic",
            field=models.BooleanField(default=False, help_text="La revisión solo inspeccionó la fuente; no modificó baseline, productos ni eventos."),
        ),
        migrations.AddField(
            model_name="discoveryrun", name="issues",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddIndex("discoveryrun", models.Index(fields=["source", "-started_at"], name="discovery_run_source_idx")),
        migrations.AddIndex("discoveryrun", models.Index(fields=["status", "-started_at"], name="discovery_run_status_idx")),
        migrations.AddIndex("discoveryproduct", models.Index(fields=["source", "-last_seen_at"], name="discovery_last_seen_idx")),
        migrations.AddIndex("discoveryevent", models.Index(fields=["event_type", "-created_at"], name="discovery_event_type_idx")),
        migrations.AddIndex("discoveryevent", models.Index(fields=["run", "-created_at"], name="discovery_event_run_idx")),
        migrations.AddIndex("discoverynotification", models.Index(fields=["status", "-created_at"], name="discovery_notif_status_idx")),
    ]
