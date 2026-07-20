from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0006_monitorsettings_anti_false_restock_cooldown"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitorrun",
            name="performance",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
