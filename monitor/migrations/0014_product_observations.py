from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0013_rule_engine_indexes")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="observations",
            field=models.TextField(blank=True),
        ),
    ]
