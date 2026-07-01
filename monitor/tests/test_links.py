from django.test import SimpleTestCase, override_settings

from monitor.links import affiliate_url_for
from monitor.models import Product


class AffiliateLinkTests(SimpleTestCase):
    def product(self, affiliate_url=""):
        return Product(asin="B0ABC12345", name="Producto", max_price=100, affiliate_url=affiliate_url)

    @override_settings(
        AMAZON_BASE_URL="https://www.amazon.com.mx",
        AMAZON_ASSOCIATE_TAG="cliente-20",
        AMAZON_CREATORS_API_PARTNER_TAG="",
    )
    def test_builds_canonical_affiliate_url_from_asin(self):
        self.assertEqual(
            affiliate_url_for(self.product(), "https://example.com/original"),
            "https://www.amazon.com.mx/dp/B0ABC12345?tag=cliente-20&linkCode=ogi&th=1&psc=1",
        )

    @override_settings(AMAZON_ASSOCIATE_TAG="cliente-20", AMAZON_CREATORS_API_PARTNER_TAG="")
    def test_product_override_has_priority(self):
        override = "https://amzn.to/enlace-especial"
        self.assertEqual(affiliate_url_for(self.product(override), "https://example.com/original"), override)

    @override_settings(AMAZON_ASSOCIATE_TAG="", AMAZON_CREATORS_API_PARTNER_TAG="")
    def test_falls_back_to_detected_url_without_configuration(self):
        original = "https://www.amazon.com.mx/dp/B0ABC12345"
        self.assertEqual(affiliate_url_for(self.product(), original), original)

    @override_settings(
        AMAZON_BASE_URL="https://www.amazon.com.mx",
        AMAZON_ASSOCIATE_TAG="prismaa-20",
        AMAZON_CREATORS_API_PARTNER_TAG="goeygeeks2023-20",
    )
    def test_creators_partner_tag_takes_priority_over_legacy_tag(self):
        self.assertEqual(
            affiliate_url_for(self.product(), "https://example.com/original"),
            "https://www.amazon.com.mx/dp/B0ABC12345?tag=goeygeeks2023-20&linkCode=ogi&th=1&psc=1",
        )
