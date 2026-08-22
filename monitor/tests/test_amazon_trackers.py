from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings

from monitor.amazon_discovery import normalize_amazon_url
from monitor.amazon_trackers import collect_amazon_trackers
from monitor.discovery import process_discovery_review
from monitor.discovery_collectors import collect_discovery_source
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
    TELEGRAM_TRACKERS_CHANNEL_ID="private-trackers",
)
class AmazonTrackersIntegrationTests(TestCase):
    def source(self, name="Próximos lanzamientos"):
        return DiscoverySource.objects.create(
            name=name,
            url="https://www.amazon.com.mx/s?k=proximos+lanzamientos&rh=p_n_availability%3A-1",
            source_type=DiscoverySource.SourceType.AMAZON_TRACKERS,
        )

    @override_settings(AMAZON_TRACKERS_DISCOVERY_MAX_PAGES=3)
    def test_collector_reuses_search_extractor_and_source_options(self):
        source = self.source()
        source.configuration = {"timeout_seconds": 7}
        with patch("monitor.discovery_collectors.collect_amazon_trackers") as collect:
            collect.return_value.as_dict.return_value = {
                "items": [], "pages_found": 1, "is_complete": True, "issues": []
            }
            result = collect_discovery_source(source)

        self.assertTrue(result["is_complete"])
        collect.assert_called_once_with(source.url, max_pages=3, timeout=7)

    def test_client_search_url_preserves_keywords_department_and_filters(self):
        url = (
            "https://www.amazon.com.mx/s?k=lego+pokemon&i=toys&"
            "rh=n%3A11260442011%2Cp_n_availability%3A9841525011&dc&"
            "ds=v1%3AgZ0AGaonEzuLo3ef97a0TjLKsr8XnBfOGZpfiU%2FLplc&"
            "__mk_es_MX=\x81M\x81_Í„&qid=1768238662&rnid=9841523011&"
            "ref=sr_nr_p_n_availability_2"
        )

        normalized = normalize_amazon_url(url)

        self.assertIn("k=lego+pokemon", normalized)
        self.assertIn("i=toys", normalized)
        self.assertIn("rh=n%3A11260442011%2Cp_n_availability%3A9841525011", normalized)
        self.assertIn("ds=v1%3AgZ0AGaonEzuLo3ef97a0TjLKsr8XnBfOGZpfiU%2FLplc", normalized)
        self.assertIn("qid=1768238662", normalized)
        self.assertIn("rnid=9841523011", normalized)
        self.assertNotIn("ref=", normalized)

    @patch("monitor.discovery_notifications.send_telegram_message", return_value="tracker-1")
    def test_baseline_then_never_seen_asin_without_price_is_stored_and_notified(self, send):
        source = self.source()
        session = Mock()
        session.get.side_effect = [
            response(fixture("amazon_discovery_page_1.html")),
            response(fixture("amazon_discovery_page_2.html")),
        ]
        review = collect_amazon_trackers(source.url, session=session)
        baseline = process_discovery_review(
            source,
            review.items,
            pages_found=review.pages_found,
            is_complete=review.is_complete,
        )

        self.assertTrue(review.is_complete)
        self.assertEqual(baseline.notifications_created, 0)
        source.refresh_from_db()
        self.assertTrue(source.baseline_established)

        new_item = {
            "external_id": "B000000004",
            "name": "Preventa todavía sin precio",
            "url": "https://www.amazon.com.mx/dp/B000000004",
            "price": None,
        }
        detected = process_discovery_review(source, [*review.items, new_item], is_complete=True)
        event = detected.events.get(event_type=DiscoveryEvent.EventType.NEW)
        notification = DiscoveryNotification.objects.get(event=event)

        self.assertEqual(event.product.external_id, "B000000004")
        self.assertEqual(event.product.name, new_item["name"])
        self.assertEqual(event.product.url, new_item["url"])
        self.assertIsNone(event.product.current_price)
        self.assertIsNotNone(event.product.first_seen_at)
        self.assertEqual(detected.notifications_created, 1)

        self.assertEqual(deliver_discovery_notification(notification.pk), "tracker-1")
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "private-trackers")
        self.assertEqual(send.call_args.kwargs["bot_token"], "private-token")
        self.assertNotIn("Precio:", send.call_args.args[1])

        repeated = process_discovery_review(source, [new_item], is_complete=True)
        self.assertEqual(repeated.notifications_created, 0)
        self.assertEqual(source.products.get(external_id="B000000004").events.count(), 1)
        self.assertEqual(
            (Product.objects.count(), ProductCheck.objects.count(), Alert.objects.count()),
            (0, 0, 0),
        )

    def test_same_asin_keeps_independent_history_per_tracker_source(self):
        first = self.source("Tracker uno")
        second = self.source("Tracker dos")
        process_discovery_review(first, [], is_complete=True)
        process_discovery_review(second, [], is_complete=True)
        item = [{"external_id": "B000000009", "name": "Producto compartido", "price": None}]

        self.assertEqual(process_discovery_review(first, item).notifications_created, 1)
        self.assertEqual(process_discovery_review(second, item).notifications_created, 1)
        self.assertEqual(DiscoveryNotification.objects.count(), 2)
