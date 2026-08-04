from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0016_alter_product_defaults")]

    operations = [
        migrations.AddField(
            model_name="productgroup",
            name="display_order",
            field=models.PositiveIntegerField(db_index=True, default=0),
        ),
        migrations.AddField(
            model_name="product",
            name="group_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name="productgroup",
            options={
                "ordering": ("display_order", "name", "pk"),
                "verbose_name": "Grupo de productos",
                "verbose_name_plural": "Grupos de productos",
            },
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(fields=("group", "group_order"), name="product_group_order_idx"),
        ),
    ]
