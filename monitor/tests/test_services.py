from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import ANY, patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from monitor.email import send_monitor_failure_email
from monitor.models import Alert, MonitorRun, MonitorSettings, ObservationSource, Product, ProductCheck
from monitor.scraper import ScrapedItem
from monitor.services import (
    alert_decision,
    consecutive_infrastructure_failures,
    determine_availability,
    effective_cooldown_minutes,
    process_missing_product,
    recover_stale_monitor_runs,
    request_worker_restart_after_infrastructure_failures,
    run_monitor,
    send_monitor_failure_notifications,
)
from monitor.telegram import send_monitor_failure_alert


class AlertDecisionTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(asin="B0ABC12345", name="Producto", max_price=Decimal("1000"))
        self.run = MonitorRun.objects.create()

    def make_check(
        self,
        availability=ProductCheck.Availability.AVAILABLE,
        price=Decimal("900"),
        move_to_cart_visible=True,
    ):
        return ProductCheck.objects.create(
            run=self.run,
            product=self.product,
            availability=availability,
            price=price,
            move_to_cart_visible=move_to_cart_visible,
        )

    def test_first_valid_availability_alerts(self):
        should_send, reason = alert_decision(self.product, self.make_check())
        self.assertTrue(should_send)
        self.assertEqual(reason, "first_availability")

    def test_price_above_target_does_not_alert(self):
        should_send, reason = alert_decision(self.product, self.make_check(price=Decimal("1100")))
        self.assertFalse(should_send)
        self.assertEqual(reason, "price_above_target")

    def test_price_below_target_without_move_to_cart_does_not_alert(self):
        should_send, reason = alert_decision(
            self.product,
            self.make_check(price=Decimal("489.00"), move_to_cart_visible=False),
        )
        self.assertFalse(should_send)
        self.assertEqual(reason, "move_to_cart_missing")

    def test_consecutive_check_respects_cooldown(self):
        first = self.make_check()
        Alert.objects.create(product=self.product, product_check=first, status=Alert.Status.SENT, reason="first_availability")
        should_send, reason = alert_decision(self.product, self.make_check())
        self.assertFalse(should_send)
        self.assertEqual(reason, "cooldown")

    def test_creators_api_never_detects_restock(self):
        first = self.make_check()
        alert = Alert.objects.create(
            product=self.product, product_check=first, status=Alert.Status.SENT,
            reason="first_availability",
        )
        Alert.objects.filter(pk=alert.pk).update(
            created_at=timezone.now() - timedelta(minutes=61)
        )
        ProductCheck.objects.create(
            run=self.run,
            product=self.product,
            source=ObservationSource.CREATORS_API,
            availability=ProductCheck.Availability.UNAVAILABLE,
        )
        current = ProductCheck.objects.create(
            run=self.run,
            product=self.product,
            source=ObservationSource.CREATORS_API,
            availability=ProductCheck.Availability.AVAILABLE,
            price=Decimal("900"),
            move_to_cart_visible=True,
        )

        should_send, reason = alert_decision(self.product, current)

        self.assertTrue(should_send)
        self.assertEqual(reason, "cooldown_elapsed")

    def test_scraper_restock_ignores_newer_unknown_creators_check(self):
        first = self.make_check()
        Alert.objects.create(
            product=self.product, product_check=first, status=Alert.Status.SENT,
            reason="first_availability",
        )
        ProductCheck.objects.create(
            run=self.run,
            product=self.product,
            source=ObservationSource.CREATORS_API,
            availability=ProductCheck.Availability.UNKNOWN,
        )

        should_send, reason = alert_decision(self.product, self.make_check())

        self.assertFalse(should_send)
        self.assertEqual(reason, "cooldown")

    def test_scraper_still_detects_restock_from_its_own_checks(self):
        first = self.make_check()
        Alert.objects.create(
            product=self.product, product_check=first, status=Alert.Status.SENT,
            reason="first_availability",
        )
        self.make_check(availability=ProductCheck.Availability.UNAVAILABLE)

        should_send, reason = alert_decision(self.product, self.make_check())

        self.assertTrue(should_send)
        self.assertEqual(reason, "restock")

    def test_effective_cooldown_follows_stepped_sequence_and_cap(self):
        self.product.cooldown_minutes = 20
        self.product.save(update_fields=("cooldown_minutes",))
        check = self.make_check()
        Alert.objects.create(
            product=self.product, product_check=check, status=Alert.Status.SENT,
            reason="first_availability",
        )
        self.assertEqual(effective_cooldown_minutes(self.product), 20)

        for expected in (40, 80, 160, 320, 360, 360):
            Alert.objects.create(
                product=self.product, product_check=check, status=Alert.Status.SENT,
                reason="cooldown_elapsed",
            )
            self.assertEqual(effective_cooldown_minutes(self.product), expected)

    def test_alert_decision_waits_for_effective_cooldown(self):
        self.product.cooldown_minutes = 20
        self.product.max_alerts_per_day = 10
        self.product.save(update_fields=("cooldown_minutes", "max_alerts_per_day"))
        check = self.make_check()
        alert = Alert.objects.create(
            product=self.product, product_check=check, status=Alert.Status.SENT,
            reason="cooldown_elapsed",
        )
        Alert.objects.filter(pk=alert.pk).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )

        should_send, reason = alert_decision(self.product, self.make_check())
        self.assertFalse(should_send)
        self.assertEqual(reason, "cooldown")

        Alert.objects.filter(pk=alert.pk).update(
            created_at=timezone.now() - timedelta(minutes=41)
        )
        should_send, reason = alert_decision(self.product, self.make_check())
        self.assertTrue(should_send)
        self.assertEqual(reason, "cooldown_elapsed")

    def test_effective_cooldown_resets_after_automatic_reset_reasons(self):
        self.product.cooldown_minutes = 20
        self.product.save(update_fields=("cooldown_minutes",))
        check = self.make_check()
        for reset_reason in ("first_availability", "restock", "significant_price_drop"):
            Alert.objects.all().delete()
            Alert.objects.create(
                product=self.product, product_check=check, status=Alert.Status.SENT,
                reason="cooldown_elapsed",
            )
            Alert.objects.create(
                product=self.product, product_check=check, status=Alert.Status.SENT,
                reason=reset_reason,
            )
            self.assertEqual(effective_cooldown_minutes(self.product), 20)

    def test_manual_failed_and_skipped_alerts_do_not_change_stepped_level(self):
        self.product.cooldown_minutes = 20
        self.product.save(update_fields=("cooldown_minutes",))
        check = self.make_check()
        Alert.objects.create(
            product=self.product, product_check=check, status=Alert.Status.SENT,
            reason="cooldown_elapsed",
        )
        Alert.objects.create(
            product=self.product, product_check=check, source=ObservationSource.MANUAL,
            status=Alert.Status.SENT, reason="manual_request",
        )
        Alert.objects.create(
            product=self.product, product_check=check, status=Alert.Status.FAILED,
            reason="cooldown_elapsed",
        )
        Alert.objects.create(
            product=self.product, product_check=check, status=Alert.Status.SKIPPED,
            reason="first_availability",
        )
        self.assertEqual(effective_cooldown_minutes(self.product), 40)

    def test_effective_cooldown_handles_zero_large_base_and_no_history(self):
        self.product.cooldown_minutes = 0
        self.product.save(update_fields=("cooldown_minutes",))
        self.assertEqual(effective_cooldown_minutes(self.product), 0)
        check = self.make_check()
        Alert.objects.create(
            product=self.product, product_check=check, status=Alert.Status.SENT,
            reason="cooldown_elapsed",
        )
        self.assertEqual(effective_cooldown_minutes(self.product), 0)

        self.product.cooldown_minutes = 480
        self.product.save(update_fields=("cooldown_minutes",))
        self.assertEqual(effective_cooldown_minutes(self.product), 480)

    def test_anti_false_restock_cooldown_blocks_recent_same_product_alert(self):
        monitor_settings = MonitorSettings(anti_false_restock_cooldown_minutes=5)
        first = self.make_check()
        alert = Alert.objects.create(
            product=self.product,
            product_check=first,
            status=Alert.Status.SENT,
            reason="first_availability",
        )
        Alert.objects.filter(pk=alert.pk).update(created_at=timezone.now() - timedelta(minutes=2))

        should_send, reason = alert_decision(self.product, self.make_check(), monitor_settings=monitor_settings)

        self.assertFalse(should_send)
        self.assertEqual(reason, "anti_false_restock_cooldown")

    def test_anti_false_restock_cooldown_does_not_block_other_products(self):
        monitor_settings = MonitorSettings(anti_false_restock_cooldown_minutes=5)
        other_product = Product.objects.create(asin="B0XYZ12345", name="Otro", max_price=Decimal("1000"))
        first = self.make_check()
        Alert.objects.create(
            product=self.product,
            product_check=first,
            status=Alert.Status.SENT,
            reason="first_availability",
        )
        other_check = ProductCheck.objects.create(
            run=self.run,
            product=other_product,
            availability=ProductCheck.Availability.AVAILABLE,
            price=Decimal("900"),
            move_to_cart_visible=True,
        )

        should_send, reason = alert_decision(other_product, other_check, monitor_settings=monitor_settings)

        self.assertTrue(should_send)
        self.assertEqual(reason, "first_availability")

    def test_anti_false_restock_cooldown_zero_keeps_existing_product_cooldown(self):
        monitor_settings = MonitorSettings(anti_false_restock_cooldown_minutes=0)
        first = self.make_check()
        Alert.objects.create(
            product=self.product,
            product_check=first,
            status=Alert.Status.SENT,
            reason="first_availability",
        )

        should_send, reason = alert_decision(self.product, self.make_check(), monitor_settings=monitor_settings)

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

    def test_price_without_move_to_cart_is_not_available(self):
        item = ScrapedItem(
            asin=self.product.asin,
            price=Decimal("489.00"),
            move_to_cart_visible=False,
            unavailable_message_visible=True,
            product_url="https://www.amazon.com.mx/dp/B0ABC12345",
            raw_text="Este producto ya no esta disponible del vendedor seleccionado. Ver productos similares $489.00",
        )
        self.assertEqual(determine_availability(item), ProductCheck.Availability.UNAVAILABLE)


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
        run = run_monitor("amazon_a")
        self.assertEqual(run.status, MonitorRun.Status.SKIPPED)
        self.assertEqual(run.error, "monitor_disabled")
        scrape_saved_items.assert_not_called()

    @patch("monitor.services.scrape_saved_items")
    def test_running_monitor_skips_overlapping_execution(self, scrape_saved_items):
        MonitorRun.objects.create(status=MonitorRun.Status.RUNNING, worker_key="scraper:amazon_a")

        run = run_monitor("amazon_a")

        self.assertEqual(run.status, MonitorRun.Status.SKIPPED)
        self.assertEqual(run.error, "previous_run_still_running")
        scrape_saved_items.assert_not_called()

    @override_settings(MONITOR_RUNNING_STALE_MINUTES=10)
    @patch("monitor.services.scrape_saved_items", return_value=[])
    def test_stale_running_monitor_is_recovered_before_new_execution(self, scrape_saved_items):
        stale = MonitorRun.objects.create(status=MonitorRun.Status.RUNNING, worker_key="scraper:amazon_a")
        MonitorRun.objects.filter(pk=stale.pk).update(started_at=timezone.now() - timedelta(minutes=30))

        run = run_monitor("amazon_a")

        stale.refresh_from_db()
        self.assertEqual(stale.status, MonitorRun.Status.FAILED)
        self.assertIn("stale_run_recovered", stale.error)
        self.assertIsNotNone(stale.finished_at)
        self.assertEqual(run.status, MonitorRun.Status.SUCCESS)
        scrape_saved_items.assert_called_once()
        self.assertIn("timing", scrape_saved_items.call_args.kwargs)

    @override_settings(MONITOR_RUNNING_STALE_MINUTES=10)
    def test_recover_stale_monitor_runs_returns_recovered_count(self):
        stale = MonitorRun.objects.create(status=MonitorRun.Status.RUNNING)
        recent = MonitorRun.objects.create(status=MonitorRun.Status.RUNNING)
        MonitorRun.objects.filter(pk=stale.pk).update(started_at=timezone.now() - timedelta(minutes=30))

        recovered = recover_stale_monitor_runs()

        stale.refresh_from_db()
        recent.refresh_from_db()
        self.assertEqual(recovered, 1)
        self.assertEqual(stale.status, MonitorRun.Status.FAILED)
        self.assertEqual(recent.status, MonitorRun.Status.RUNNING)

    @patch("monitor.services.send_monitor_failure_notifications")
    @patch("monitor.services.scrape_saved_items", side_effect=RuntimeError("captcha requerido"))
    def test_failed_monitor_sends_failure_notification(self, scrape_saved_items, send_failure_notifications):
        with self.assertRaisesMessage(RuntimeError, "captcha requerido"):
            run_monitor("amazon_a")

        run = MonitorRun.objects.get()
        self.assertEqual(run.status, MonitorRun.Status.FAILED)
        self.assertEqual(run.error, "captcha requerido")
        self.assertIsNotNone(run.finished_at)
        send_failure_notifications.assert_called_once_with(run, ANY)

    @patch("monitor.services.scrape_saved_items", return_value=[])
    def test_successful_monitor_stores_performance_breakdown(self, scrape_saved_items):
        run = run_monitor("amazon_a")

        self.assertEqual(run.status, MonitorRun.Status.SUCCESS)
        self.assertIn("total_seconds", run.performance)
        self.assertIn("stages", run.performance)
        self.assertTrue(any(stage["name"] == "scrape_saved_items" for stage in run.performance["stages"]))

    @patch("monitor.services.scraper_profile_dir", return_value="/profiles/amazon_a")
    @patch("monitor.services.scrape_saved_items", return_value=[])
    def test_monitor_only_marks_its_assigned_partition_as_missing(self, scrape_saved_items, profile_dir):
        assigned = Product.objects.create(asin="B0PARTA001", name="Cuenta A", max_price=100)
        other = Product.objects.create(
            asin="B0PARTB001", name="Cuenta B", max_price=100, scraper_account_id="amazon_b"
        )

        run = run_monitor("amazon_a")

        self.assertTrue(ProductCheck.objects.filter(run=run, product=assigned).exists())
        self.assertFalse(ProductCheck.objects.filter(run=run, product=other).exists())
        scrape_saved_items.assert_called_once_with(
            account_key="amazon_a", profile_dir="/profiles/amazon_a", timing=ANY
        )

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
    def test_failure_notifier_stops_after_successful_telegram(self, send_failure_alert, send_failure_email):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        send_monitor_failure_notifications(run, RuntimeError("captcha requerido"))

        send_failure_alert.assert_called_once()
        send_failure_email.assert_not_called()

    @patch("monitor.services.send_monitor_failure_email", return_value=0)
    @patch("monitor.services.send_monitor_failure_alert", side_effect=RuntimeError("telegram caido"))
    def test_failure_notifier_uses_email_when_telegram_fails(self, send_failure_alert, send_failure_email):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        with self.assertLogs("monitor.services", level="ERROR"):
            send_monitor_failure_notifications(run, RuntimeError("captcha requerido"))

        send_failure_alert.assert_called_once()
        send_failure_email.assert_called_once()

    @patch("monitor.services.send_monitor_failure_alert")
    @patch("monitor.services.send_monitor_failure_email")
    def test_failure_notifier_respects_failure_cooldown(self, send_failure_email, send_failure_alert):
        previous = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")
        MonitorRun.objects.filter(pk=previous.pk).update(started_at=timezone.now() - timedelta(minutes=30))
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        with self.assertLogs("monitor.services", level="INFO"):
            send_monitor_failure_notifications(run, RuntimeError("captcha requerido"))

        send_failure_alert.assert_not_called()
        send_failure_email.assert_not_called()

    @patch("monitor.services.send_monitor_failure_email", return_value=1)
    @patch("monitor.services.send_monitor_failure_alert", side_effect=RuntimeError("telegram caido"))
    def test_failure_notifier_cooldown_is_independent_per_worker(self, send_failure_alert, send_failure_email):
        MonitorRun.objects.create(
            worker_key="scraper:amazon_a", status=MonitorRun.Status.FAILED, error="captcha"
        )
        run = MonitorRun.objects.create(
            worker_key="scraper:amazon_b", status=MonitorRun.Status.FAILED, error="captcha"
        )

        send_monitor_failure_notifications(run, RuntimeError("captcha"))

        send_failure_alert.assert_called_once()
        send_failure_email.assert_called_once()

    def test_consecutive_infrastructure_failures_counts_only_latest_infra_errors(self):
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="Page.goto: Timeout 45000ms exceeded")
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="pthread_create: Resource temporarily unavailable")
        MonitorRun.objects.create(status=MonitorRun.Status.SUCCESS)

        self.assertEqual(consecutive_infrastructure_failures(3, "scraper:default"), 0)

        MonitorRun.objects.all().delete()
        MonitorRun.objects.create(status=MonitorRun.Status.SUCCESS)
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="stale_run_recovered: exceeded 10 minutes")
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="pthread_create: Resource temporarily unavailable")

        self.assertEqual(consecutive_infrastructure_failures(3, "scraper:default"), 2)

    def test_creators_runs_do_not_interrupt_scraper_failure_streak(self):
        MonitorRun.objects.create(
            source=ObservationSource.SCRAPER,
            worker_key="scraper:default",
            status=MonitorRun.Status.FAILED,
            error="Page.goto: Timeout 45000ms exceeded",
        )
        MonitorRun.objects.create(
            source=ObservationSource.CREATORS_API,
            worker_key="creators_api:default",
            status=MonitorRun.Status.SUCCESS,
        )
        MonitorRun.objects.create(
            source=ObservationSource.SCRAPER,
            worker_key="scraper:default",
            status=MonitorRun.Status.FAILED,
            error="pthread_create: Resource temporarily unavailable",
        )

        self.assertEqual(consecutive_infrastructure_failures(2, "scraper:default"), 2)

    @override_settings(
        MONITOR_INFRASTRUCTURE_FAILURE_RESTART_THRESHOLD=2,
        MONITOR_AUTO_RESTART_WORKER_ON_INFRA_FAILURE=True,
    )
    @patch("monitor.services.os._exit")
    @patch("monitor.services.os.kill")
    @patch("monitor.services.os.getppid", return_value=123)
    @patch.dict("monitor.services.os.environ", {"GOEY_CELERY_WORKER_PROCESS": "1"})
    def test_infrastructure_failures_request_worker_restart_inside_celery(self, getppid, kill, exit_process):
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="Page.goto: Timeout 45000ms exceeded")
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="stale_run_recovered: exceeded 10 minutes")

        with self.assertLogs("monitor.services", level="ERROR"):
            request_worker_restart_after_infrastructure_failures("scraper:default")

        kill.assert_called_once()
        exit_process.assert_called_once()

    @override_settings(
        MONITOR_INFRASTRUCTURE_FAILURE_RESTART_THRESHOLD=2,
        MONITOR_AUTO_RESTART_WORKER_ON_INFRA_FAILURE=True,
    )
    @patch("monitor.services.os._exit")
    @patch("monitor.services.os.kill")
    @patch("monitor.services.sys.argv", ["manage.py", "monitor_saved_items"])
    def test_infrastructure_failures_do_not_restart_manual_command(self, kill, exit_process):
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="Page.goto: Timeout 45000ms exceeded")
        MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="pthread_create: Resource temporarily unavailable")

        with self.assertLogs("monitor.services", level="ERROR"):
            request_worker_restart_after_infrastructure_failures("scraper:default")

        kill.assert_not_called()
        exit_process.assert_not_called()


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
    @override_settings(
        TELEGRAM_BOT_TOKEN="product-token",
        TELEGRAM_ERROR_BOT_TOKEN="error-token",
        TELEGRAM_ERROR_CHAT_ID="-100123",
    )
    @patch("monitor.telegram.requests.post")
    def test_send_monitor_failure_alert_uses_error_bot_and_channel(self, post):
        post.return_value.json.return_value = {"result": {"message_id": 77}}
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        message_id = send_monitor_failure_alert(run, RuntimeError("captcha requerido"))

        self.assertEqual(message_id, "77")
        post.assert_called_once()
        self.assertIn("boterror-token", post.call_args.args[0])
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "-100123")
        self.assertIn("Scraper fallido", payload["text"])
        self.assertIn("captcha requerido", payload["text"])
        self.assertTrue(payload["disable_web_page_preview"])

    @override_settings(TELEGRAM_ERROR_BOT_TOKEN="error-token", TELEGRAM_ERROR_CHAT_ID="")
    def test_send_monitor_failure_alert_requires_error_channel(self):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        with self.assertRaisesMessage(RuntimeError, "TELEGRAM_ERROR_CHAT_ID"):
            send_monitor_failure_alert(run, RuntimeError("captcha requerido"))

    @override_settings(TELEGRAM_ERROR_BOT_TOKEN="", TELEGRAM_ERROR_CHAT_ID="-100123")
    def test_send_monitor_failure_alert_requires_error_bot_token(self):
        run = MonitorRun.objects.create(status=MonitorRun.Status.FAILED, error="captcha requerido")

        with self.assertRaisesMessage(RuntimeError, "TELEGRAM_ERROR_BOT_TOKEN"):
            send_monitor_failure_alert(run, RuntimeError("captcha requerido"))
