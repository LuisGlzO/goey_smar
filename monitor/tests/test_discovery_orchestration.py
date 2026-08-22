from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from monitor.discovery import process_discovery_review
from monitor.discovery_notifications import deliver_discovery_notification
from monitor.models import DiscoveryNotification, DiscoveryRun, DiscoverySource
from monitor.tasks import cleanup_discovery_history, dispatch_due_discovery_sources, run_discovery_source


CHANNELS = {
    "TELEGRAM_BOT_TOKEN": "commercial-token",
    "TELEGRAM_DISCOVERY_BOT_TOKEN": "private-token",
    "TELEGRAM_TOP100_CHANNEL_ID": "private-top100",
    "TELEGRAM_NEWEST_CHANNEL_ID": "private-newest",
    "TELEGRAM_TRACKERS_CHANNEL_ID": "private-trackers",
    "TELEGRAM_MERCADOLIBRE_CHANNEL_ID": "private-ml",
}


class DiscoveryOrchestrationTests(TestCase):
    def source(self, name="Source", **values):
        defaults = dict(
            name=name,
            url="https://example.com/public",
            source_type=DiscoverySource.SourceType.AMAZON_TOP_100,
            price_drop_percent=Decimal("5"),
        )
        defaults.update(values)
        return DiscoverySource.objects.create(**defaults)

    @patch("monitor.tasks.run_discovery_source.apply_async")
    def test_dispatches_only_due_active_sources_and_staggers(self, publish):
        due_a = self.source("A")
        due_b = self.source("B", next_run_at=timezone.now() - timedelta(minutes=1))
        self.source("Future", next_run_at=timezone.now() + timedelta(minutes=1))
        self.source("Inactive", is_active=False)

        self.assertEqual(dispatch_due_discovery_sources(), 2)
        self.assertEqual(publish.call_count, 2)
        self.assertEqual(publish.call_args_list[0].kwargs["countdown"], 0)
        self.assertEqual(publish.call_args_list[1].kwargs["countdown"], 5)
        for source in (due_a, due_b):
            source.refresh_from_db()
            self.assertIsNotNone(source.dispatch_reserved_at)
            self.assertGreater(source.next_run_at, timezone.now())

    @patch("monitor.tasks.run_discovery_source.apply_async")
    def test_dispatcher_does_not_publish_overlapping_source(self, publish):
        source = self.source()
        DiscoveryRun.objects.create(source=source, status=DiscoveryRun.Status.RUNNING)
        self.assertEqual(dispatch_due_discovery_sources(), 0)
        publish.assert_not_called()

    @override_settings(MERCADOLIBRE_DISCOVERY_QUEUE="discovery_mercadolibre")
    @patch("monitor.tasks.run_discovery_source.apply_async")
    def test_dispatches_mercado_libre_to_its_serial_queue(self, publish):
        self.source(
            "Seller",
            source_type=DiscoverySource.SourceType.MERCADO_LIBRE_SELLER,
            url="https://listado.mercadolibre.com.mx/pagina/tieronezone/",
        )

        self.assertEqual(dispatch_due_discovery_sources(), 1)

        self.assertEqual(publish.call_args.kwargs["queue"], "discovery_mercadolibre")


    @patch("monitor.tasks.send_discovery_notification.apply_async")
    @patch("monitor.tasks.collect_discovery_source")
    def test_source_task_uses_fake_collector_and_enqueues_its_own_notifications(
        self, collect, enqueue
    ):
        source = self.source()
        collect.return_value = {"items": [{"external_id": "A", "name": "A"}], "pages_found": 1}
        first_id = run_discovery_source.run(source.pk)
        self.assertEqual(DiscoveryRun.objects.get(pk=first_id).notifications_created, 0)
        enqueue.assert_not_called()

        collect.return_value = {"items": [
            {"external_id": "A", "name": "A"},
            {"external_id": "B", "name": "B"},
        ]}
        second_id = run_discovery_source.run(source.pk)
        notification = DiscoveryNotification.objects.get(event__run_id=second_id)
        enqueue.assert_called_once_with(
            args=(notification.pk,), queue="discovery_notifications", expires=900
        )

    @patch("monitor.tasks.collect_discovery_source", side_effect=RuntimeError("source down"))
    def test_source_failure_is_audited(self, _collect):
        source = self.source()
        with self.assertRaises(Exception):
            run_discovery_source.run(source.pk)
        run = source.runs.get()
        self.assertEqual(run.status, DiscoveryRun.Status.FAILED)
        self.assertIn("source down", run.error)

    @patch("monitor.tasks.send_discovery_notification.apply_async")
    @patch("monitor.tasks.collect_discovery_source")
    def test_manual_diagnostic_never_changes_baseline_or_history(self, collect, send):
        source = self.source(is_active=False)
        collect.return_value = {
            "items": [{"external_id": "DIAG", "name": "Solo diagnóstico"}],
            "pages_found": 2, "is_complete": True, "issues": [],
        }
        run_id = run_discovery_source.run(source.pk, diagnostic=True)
        run = DiscoveryRun.objects.get(pk=run_id)
        source.refresh_from_db()
        self.assertTrue(run.is_diagnostic)
        self.assertEqual((run.pages_found, run.products_found), (2, 1))
        self.assertFalse(source.baseline_established)
        self.assertIsNone(source.last_run)
        self.assertFalse(source.products.exists())
        self.assertFalse(run.events.exists())
        send.assert_not_called()

    @override_settings(DISCOVERY_RETENTION_DAYS=30, DISCOVERY_RETENTION_BATCH_SIZE=100)
    def test_cleanup_only_removes_old_finished_discovery_history(self):
        source = self.source()
        old = DiscoveryRun.objects.create(source=source, status=DiscoveryRun.Status.SUCCESS)
        DiscoveryRun.objects.filter(pk=old.pk).update(started_at=timezone.now() - timedelta(days=31))
        current = DiscoveryRun.objects.create(source=source, status=DiscoveryRun.Status.SUCCESS)
        result = cleanup_discovery_history.run()
        self.assertEqual(result["runs"], 1)
        self.assertFalse(DiscoveryRun.objects.filter(pk=old.pk).exists())
        self.assertTrue(DiscoveryRun.objects.filter(pk=current.pk).exists())
        self.assertTrue(DiscoverySource.objects.filter(pk=source.pk).exists())


@override_settings(**CHANNELS)
class DiscoveryNotificationTests(TestCase):
    def notification(self, source_type):
        source = DiscoverySource.objects.create(
            name="Private source",
            url="https://example.com/public",
            source_type=source_type,
            price_drop_percent=(
                Decimal("5") if source_type in DiscoverySource.PRICE_DROP_SOURCE_TYPES else None
            ),
        )
        process_discovery_review(source, [{"external_id": "A", "name": "A"}])
        run = process_discovery_review(source, [
            {"external_id": "A", "name": "A"},
            {"external_id": "B", "name": "New", "url": "https://example.com/b"},
        ])
        return DiscoveryNotification.objects.get(event__run=run)

    @override_settings(TELEGRAM_TOP100_CHANNEL_ID="commercial", TELEGRAM_CHAT_ID="commercial")
    @patch("monitor.discovery_notifications.send_telegram_message")
    def test_commercial_channel_is_explicitly_rejected(self, send):
        notification = self.notification(DiscoverySource.SourceType.AMAZON_TOP_100)
        with self.assertRaisesRegex(RuntimeError, "canal comercial"):
            deliver_discovery_notification(notification.pk)
        send.assert_not_called()

    @patch("monitor.discovery_notifications.send_telegram_message", return_value="123")
    def test_routes_each_type_to_its_private_channel_and_specific_bot(self, send):
        expected = {
            DiscoverySource.SourceType.AMAZON_TOP_100: "private-top100",
            DiscoverySource.SourceType.AMAZON_NEWEST: "private-newest",
            DiscoverySource.SourceType.AMAZON_TRACKERS: "private-trackers",
            DiscoverySource.SourceType.MERCADO_LIBRE_SELLER: "private-ml",
        }
        for source_type, channel in expected.items():
            with self.subTest(source_type=source_type):
                notification = self.notification(source_type)
                deliver_discovery_notification(notification.pk)
                self.assertEqual(send.call_args.args[0], channel)
                self.assertEqual(send.call_args.kwargs["bot_token"], "private-token")

    @patch("monitor.discovery_notifications.send_telegram_message", return_value="321")
    def test_sent_notification_is_idempotent(self, send):
        notification = self.notification(DiscoverySource.SourceType.AMAZON_NEWEST)
        self.assertEqual(deliver_discovery_notification(notification.pk), "321")
        self.assertEqual(deliver_discovery_notification(notification.pk), "321")
        self.assertEqual(send.call_count, 1)
        notification.refresh_from_db()
        self.assertEqual(notification.status, DiscoveryNotification.Status.SENT)
        self.assertEqual(notification.telegram_message_id, "321")

    @patch("monitor.discovery_notifications.send_telegram_message", side_effect=RuntimeError("telegram down"))
    def test_failed_delivery_is_recorded(self, _send):
        notification = self.notification(DiscoverySource.SourceType.AMAZON_TRACKERS)
        with self.assertRaises(RuntimeError):
            deliver_discovery_notification(notification.pk)
        notification.refresh_from_db()
        self.assertEqual(notification.status, DiscoveryNotification.Status.FAILED)
        self.assertIn("telegram down", notification.error)
