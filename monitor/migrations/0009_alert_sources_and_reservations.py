import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("monitor", "0008_alter_monitorrun_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitorrun",
            name="source",
            field=models.CharField(
                choices=[("scraper", "Scraper"), ("creators_api", "Creators API"), ("manual", "Manual")],
                default="scraper",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="monitorrun",
            name="worker_key",
            field=models.CharField(db_index=True, default="scraper:default", max_length=100),
        ),
        migrations.AlterField(
            model_name="productcheck",
            name="run",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="checks", to="monitor.monitorrun",
            ),
        ),
        migrations.AddField(
            model_name="productcheck",
            name="source",
            field=models.CharField(
                choices=[("scraper", "Scraper"), ("creators_api", "Creators API"), ("manual", "Manual")],
                default="scraper", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="productcheck",
            name="requested_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="manual_product_checks", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="alert",
            name="source",
            field=models.CharField(
                choices=[("scraper", "Scraper"), ("creators_api", "Creators API"), ("manual", "Manual")],
                default="scraper", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="alert",
            name="requested_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="requested_alerts", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="alert",
            name="reservation_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="alert",
            name="status",
            field=models.CharField(
                choices=[("processing", "Procesando"), ("sent", "Enviada"),
                         ("skipped", "Omitida"), ("failed", "Fallida")],
                max_length=12,
            ),
        ),
        migrations.AlterModelOptions(
            name="alert",
            options={
                "ordering": ("-created_at",),
                "permissions": [("send_manual_alert", "Puede enviar alertas manuales")],
            },
        ),
    ]
