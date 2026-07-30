from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from monitor.amazon_creators import CreatorProductContent
from monitor.models import Product, ScraperAccount


@override_settings(
    AMAZON_CREATORS_API_CLIENT_ID="client",
    AMAZON_CREATORS_API_CLIENT_SECRET="secret",
    AMAZON_CREATORS_API_PARTNER_TAG="tag-20",
    AMAZON_CREATORS_API_BATCH_SIZE=10,
    AMAZON_CREATORS_API_BATCH_DELAY_SECONDS=0,
)
class RefreshProductCatalogTests(TestCase):
    def setUp(self):
        account = ScraperAccount.objects.get(key="amazon_a")
        self.product = Product.objects.create(
            asin="B0ABC12345",
            scraper_account=account,
            name="Nombre anterior",
            image_url="https://old.example/image.jpg",
            max_price=100,
        )

    @patch("monitor.management.commands.refresh_product_catalog.get_products_content")
    def test_updates_name_and_image_from_creators_api(self, get_products_content):
        get_products_content.return_value = {
            self.product.asin: CreatorProductContent(
                title="Nombre oficial",
                image_url="https://new.example/image.jpg",
                detail_page_url="",
            )
        }

        stdout = StringIO()
        call_command("refresh_product_catalog", batch_delay=0, stdout=stdout)

        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Nombre oficial")
        self.assertEqual(self.product.image_url, "https://new.example/image.jpg")
        self.assertIsNotNone(self.product.image_refreshed_at)
        self.assertIn("updated=1", stdout.getvalue())

    @patch("monitor.management.commands.refresh_product_catalog.get_products_content")
    def test_empty_api_fields_do_not_erase_catalog_content(self, get_products_content):
        get_products_content.return_value = {
            self.product.asin: CreatorProductContent("", "", "")
        }

        call_command("refresh_product_catalog", batch_delay=0)

        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Nombre anterior")
        self.assertEqual(self.product.image_url, "https://old.example/image.jpg")
        self.assertIsNone(self.product.image_refreshed_at)

    @patch("monitor.management.commands.refresh_product_catalog.get_products_content")
    def test_dry_run_does_not_persist_changes(self, get_products_content):
        get_products_content.return_value = {
            self.product.asin: CreatorProductContent(
                "Nombre oficial", "https://new.example/image.jpg", ""
            )
        }

        call_command("refresh_product_catalog", batch_delay=0, dry_run=True)

        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Nombre anterior")
        self.assertEqual(self.product.image_url, "https://old.example/image.jpg")

    @patch("monitor.management.commands.refresh_product_catalog.get_products_content")
    def test_processes_catalog_in_api_sized_batches(self, get_products_content):
        for index in range(10):
            Product.objects.create(
                asin=f"A{index:09d}",
                scraper_account=self.product.scraper_account,
                name=f"Producto {index}",
                max_price=100,
            )
        get_products_content.return_value = {}

        call_command("refresh_product_catalog", batch_size=10, batch_delay=0)

        self.assertEqual(get_products_content.call_count, 2)
        self.assertEqual(len(get_products_content.call_args_list[0].args[0]), 10)
        self.assertEqual(len(get_products_content.call_args_list[1].args[0]), 1)
