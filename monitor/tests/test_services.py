from datetime import time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from monitor.models import Alert, MonitorRun, MonitorSettings, Product, ProductCheck
from monitor.scraper import ScrapedItem
from monitor.services import alert_decision, determine_availability, process_missing_product, run_monitor


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
