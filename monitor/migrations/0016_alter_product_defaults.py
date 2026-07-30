from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0015_product_groups"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="priority",
            field=models.IntegerField(
                choices=[(10, "Baja"), (20, "Normal"), (30, "Alta")],
                default=30,
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="max_alerts_per_day",
            field=models.PositiveIntegerField(default=99),
        ),
        migrations.AlterField(
            model_name="product",
            name="significant_price_drop_percent",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=5),
        ),
    ]
