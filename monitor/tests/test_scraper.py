from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from monitor.scraper import (
    CHROMIUM_PROFILE_LOCK_FILES,
    ScrapedItem,
    cleanup_chromium_profile_locks,
    extract_asin,
    item_from_payload,
    item_score,
    parse_price,
    scrape_saved_items,
    validate_profile_owner,
)


class ScraperParsingTests(SimpleTestCase):
    def test_extracts_asin_from_data_attribute_or_url(self):
        self.assertEqual(extract_asin("", "b0abc12345"), "B0ABC12345")
        self.assertEqual(extract_asin("/dp/B0ABC12345/ref=cart"), "B0ABC12345")

    def test_parses_common_price_formats(self):
        self.assertEqual(parse_price("$1,299.99"), Decimal("1299.99"))
        self.assertEqual(parse_price("MXN 899.00"), Decimal("899.00"))

    def test_builds_unavailable_item(self):
        item = item_from_payload({
            "asin": "B0ABC12345",
            "href": "/dp/B0ABC12345",
            "text": "Producto de prueba Sin stock",
        })
        self.assertTrue(item.unavailable_message_visible)
        self.assertFalse(item.move_to_cart_visible)

    def test_detects_selected_seller_unavailable_message(self):
        item = item_from_payload({
            "asin": "B0ABC12345",
            "href": "/dp/B0ABC12345",
            "text": "Este producto ya no está disponible del vendedor que has seleccionado.",
        })
        self.assertTrue(item.unavailable_message_visible)

    def test_item_keeps_source(self):
        item = item_from_payload({
            "asin": "B0ABC12345",
            "href": "/dp/B0ABC12345",
            "text": "Producto $549.00",
            "source": "cart",
        })
        self.assertEqual(item.source, "cart")

    def test_cart_item_wins_over_saved_duplicate(self):
        cart_item = ScrapedItem(
            asin="B0ABC12345",
            price=Decimal("549.00"),
            move_to_cart_visible=False,
            unavailable_message_visible=False,
            product_url="https://www.amazon.com.mx/dp/B0ABC12345",
            raw_text="Carrito",
            source="cart",
        )
        saved_item = ScrapedItem(
            asin="B0ABC12345",
            price=Decimal("549.00"),
            move_to_cart_visible=True,
            unavailable_message_visible=False,
            product_url="https://www.amazon.com.mx/dp/B0ABC12345",
            raw_text="Guardado para mas tarde con mas texto",
            source="saved",
        )
        self.assertGreater(item_score(cart_item), item_score(saved_item))

    def test_cleanup_chromium_profile_locks_removes_stale_files(self):
        with TemporaryDirectory() as profile_dir:
            for filename in CHROMIUM_PROFILE_LOCK_FILES:
                (Path(profile_dir) / filename).write_text("")

            cleanup_chromium_profile_locks(profile_dir)

            for filename in CHROMIUM_PROFILE_LOCK_FILES:
                self.assertFalse((Path(profile_dir) / filename).exists())

    def test_profile_owner_rejects_a_different_account(self):
        with TemporaryDirectory() as profile_dir:
            validate_profile_owner(profile_dir, "amazon_a")
            validate_profile_owner(profile_dir, "amazon_a")
            with self.assertRaisesMessage(RuntimeError, "amazon_a"):
                validate_profile_owner(profile_dir, "amazon_b")

    @override_settings(AMAZON_SCRAPER_MAX_ATTEMPTS=2, AMAZON_SCRAPER_RETRY_DELAY_SECONDS=0)
    @patch("monitor.scraper.scrape_saved_items_once")
    def test_scrape_saved_items_retries_infrastructure_error(self, scrape_saved_items_once):
        scrape_saved_items_once.side_effect = [RuntimeError("Page.goto: Timeout 45000ms exceeded"), []]

        self.assertEqual(scrape_saved_items("amazon_a", "/tmp/profile"), [])

        self.assertEqual(scrape_saved_items_once.call_count, 2)

    @override_settings(AMAZON_SCRAPER_MAX_ATTEMPTS=2, AMAZON_SCRAPER_RETRY_DELAY_SECONDS=0)
    @patch("monitor.scraper.scrape_saved_items_once")
    def test_scrape_saved_items_does_not_retry_session_error(self, scrape_saved_items_once):
        scrape_saved_items_once.side_effect = RuntimeError("La sesion de Amazon no es valida")

        with self.assertRaisesMessage(RuntimeError, "sesion de Amazon"):
            scrape_saved_items("amazon_a", "/tmp/profile")

        scrape_saved_items_once.assert_called_once()
