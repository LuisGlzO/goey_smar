from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0017_group_display_order_product_group_order")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="intentionally_not_in_cart",
            field=models.BooleanField(
                default=False,
                help_text="Indica que el producto permanece solo en el sistema de forma intencional.",
            ),
        ),
    ]
