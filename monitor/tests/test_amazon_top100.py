from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import requests
from django.test import TestCase

from monitor.amazon_top100 import collect_amazon_top100
from monitor.discovery import process_discovery_review
from monitor.models import DiscoveryEvent, DiscoveryNotification, DiscoverySource


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def response(html):
    result = Mock(spec=requests.Response)
    result.text = html
    result.status_code = 200
    result.headers = {}
    result.is_redirect = False
    return result


class AmazonTop100IntegrationTests(TestCase):
    def test_controlled_html_builds_baseline_then_detects_new_product(self):
        source = DiscoverySource.objects.create(
            name="Figuras de acción",
            url="https://www.amazon.com.mx/gp/bestsellers/toys/23566061011",
            source_type=DiscoverySource.SourceType.AMAZON_TOP_100,
            price_drop_percent=Decimal("5"),
        )
        session = Mock()
        session.get.side_effect = [
            response(fixture("amazon_discovery_page_1.html")),
            response(fixture("amazon_discovery_page_2.html")),
        ]

        review = collect_amazon_top100(source.url, session=session)
        baseline = process_discovery_review(
            source,
            review.items,
            pages_found=review.pages_found,
            is_complete=review.is_complete,
        )

        self.assertTrue(review.is_complete)
        self.assertEqual(baseline.notifications_created, 0)
        self.assertEqual(source.products.count(), 3)

        second = process_discovery_review(source, [
            *review.items,
            {
                "external_id": "B000000004",
                "name": "Producto nuevo",
                "price": "499.00",
                "url": "https://www.amazon.com.mx/dp/B000000004",
                "position": 4,
            },
        ], pages_found=2, is_complete=True)

        event = second.events.get(event_type=DiscoveryEvent.EventType.NEW)
        self.assertEqual(event.product.external_id, "B000000004")
        self.assertEqual(event.notification.status, DiscoveryNotification.Status.PENDING)
        self.assertEqual(second.notifications_created, 1)
