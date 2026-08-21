from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from monitor.discovery_collectors import collect_discovery_source
from monitor.mercado_libre_discovery import (
    MercadoLibreConfigurationError,
    navigate_mercado_libre_public,
    normalize_mercado_libre_url,
    parse_mercado_libre_page,
)
from monitor.models import DiscoverySource


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def response(html, status=200, headers=None):
    result = Mock(spec=requests.Response)
    result.text = html
    result.status_code = status
    result.headers = headers or {}
    result.is_redirect = status in (301, 302, 303, 307, 308)
    return result


class MercadoLibrePublicDiscoveryTests(SimpleTestCase):
    def test_parses_stable_listing_id_current_price_and_canonical_url(self):
        items, next_url, hints, malformed = parse_mercado_libre_page(
            fixture("mercado_libre_seller_page_1.html"),
            "https://listado.mercadolibre.com.mx/pagina/tieronezone/",
        )
        self.assertEqual(hints, 2)
        self.assertEqual(malformed, 0)
        self.assertEqual(items[0], {
            "external_id": "MLM123456789",
            "name": "Producto Uno",
            "price": items[0]["price"],
            "url": "https://articulo.mercadolibre.com.mx/MLM-123456789",
        })
        self.assertEqual(str(items[0]["price"]), "1299.50")
        self.assertEqual(str(items[1]["price"]), "800.00")
        self.assertEqual(
            next_url,
            "https://listado.mercadolibre.com.mx/pagina/tieronezone/_Desde_51",
        )

    def test_walks_all_pages_and_deduplicates_listing_ids(self):
        session = Mock()
        session.get.side_effect = [
            response(fixture("mercado_libre_seller_page_1.html")),
            response(fixture("mercado_libre_seller_page_2.html")),
        ]
        review = navigate_mercado_libre_public(
            "https://listado.mercadolibre.com.mx/pagina/tieronezone/#tracking", session=session
        )
        self.assertTrue(review.is_complete)
        self.assertEqual(review.pages_found, 2)
        self.assertEqual(
            [item["external_id"] for item in review.items],
            ["MLM123456789", "MLM987654321", "MLM555666777"],
        )
        self.assertEqual(
            session.get.call_args_list[1].args[0],
            "https://listado.mercadolibre.com.mx/pagina/tieronezone/_Desde_51",
        )

    def test_partial_or_suspicious_pages_never_claim_a_complete_review(self):
        malformed = fixture("mercado_libre_seller_page_1.html").replace(
            '<span class="andes-money-amount__fraction">800</span>', ""
        )
        cases = (
            (response(malformed), "incomplete_products"),
            (response("Access denied", 403), "blocked"),
            (response("captcha"), "captcha"),
            (response(""), "empty_page"),
            (requests.Timeout(), "timeout"),
        )
        for outcome, issue in cases:
            with self.subTest(issue=issue):
                session = Mock()
                session.get.side_effect = outcome if isinstance(outcome, Exception) else None
                session.get.return_value = outcome if not isinstance(outcome, Exception) else None
                review = navigate_mercado_libre_public(
                    "https://listado.mercadolibre.com.mx/pagina/tieronezone/", session=session
                )
                self.assertFalse(review.is_complete)
                self.assertIn(issue, review.issues)

    def test_page_limit_and_cycle_are_incomplete(self):
        session = Mock()
        session.get.return_value = response(fixture("mercado_libre_seller_page_1.html"))
        limited = navigate_mercado_libre_public(
            "https://listado.mercadolibre.com.mx/pagina/tieronezone/",
            max_pages=1,
            session=session,
        )
        self.assertEqual(limited.issues, ("page_limit",))
        self.assertFalse(limited.is_complete)

    def test_rejects_foreign_hosts_credentials_and_nonstandard_ports(self):
        for url in (
            "https://example.com/path",
            "https://mercadolibre.com.mx.evil.example/path",
            "https://user:secret@mercadolibre.com.mx/path",
            "https://listado.mercadolibre.com.mx:444/path",
        ):
            with self.subTest(url=url), self.assertRaises(MercadoLibreConfigurationError):
                normalize_mercado_libre_url(url)

    @patch("monitor.discovery_collectors.navigate_mercado_libre_public")
    def test_common_collector_uses_mercado_libre_specific_limits(self, navigate):
        navigate.return_value.as_dict.return_value = {
            "items": [], "pages_found": 0, "is_complete": False, "issues": ["timeout"]
        }
        source = Mock(
            source_type=DiscoverySource.SourceType.MERCADO_LIBRE_SELLER,
            url="https://listado.mercadolibre.com.mx/pagina/tieronezone/",
            configuration={"max_pages": 7, "timeout_seconds": 4},
        )
        self.assertFalse(collect_discovery_source(source)["is_complete"])
        navigate.assert_called_once_with(source.url, max_pages=7, timeout=4)
