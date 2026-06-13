from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0003_rename_generated_indexes")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="affiliate_url",
            field=models.URLField(
                blank=True,
                help_text="Opcional. Tiene prioridad sobre el tag global de afiliado.",
                max_length=1000,
            ),
        ),
    ]

