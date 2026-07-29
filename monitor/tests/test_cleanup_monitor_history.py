from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from monitor.models import (
    Alert,
    CartSnapshotItem,
    MonitorRun,
    Product,
    ProductCheck,
)
from monitor.services import effective_cooldown_minutes


class CleanupMonitorHistoryTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            asin="B0CLEAN001",
            name="Producto",
            max_price=Decimal("1000"),
            cooldown_minutes=20,
        )
        self.old_time = timezone.now() - timedelta(days=45)

    def old_run(self):
        run = MonitorRun.objects.create(status=MonitorRun.Status.SUCCESS)
        MonitorRun.objects.filter(pk=run.pk).update(
            started_at=self.old_time,
            finished_at=self.old_time,
        )
        return run

    def old_check(self, run):
        check = ProductCheck.objects.create(
            run=run,
            product=self.product,
            availability=ProductCheck.Availability.AVAILABLE,
            price=Decimal("900"),
            move_to_cart_visible=True,
        )
        ProductCheck.objects.filter(pk=check.pk).update(checked_at=self.old_time)
        return check

    def old_alert(self, check, status, reason):
        alert = Alert.objects.create(
            product=self.product,
            product_check=check,
            status=status,
            reason=reason,
        )
        Alert.objects.filter(pk=alert.pk).update(created_at=self.old_time)
        return alert

    def test_cleanup_preserves_sent_and_failed_alerts_and_effective_cooldown(self):
        sent_run = self.old_run()
        sent_check = self.old_check(sent_run)
        sent = self.old_alert(sent_check, Alert.Status.SENT, "cooldown_elapsed")
        failed_run = self.old_run()
        failed_check = self.old_check(failed_run)
        failed = self.old_alert(failed_check, Alert.Status.FAILED, "telegram_error")
        expected_cooldown = effective_cooldown_minutes(self.product)

        call_command("cleanup_monitor_history", "--days", "30", "--batch-size", "2")

        self.assertTrue(Alert.objects.filter(pk=sent.pk).exists())
        self.assertTrue(Alert.objects.filter(pk=failed.pk).exists())
        self.assertEqual(
            ProductCheck.objects.filter(pk__in=(sent_check.pk, failed_check.pk)).count(),
            2,
        )
        self.assertEqual(
            MonitorRun.objects.filter(pk__in=(sent_run.pk, failed_run.pk)).count(),
            2,
        )
        self.assertEqual(effective_cooldown_minutes(self.product), expected_cooldown)

    def test_cleanup_removes_old_skipped_checks_snapshots_and_empty_runs(self):
        skipped_run = self.old_run()
        skipped_check = self.old_check(skipped_run)
        skipped = self.old_alert(skipped_check, Alert.Status.SKIPPED, "cooldown")
        snapshot_run = self.old_run()
        snapshot = CartSnapshotItem.objects.create(
            run=snapshot_run,
            scraper_account_id="amazon_a",
            asin=self.product.asin,
            source="saved",
        )

        call_command("cleanup_monitor_history", "--days", "30", "--batch-size", "1")

        self.assertFalse(Alert.objects.filter(pk=skipped.pk).exists())
        self.assertFalse(ProductCheck.objects.filter(pk=skipped_check.pk).exists())
        self.assertFalse(CartSnapshotItem.objects.filter(pk=snapshot.pk).exists())
        self.assertFalse(MonitorRun.objects.filter(pk__in=(skipped_run.pk, snapshot_run.pk)).exists())

    def test_cleanup_expires_stale_processing_reservations(self):
        run = self.old_run()
        check = self.old_check(run)
        alert = self.old_alert(check, Alert.Status.PROCESSING, "first_availability")
        Alert.objects.filter(pk=alert.pk).update(
            reservation_expires_at=timezone.now() - timedelta(minutes=5)
        )

        call_command("cleanup_monitor_history", "--days", "30")

        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.Status.FAILED)
        self.assertEqual(alert.reason, "reservation_expired")
        self.assertIsNone(alert.reservation_expires_at)

    def test_dry_run_reports_without_mutating(self):
        run = self.old_run()
        check = self.old_check(run)
        skipped = self.old_alert(check, Alert.Status.SKIPPED, "cooldown")
        output = StringIO()

        call_command(
            "cleanup_monitor_history",
            "--days",
            "30",
            "--batch-size",
            "10",
            "--dry-run",
            stdout=output,
        )

        self.assertTrue(Alert.objects.filter(pk=skipped.pk).exists())
        self.assertTrue(ProductCheck.objects.filter(pk=check.pk).exists())
        self.assertTrue(MonitorRun.objects.filter(pk=run.pk).exists())
        self.assertIn("dry_run=true", output.getvalue())
        self.assertIn("skipped_alerts_to_delete=1", output.getvalue())
