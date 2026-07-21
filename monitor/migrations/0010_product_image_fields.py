from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0009_alert_sources_and_reservations")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="image_url",
            field=models.URLField(blank=True, max_length=2000),
        ),
        migrations.AddField(
            model_name="product",
            name="image_refreshed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
