from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from monitor.amazon_discovery import (
    AmazonDiscoveryConfigurationError,
    navigate_amazon_public,
    normalize_amazon_url,
)
from monitor.discovery_collectors import collect_discovery_source
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


class AmazonPublicDiscoveryTests(SimpleTestCase):
    def test_walks_real_next_link_and_deduplicates_asins(self):
        session = Mock()
        session.get.side_effect = [
            response(fixture("amazon_discovery_page_1.html")),
            response(fixture("amazon_discovery_page_2.html")),
        ]
        review = navigate_amazon_public(
            "https://www.amazon.com.mx/start?tag=affiliate#section", session=session
        )
        self.assertTrue(review.is_complete)
        self.assertEqual(review.pages_found, 2)
        self.assertEqual([item["external_id"] for item in review.items], [
            "B000000001", "B000000002", "B000000003"
        ])
        self.assertEqual(str(review.items[0]["price"]), "1299.50")
        self.assertEqual(review.items[0]["position"], 1)
        self.assertEqual(review.items[0]["url"], "https://www.amazon.com.mx/dp/B000000001")
        self.assertEqual(session.get.call_args_list[1].args[0], "https://www.amazon.com.mx/fixture-page-2")

    def test_page_limit_with_a_next_link_is_incomplete(self):
        session = Mock()
        session.get.return_value = response(fixture("amazon_discovery_page_1.html"))
        review = navigate_amazon_public("https://amazon.com.mx/start", max_pages=1, session=session)
        self.assertFalse(review.is_complete)
        self.assertEqual(review.issues, ("page_limit",))
        self.assertEqual(len(review.items), 2)

    def test_cycle_keeps_observations_but_marks_review_incomplete(self):
        session = Mock()
        session.get.side_effect = [
            response(fixture("amazon_discovery_cycle.html")),
            response(fixture("amazon_discovery_cycle.html")),
        ]
        review = navigate_amazon_public("https://amazon.com.mx/first", session=session)
        self.assertFalse(review.is_complete)
        self.assertIn("pagination_cycle", review.issues)
        self.assertEqual(len(review.items), 1)

    def test_captcha_block_empty_error_and_timeout_are_detected(self):
        cases = (
            (response(fixture("amazon_discovery_captcha.html")), "captcha"),
            (response("Access denied", 403), "blocked"),
            (response(""), "empty_page"),
            (response("Sorry! Something went wrong"), "error_page"),
            (requests.Timeout(), "timeout"),
        )
        for outcome, issue in cases:
            with self.subTest(issue=issue):
                session = Mock()
                session.get.side_effect = outcome if isinstance(outcome, Exception) else None
                session.get.return_value = outcome if not isinstance(outcome, Exception) else None
                review = navigate_amazon_public("https://amazon.com.mx/start", session=session)
                self.assertFalse(review.is_complete)
                self.assertEqual(review.issues, (issue,))

    def test_product_hints_without_extractable_products_are_unexpected(self):
        session = Mock()
        session.get.return_value = response('<div data-asin="B000000001"></div>')
        review = navigate_amazon_public("https://amazon.com.mx/start", session=session)
        self.assertFalse(review.is_complete)
        self.assertIn("unexpected_structure", review.issues)

    def test_rejects_non_amazon_hosts_credentials_and_nonstandard_ports(self):
        for url in (
            "https://example.com/path",
            "https://www.amazon.com.evil.example/path",
            "https://user:secret@amazon.com/path",
            "https://amazon.com:444/path",
        ):
            with self.subTest(url=url), self.assertRaises(AmazonDiscoveryConfigurationError):
                normalize_amazon_url(url)

    @patch("monitor.discovery_collectors.collect_amazon_newest")
    def test_common_collector_applies_source_limits_without_specific_rules(self, collect):
        collect.return_value.as_dict.return_value = {
            "items": [], "pages_found": 0, "is_complete": False, "issues": ["timeout"]
        }
        source = Mock(
            source_type=DiscoverySource.SourceType.AMAZON_NEWEST,
            url="https://amazon.com.mx/new",
            configuration={"max_pages": 7, "timeout_seconds": 4},
        )
        self.assertFalse(collect_discovery_source(source)["is_complete"])
        collect.assert_called_once_with(source.url, max_pages=7, timeout=4)
