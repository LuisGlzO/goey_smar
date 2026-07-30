import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("monitor", "0014_product_observations")]

    operations = [
        migrations.CreateModel(
            name="ProductGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("description", models.TextField(blank=True)),
                (
                    "color",
                    models.CharField(
                        default="#11999E",
                        max_length=7,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="El color debe tener el formato hexadecimal #RRGGBB.",
                                regex="^#[0-9A-Fa-f]{6}$",
                            )
                        ],
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Grupo de productos",
                "verbose_name_plural": "Grupos de productos",
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="product",
            name="group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="products",
                to="monitor.productgroup",
            ),
        ),
    ]
