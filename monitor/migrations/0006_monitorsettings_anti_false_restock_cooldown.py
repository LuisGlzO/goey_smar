from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0005_monitorsettings_monitorrun_skipped"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitorsettings",
            name="anti_false_restock_cooldown_minutes",
            field=models.PositiveIntegerField(
                "Cooldown anti-falso-restock (minutos)",
                default=0,
                help_text=(
                    "Minutos para bloquear una nueva alerta del mismo producto despues "
                    "de una alerta enviada. Use 0 para desactivar."
                ),
            ),
        ),
    ]
