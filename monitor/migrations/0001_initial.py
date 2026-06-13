import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MonitorRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("running", "En ejecución"), ("success", "Exitoso"), ("failed", "Fallido")], default="running", max_length=10)),
                ("items_seen", models.PositiveIntegerField(default=0)),
                ("error", models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("asin", models.CharField(max_length=10, unique=True)),
                ("name", models.CharField(max_length=250)),
                ("max_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("priority", models.IntegerField(choices=[(10, "Baja"), (20, "Normal"), (30, "Alta")], default=20)),
                ("is_active", models.BooleanField(default=True)),
                ("cooldown_minutes", models.PositiveIntegerField(default=60)),
                ("max_alerts_per_day", models.PositiveIntegerField(default=3)),
                ("significant_price_drop_percent", models.DecimalField(decimal_places=2, default=5, max_digits=5)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-priority", "name")},
        ),
        migrations.CreateModel(
            name="ProductCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("checked_at", models.DateTimeField(auto_now_add=True)),
                ("availability", models.CharField(choices=[("available", "Disponible"), ("unavailable", "No disponible"), ("unknown", "Desconocido")], max_length=12)),
                ("price", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("move_to_cart_visible", models.BooleanField(default=False)),
                ("unavailable_message_visible", models.BooleanField(default=False)),
                ("product_url", models.URLField(blank=True, max_length=1000)),
                ("raw_text", models.TextField(blank=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checks", to="monitor.product")),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checks", to="monitor.monitorrun")),
            ],
            options={"ordering": ("-checked_at",)},
        ),
        migrations.CreateModel(
            name="Alert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("status", models.CharField(choices=[("sent", "Enviada"), ("skipped", "Omitida"), ("failed", "Fallida")], max_length=8)),
                ("reason", models.CharField(max_length=80)),
                ("details", models.TextField(blank=True)),
                ("check", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alerts", to="monitor.productcheck")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alerts", to="monitor.product")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(model_name="productcheck", index=models.Index(fields=["product", "-checked_at"], name="monitor_pro_product_7e3aba_idx")),
        migrations.AddIndex(model_name="alert", index=models.Index(fields=["product", "-created_at"], name="monitor_ale_product_431d9c_idx")),
    ]

