from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings

from monitor.amazon_newest import collect_amazon_newest
from monitor.discovery import process_discovery_review
from monitor.discovery_notifications import deliver_discovery_notification
from monitor.models import (
    Alert,
    DiscoveryEvent,
    DiscoveryNotification,
    DiscoverySource,
    Product,
    ProductCheck,
)


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


@override_settings(
    TELEGRAM_BOT_TOKEN="commercial-token",
    TELEGRAM_DISCOVERY_BOT_TOKEN="private-token",
    TELEGRAM_NEWEST_CHANNEL_ID="private-newest",
)
class AmazonNewestIntegrationTests(TestCase):
    def source(self, name="Manga Panini"):
        return DiscoverySource.objects.create(
            name=name,
            url="https://www.amazon.com.mx/s?k=manga+panini&s=date-desc-rank",
            source_type=DiscoverySource.SourceType.AMAZON_NEWEST,
        )

    def complete_review(self, source):
        session = Mock()
        session.get.side_effect = [
            response(fixture("amazon_discovery_page_1.html")),
            response(fixture("amazon_discovery_page_2.html")),
        ]
        review = collect_amazon_newest(source.url, session=session)
        return review, process_discovery_review(
            source,
            review.items,
            pages_found=review.pages_found,
            is_complete=review.is_complete,
        )

    def test_complete_baseline_deduplicates_pages_and_accepts_missing_price(self):
        source = self.source()
        review, run = self.complete_review(source)

        self.assertTrue(review.is_complete)
        self.assertEqual(run.pages_found, 2)
        self.assertEqual(source.products.count(), 3)
        self.assertEqual(source.products.get(external_id="B000000002").current_price, None)
        self.assertEqual(run.events_created, 3)
        self.assertEqual(run.notifications_created, 0)
        source.refresh_from_db()
        self.assertTrue(source.baseline_established)

    @patch("monitor.discovery_notifications.send_telegram_message", return_value="newest-1")
    def test_only_never_seen_asin_notifies_once_to_newest_channel(self, send):
        source = self.source()
        review, _baseline = self.complete_review(source)
        second = process_discovery_review(source, [
            *review.items,
            {
                "external_id": "B000000004",
                "name": "Manga nuevo sin precio",
                "url": "https://www.amazon.com.mx/dp/B000000004",
            },
        ], pages_found=2, is_complete=True)

        event = second.events.get(event_type=DiscoveryEvent.EventType.NEW)
        notification = event.notification
        self.assertIsNone(event.product.current_price)
        self.assertEqual(second.notifications_created, 1)
        self.assertEqual(deliver_discovery_notification(notification.pk), "newest-1")
        self.assertEqual(deliver_discovery_notification(notification.pk), "newest-1")
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "private-newest")
        self.assertEqual(send.call_args.kwargs["bot_token"], "private-token")
        self.assertEqual(
            (Product.objects.count(), ProductCheck.objects.count(), Alert.objects.count()),
            (0, 0, 0),
        )

    def test_same_asin_has_independent_history_in_each_source(self):
        first = self.source("Primera")
        second = self.source("Segunda")
        process_discovery_review(first, [], pages_found=1, is_complete=True)
        process_discovery_review(second, [], pages_found=1, is_complete=True)
        item = [{"external_id": "B000000004", "name": "Compartido"}]

        first_run = process_discovery_review(first, item, pages_found=1, is_complete=True)
        second_run = process_discovery_review(second, item, pages_found=1, is_complete=True)

        self.assertEqual(first_run.notifications_created, 1)
        self.assertEqual(second_run.notifications_created, 1)
        self.assertEqual(DiscoveryNotification.objects.count(), 2)
