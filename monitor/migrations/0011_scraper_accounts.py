from django.db import migrations, models
import django.db.models.deletion


def create_scraper_accounts(apps, schema_editor):
    ScraperAccount = apps.get_model("monitor", "ScraperAccount")
    Product = apps.get_model("monitor", "Product")
    ScraperAccount.objects.get_or_create(key="amazon_a", defaults={"name": "Amazon A"})
    ScraperAccount.objects.get_or_create(key="amazon_b", defaults={"name": "Amazon B"})
    Product.objects.filter(scraper_account_id__isnull=True).update(scraper_account_id="amazon_a")


class Migration(migrations.Migration):
    dependencies = [("monitor", "0010_product_image_fields")]
    operations = [
        migrations.CreateModel(
            name="ScraperAccount",
            fields=[
                ("key", models.SlugField(max_length=50, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100)),
            ],
            options={"verbose_name": "Cuenta scraper de Amazon", "verbose_name_plural": "Cuentas scraper de Amazon", "ordering": ("key",)},
        ),
        migrations.AddField(
            model_name="product", name="scraper_account",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="products", to="monitor.scraperaccount"),
        ),
        migrations.RunPython(create_scraper_accounts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="product", name="scraper_account",
            field=models.ForeignKey(default="amazon_a", on_delete=django.db.models.deletion.PROTECT, related_name="products", to="monitor.scraperaccount"),
        ),
    ]
