from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0004_product_affiliate_url")]

    operations = [
        migrations.CreateModel(
            name="MonitorSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True)),
                (
                    "active_from",
                    models.TimeField(
                        blank=True,
                        help_text="Hora local desde la que se permite monitorear. Vacio significa sin limite.",
                        null=True,
                    ),
                ),
                (
                    "active_until",
                    models.TimeField(
                        blank=True,
                        help_text="Hora local hasta la que se permite monitorear. Vacio significa sin limite.",
                        null=True,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Configuracion del monitor",
                "verbose_name_plural": "Configuracion del monitor",
            },
        ),
        migrations.AlterField(
            model_name="monitorrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("running", "En ejecuciÃ³n"),
                    ("success", "Exitoso"),
                    ("failed", "Fallido"),
                    ("skipped", "Omitido"),
                ],
                default="running",
                max_length=10,
            ),
        ),
    ]
