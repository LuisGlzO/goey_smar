from datetime import time
from decimal import Decimal
from unittest.mock import ANY, patch

from django.core import mail
from django.test import TestCase, override_settings

from monitor.email import send_monitor_failure_email
from monitor.models import Alert, MonitorRun, MonitorSettings, Product, ProductCheck
from monitor.scraper import ScrapedItem
from monitor.services import (
    alert_decision,
    determine_availability,
    process_missing_product,
    run_monitor,
    send_monitor_failure_notifications,
)
from monitor.telegram import send_monitor_failure_alert


class AlertDecisionTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(asin="B0ABC12345", name="Producto", max_price=Decimal("1000"))
        self.run = MonitorRun.objects.create()

    def make_check(self, availability=ProductCheck.Availability.AVAILABLE, price=Decimal("900")):
        return ProductCheck.objects.create(
            run=self.run,
            product=self.product,
            availability=availability,
            price=price,
        )

    def test_first_valid_availability_alerts(self):
        should_send, reason = alert_decision(self.product, self.make_check())
        self.assertTrue(should_send)
        self.assertEqual(reason, "first_availability")

    def test_price_above_target_does_not_alert(self):
        should_send, reason = alert_decision(self.product, self.make_check(price=Decimal("1100")))
        self.assertFalse(should_send)
        self.assertEqual(reason, "price_above_target")

    def test_consecutive_check_respects_cooldown(self):
        first = self.make_check()
        Alert.objects.create(product=self.product, product_check=first, status=Alert.Status.SENT, reason="first_availability")
        should_send, reason = alert_decision(self.product, self.make_check())
        self.assertFalse(should_send)
        self.assertEqual(reason, "cooldown")

    def test_missing_product_is_audited_as_unknown(self):
        process_missing_product(self.run, self.product)
        check = ProductCheck.objects.get()
        self.assertEqual(check.availability, ProductCheck.Availability.UNKNOWN)
        self.assertEqual(check.alerts.get().reason, "not_visible")

    def test_move_to_cart_with_price_wins_over_selected_seller_unavailable_message(self):
        item = ScrapedItem(
            asin=self.product.asin,
            price=Decimal("549.00"),
            move_to_cart_visible=True,
            unavailable_message_visible=True,
            product_url="https://www.amazon.com.mx/dp/B0ABC12345",
            raw_text="Este producto ya no está disponible del vendedor seleccionado. Mover al carrito",
        )
        self.assertEqual(determine_availability(item), ProductCheck.Availability.AVAILABLE)


class MonitorSettingsTests(TestCase):
    def test_empty_window_is_always_active_when_enabled(self):
        settings = MonitorSettings(enabled=True)
        self.assertTrue(settings.is_active_at(time(2, 0)))

    def test_standard_window_only_allows_inside_hours(self):
        settings = MonitorSettings(enabled=True, active_from=time(7, 0), active_until=time(23, 0))
        self.assertTrue(settings.is_active_at(time(12, 0)))
        self.assertFalse(settings.is_active_at(time(23, 30)))

    def test_overnight_window_crosses_midnight(self):
        settings = MonitorSettings(enabled=True, active_from=time(23, 0), active_until=time(7, 0))
        self.assertTrue(settings.is_active_at(time(23, 30)))
        self.assertTrue(settings.is_active_at(time(2, 0)))
        self.assertFalse(settings.is_active_at(time(12, 0)))

    @patch("monitor.services.scrape_saved_items")
    def test_disabled_monitor_skips_without_opening_amazon(self, scrape_saved_items):
        MonitorSettings.objects.create(enabled=False)
        run = run_monitor()
        self.assertEqual(run.status, MonitorRun.Status.SKIPPED)
        self.assertEqual(run.error, "monitor_disabled")
        scrape_saved_items.assert_not_called()

    @patch("monitor.services.scrape_saved_items")
    def test_running_monitor_skips_overlapping_execution(self, scrape_saved_items):
        MonitorRun.objects.create(status=MonitorRun.Status.RUNNING)

        run = run_monitor()

        self.assertEqual(run.status, MonitorRun.Status.SKIPPED)
        self.assertEqual(run.error, "previous_run_still_running")
        scrape_saved_items.assert_not_called()

    @patch("monitor.services.send_monitor_failure_notifications")
    @patch("monitor.services.scrape_saved_items", side_effect=RuntimeError("captcha requerido"))
    def test_failed_monitor_sends_failure_notification(self, scrape_saved_items, send_failure_notifications):
        with self.assertRaisesMessage(RuntimeError, "captcha requerido"):
            run_monitor()

        run = MonitorRun.objects.get()
        self.assertEqual(run.status, MonitorRun.Status.FAILED)
        self.assertEqual(run.error, "captcha requerido")
        self.assertIsNotNone(run.finished_at)
        send_failure_notifications.assert_called_once_with(run, ANY)

    @patch("monitor.services.send_monitor_failure_email", side_effect=RuntimeError("smtp caido"))
    @patch("monitor.services.send_monitor_failure_alert", side_effect=RuntimeError("telegram caido"))
    def test_failure_notifier_errors_are_logged(self, send_failure_alert, send_failure_email):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="sesion invalida")

        with self.assertLogs("monitor.services", level="ERROR"):
            send_monitor_failure_notifications(run, RuntimeError("sesion invalida"))

        send_failure_email.assert_called_once()
        send_failure_alert.assert_called_once()

    @patch("monitor.services.send_monitor_failure_email", return_value=1)
    @patch("monitor.services.send_monitor_failure_alert")
    def test_failure_notifier_stops_after_successful_email(self, send_failure_alert, send_failure_email):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        send_monitor_failure_notifications(run, RuntimeError("captcha requerido"))

        send_failure_email.assert_called_once()
        send_failure_alert.assert_not_called()

    @patch("monitor.services.send_monitor_failure_email", return_value=0)
    @patch("monitor.services.send_monitor_failure_alert")
    def test_failure_notifier_uses_telegram_when_email_has_no_recipients(self, send_failure_alert, send_failure_email):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        send_monitor_failure_notifications(run, RuntimeError("captcha requerido"))

        send_failure_email.assert_called_once()
        send_failure_alert.assert_called_once()

    @patch("monitor.services.send_monitor_failure_email", side_effect=RuntimeError("smtp caido"))
    @patch("monitor.services.send_monitor_failure_alert")
    def test_failure_notifier_uses_telegram_when_email_fails(self, send_failure_alert, send_failure_email):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        with self.assertLogs("monitor.services", level="ERROR"):
            send_monitor_failure_notifications(run, RuntimeError("captcha requerido"))

        send_failure_email.assert_called_once()
        send_failure_alert.assert_called_once()


class MonitorFailureEmailTests(TestCase):
    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="monitor@example.com",
        MONITOR_FAILURE_EMAIL_RECIPIENTS=["ops@example.com"],
        MONITOR_FAILURE_EMAIL_SUBJECT_PREFIX="[Pruebas]",
    )
    def test_send_monitor_failure_email_uses_configured_recipients(self):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        sent = send_monitor_failure_email(run, RuntimeError("captcha requerido"))

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ops@example.com"])
        self.assertIn("[Pruebas] Scraper fallido", mail.outbox[0].subject)
        self.assertIn("captcha requerido", mail.outbox[0].body)

    @override_settings(MONITOR_FAILURE_EMAIL_RECIPIENTS=[])
    def test_send_monitor_failure_email_is_noop_without_recipients(self):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        sent = send_monitor_failure_email(run, RuntimeError("captcha requerido"))

        self.assertEqual(sent, 0)


class MonitorFailureTelegramTests(TestCase):
    @override_settings(TELEGRAM_BOT_TOKEN="token", TELEGRAM_ERROR_CHAT_ID="-100123")
    @patch("monitor.telegram.requests.post")
    def test_send_monitor_failure_alert_uses_error_channel(self, post):
        post.return_value.json.return_value = {"result": {"message_id": 77}}
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        message_id = send_monitor_failure_alert(run, RuntimeError("captcha requerido"))

        self.assertEqual(message_id, "77")
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "-100123")
        self.assertIn("Scraper fallido", payload["text"])
        self.assertIn("captcha requerido", payload["text"])
        self.assertTrue(payload["disable_web_page_preview"])

    @override_settings(TELEGRAM_BOT_TOKEN="token", TELEGRAM_ERROR_CHAT_ID="")
    def test_send_monitor_failure_alert_requires_error_channel(self):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        with self.assertRaisesMessage(RuntimeError, "TELEGRAM_ERROR_CHAT_ID"):
            send_monitor_failure_alert(run, RuntimeError("captcha requerido"))
