from decimal import Decimal

from django.test import SimpleTestCase

from monitor.scraper import extract_asin, item_from_payload, parse_price


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
