from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from monitor.amazon_creators import CreatorProductContent
from monitor.models import Alert, MonitorRun, MonitorSettings, ObservationSource, Product, ProductCheck
from monitor.services import request_product_alert, run_creators_api_monitor, start_monitor_run


class CentralAlertServiceTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            asin="B0ABC12345", name="Producto", max_price=Decimal("1000"), cooldown_minutes=30
        )
        self.settings = MonitorSettings.objects.create(anti_false_restock_cooldown_minutes=5)

    def check(self, source=ObservationSource.SCRAPER, price=Decimal("900")):
        return ProductCheck.objects.create(
            product=self.product, source=source, availability=ProductCheck.Availability.AVAILABLE,
            price=price, move_to_cart_visible=True,
        )

    @patch("monitor.services.send_product_alert", return_value="101")
    def test_alert_from_one_source_blocks_all_during_false_restock_window(self, send):
        first = request_product_alert(
            self.product, self.check(), ObservationSource.SCRAPER, monitor_settings=self.settings
        )
        second = request_product_alert(
            self.product, self.check(ObservationSource.CREATORS_API), ObservationSource.CREATORS_API,
            monitor_settings=self.settings,
        )
        self.assertEqual(first.status, Alert.Status.SENT)
        self.assertEqual(second.reason, "anti_false_restock_cooldown")
        self.assertEqual(send.call_count, 1)

    @patch("monitor.services.send_product_alert", return_value="102")
    def test_manual_request_obeys_normal_cooldown(self, send):
        old_check = self.check()
        sent = Alert.objects.create(
            product=self.product, product_check=old_check, source=ObservationSource.SCRAPER,
            status=Alert.Status.SENT, reason="first_availability",
        )
        Alert.objects.filter(pk=sent.pk).update(created_at=timezone.now() - timedelta(minutes=10))
        manual = self.check(ObservationSource.MANUAL, price=None)
        result = request_product_alert(
            self.product, manual, ObservationSource.MANUAL, monitor_settings=self.settings
        )
        self.assertEqual(result.reason, "cooldown")
        send.assert_not_called()

    @override_settings(ALERT_RESERVATION_SECONDS=60)
    @patch("monitor.services.send_product_alert", return_value="103")
    def test_live_reservation_prevents_duplicate(self, send):
        check = self.check()
        Alert.objects.create(
            product=self.product, product_check=check, source=ObservationSource.SCRAPER,
            status=Alert.Status.PROCESSING, reason="first_availability",
            reservation_expires_at=timezone.now() + timedelta(seconds=30),
        )
        result = request_product_alert(
            self.product, self.check(), ObservationSource.SCRAPER, monitor_settings=self.settings
        )
        self.assertEqual(result.reason, "alert_in_progress")
        send.assert_not_called()

    def test_different_worker_keys_can_run_together(self):
        scraper, _ = start_monitor_run(ObservationSource.SCRAPER, "scraper:default")
        api, _ = start_monitor_run(ObservationSource.CREATORS_API, "creators_api:default")
        duplicate, _ = start_monitor_run(ObservationSource.SCRAPER, "scraper:default")
        self.assertEqual(scraper.status, MonitorRun.Status.RUNNING)
        self.assertEqual(api.status, MonitorRun.Status.RUNNING)
        self.assertEqual(duplicate.status, MonitorRun.Status.SKIPPED)

    def test_two_scraper_accounts_can_run_together_but_each_blocks_itself(self):
        account_a, _ = start_monitor_run(ObservationSource.SCRAPER, "scraper:amazon_a")
        account_b, _ = start_monitor_run(ObservationSource.SCRAPER, "scraper:amazon_b")
        duplicate_a, _ = start_monitor_run(ObservationSource.SCRAPER, "scraper:amazon_a")

        self.assertEqual(account_a.status, MonitorRun.Status.RUNNING)
        self.assertEqual(account_b.status, MonitorRun.Status.RUNNING)
        self.assertEqual(duplicate_a.status, MonitorRun.Status.SKIPPED)


class CreatorsMonitorTests(TestCase):
    @override_settings(AMAZON_CREATORS_API_BATCH_SIZE=10, AMAZON_CREATORS_API_BATCH_DELAY_SECONDS=0)
    @patch("monitor.services.send_product_alert", return_value="201")
    @patch("monitor.services.creators_api_is_configured", return_value=True)
    @patch("monitor.services.get_products_content")
    def test_api_monitor_uses_primary_offer_data(self, get_content, configured, send):
        product = Product.objects.create(asin="B0ABC12345", name="Producto", max_price=Decimal("1000"))
        get_content.return_value = {
            product.asin: CreatorProductContent(
                "Titulo", "https://m.media-amazon.com/product.jpg",
                "https://amazon/dp/x", True, Decimal("900")
            )
        }
        run = run_creators_api_monitor()
        self.assertEqual(run.status, MonitorRun.Status.SUCCESS)
        check = ProductCheck.objects.get(product=product)
        self.assertEqual(check.source, ObservationSource.CREATORS_API)
        self.assertEqual(check.availability, ProductCheck.Availability.AVAILABLE)
        self.assertEqual(check.alerts.get().status, Alert.Status.SENT)
        product.refresh_from_db()
        self.assertEqual(product.image_url, "https://m.media-amazon.com/product.jpg")
        self.assertIsNotNone(product.image_refreshed_at)
        send.assert_called_once()


class ManualAlertPanelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("cliente", password="secret")
        self.user.user_permissions.add(Permission.objects.get(codename="send_manual_alert"))
        self.active = Product.objects.create(asin="B0ABC12345", name="Activo", max_price=Decimal("1000"))
        Product.objects.create(asin="B0XYZ12345", name="Inactivo", max_price=Decimal("1000"), is_active=False)

    def test_panel_requires_login_and_lists_only_active_products(self):
        response = self.client.get(reverse("manual_alerts"))
        self.assertEqual(response.status_code, 302)
        self.client.login(username="cliente", password="secret")
        response = self.client.get(reverse("manual_alerts"))
        self.assertContains(response, "Activo")
        self.assertNotContains(response, "Inactivo")

    @patch("monitor.services.send_product_alert", return_value="301")
    def test_manual_post_sends_and_audits_user(self, send):
        self.client.login(username="cliente", password="secret")
        response = self.client.post(reverse("send_manual_alert", args=[self.active.pk]), follow=True)
        self.assertContains(response, "enviada correctamente")
        alert = Alert.objects.get(status=Alert.Status.SENT)
        self.assertEqual(alert.source, ObservationSource.MANUAL)
        self.assertEqual(alert.requested_by, self.user)
        send.assert_called_once()
