from decimal import Decimal

from django.test import TestCase

from monitor.models import Alert, MonitorRun, Product, ProductCheck
from monitor.services import alert_decision, process_missing_product


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
