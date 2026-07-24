from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("monitor", "0011_scraper_accounts")]

    operations = [
        migrations.CreateModel(
            name="CartSnapshotItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("asin", models.CharField(max_length=10)),
                ("source", models.CharField(max_length=12)),
                ("price", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("product_url", models.URLField(blank=True, max_length=1000)),
                ("raw_text", models.TextField(blank=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cart_items", to="monitor.monitorrun")),
                ("scraper_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cart_snapshot_items", to="monitor.scraperaccount")),
            ],
            options={"ordering": ("scraper_account_id", "asin")},
        ),
        migrations.AddConstraint(
            model_name="cartsnapshotitem",
            constraint=models.UniqueConstraint(fields=("run", "asin"), name="unique_cart_item_per_run"),
        ),
        migrations.AddIndex(
            model_name="cartsnapshotitem",
            index=models.Index(fields=["scraper_account", "asin"], name="monitor_car_scraper_817664_idx"),
        ),
    ]
