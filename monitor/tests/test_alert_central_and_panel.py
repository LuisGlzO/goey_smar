from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from monitor.amazon_creators import CreatorProductContent
from monitor.models import Alert, MonitorRun, MonitorSettings, ObservationSource, Product, ProductCheck
from monitor.performance import MonitorPerformance
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
    def test_manual_request_bypasses_normal_cooldown(self, send):
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
        self.assertEqual(result.status, Alert.Status.SENT)
        self.assertEqual(result.reason, "manual_request")
        send.assert_called_once()

    @patch("monitor.services.send_product_alert", return_value="104")
    def test_manual_request_bypasses_effective_cooldown_without_resetting_level(self, send):
        self.product.cooldown_minutes = 20
        self.product.save(update_fields=("cooldown_minutes",))
        old_check = self.check()
        elapsed = Alert.objects.create(
            product=self.product, product_check=old_check, source=ObservationSource.SCRAPER,
            status=Alert.Status.SENT, reason="cooldown_elapsed",
        )
        Alert.objects.filter(pk=elapsed.pk).update(created_at=timezone.now() - timedelta(minutes=30))

        first_manual = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )
        self.assertEqual(first_manual.status, Alert.Status.SENT)
        Alert.objects.filter(pk=first_manual.pk).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

        Alert.objects.filter(pk=elapsed.pk).update(created_at=timezone.now() - timedelta(minutes=41))
        sent = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )
        self.assertEqual(sent.status, Alert.Status.SENT)

        Alert.objects.filter(pk=sent.pk).update(created_at=timezone.now() - timedelta(minutes=30))
        second_manual = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )
        self.assertEqual(second_manual.status, Alert.Status.SENT)
        self.assertEqual(second_manual.reason, "manual_request")
        self.assertEqual(send.call_count, 3)

    @patch("monitor.services.send_product_alert", return_value="107")
    def test_recent_automatic_alert_blocks_manual_request(self, send):
        automatic = request_product_alert(
            self.product, self.check(), ObservationSource.SCRAPER, monitor_settings=self.settings
        )
        manual = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )

        self.assertEqual(automatic.status, Alert.Status.SENT)
        self.assertEqual(manual.status, Alert.Status.SKIPPED)
        self.assertEqual(manual.reason, "anti_false_restock_cooldown")
        self.assertEqual(send.call_count, 1)

    @patch("monitor.services.send_product_alert", return_value="108")
    def test_recent_manual_alert_blocks_automatic_and_manual_sources(self, send):
        first_manual = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )
        automatic = request_product_alert(
            self.product, self.check(ObservationSource.CREATORS_API),
            ObservationSource.CREATORS_API, monitor_settings=self.settings,
        )
        second_manual = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )

        self.assertEqual(first_manual.status, Alert.Status.SENT)
        self.assertEqual(automatic.reason, "anti_false_restock_cooldown")
        self.assertEqual(second_manual.reason, "anti_false_restock_cooldown")
        self.assertEqual(send.call_count, 1)

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

    @patch("monitor.services.send_product_alert", return_value="106")
    def test_manual_request_keeps_inactive_and_concurrent_safety(self, send):
        self.product.is_active = False
        self.product.save(update_fields=("is_active",))
        inactive = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )
        self.assertEqual(inactive.reason, "product_inactive")

        self.product.is_active = True
        self.product.save(update_fields=("is_active",))
        check = self.check(ObservationSource.MANUAL, price=None)
        Alert.objects.create(
            product=self.product, product_check=check, source=ObservationSource.MANUAL,
            status=Alert.Status.PROCESSING, reason="manual_request",
            reservation_expires_at=timezone.now() + timedelta(seconds=30),
        )
        concurrent = request_product_alert(
            self.product, self.check(ObservationSource.MANUAL, price=None),
            ObservationSource.MANUAL, monitor_settings=self.settings,
        )
        self.assertEqual(concurrent.reason, "alert_in_progress")
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

    @patch("monitor.services.send_product_alert", return_value="105")
    def test_alert_performance_separates_rule_and_persistence_stages(self, send):
        timing = MonitorPerformance()

        result = request_product_alert(
            self.product,
            self.check(),
            ObservationSource.SCRAPER,
            monitor_settings=self.settings,
            timing=timing,
        )

        self.assertEqual(result.status, Alert.Status.SENT)
        names = [entry["name"] for entry in timing.finish()["alerts"]]
        self.assertIn("alert_reservation", names)
        self.assertIn("rule_state_load", names)
        self.assertIn("rule_evaluation", names)
        self.assertIn("alert_insert", names)
        self.assertIn("telegram_send", names)
        self.assertNotIn("alert_decision", names)

    @patch("monitor.services.load_alert_rule_state")
    def test_fast_precheck_does_not_load_alert_history(self, load_rule_state):
        result = request_product_alert(
            self.product,
            self.check(price=Decimal("1100")),
            ObservationSource.SCRAPER,
            monitor_settings=self.settings,
        )

        self.assertEqual(result.status, Alert.Status.SKIPPED)
        self.assertEqual(result.reason, "price_above_target")
        load_rule_state.assert_not_called()


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
        self.assertEqual(product.image_url, "")
        self.assertIsNone(product.image_refreshed_at)
        send.assert_called_once()
        self.assertEqual(
            send.call_args.kwargs["creator_content"].image_url,
            "https://m.media-amazon.com/product.jpg",
        )


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
        self.assertContains(response, "Sin grupo")
        self.assertNotContains(response, "Inactivo")
        response = self.client.get(reverse("manual_alerts"), {"group": "ungrouped"})
        self.assertContains(response, "Activo")

    def test_panel_does_not_show_effective_cooldown_as_a_block(self):
        self.active.cooldown_minutes = 20
        self.active.save(update_fields=("cooldown_minutes",))
        check = ProductCheck.objects.create(
            product=self.active, availability=ProductCheck.Availability.AVAILABLE,
            price=Decimal("900"), move_to_cart_visible=True,
        )
        alert = Alert.objects.create(
            product=self.active, product_check=check, status=Alert.Status.SENT,
            reason="cooldown_elapsed",
        )
        Alert.objects.filter(pk=alert.pk).update(created_at=timezone.now() - timedelta(minutes=10))

        self.client.login(username="cliente", password="secret")
        response = self.client.get(reverse("manual_alerts"), {"group": "ungrouped"})

        self.assertContains(response, "Envío manual disponible")
        self.assertNotContains(response, "Cooldown: 30 min")

    def test_panel_group_cover_does_not_load_alert_states(self):
        for index in range(20):
            Product.objects.create(
                asin=f"M{index:09d}",
                name=f"Manual {index}",
                max_price=Decimal("1000"),
            )
        self.client.login(username="cliente", password="secret")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("manual_alerts"))

        self.assertEqual(response.status_code, 200)
        alert_queries = [
            query["sql"] for query in queries
            if 'FROM "monitor_alert"' in query["sql"]
        ]
        self.assertEqual(len(alert_queries), 0)

    def test_panel_marks_anti_false_with_one_embedded_alert_subquery(self):
        settings = MonitorSettings.load()
        settings.anti_false_restock_cooldown_minutes = 5
        settings.save(update_fields=("anti_false_restock_cooldown_minutes",))
        check = ProductCheck.objects.create(
            product=self.active, source=ObservationSource.MANUAL,
            availability=ProductCheck.Availability.AVAILABLE,
        )
        Alert.objects.create(
            product=self.active, product_check=check, source=ObservationSource.MANUAL,
            status=Alert.Status.SENT, reason="manual_request",
        )
        self.client.login(username="cliente", password="secret")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("manual_alerts"), {"group": "ungrouped"})

        self.assertContains(response, "Cooldown anti-falso-restock activo")
        product_queries_with_alert_subquery = [
            query["sql"] for query in queries
            if 'FROM "monitor_product"' in query["sql"]
            and 'monitor_alert' in query["sql"]
        ]
        self.assertEqual(len(product_queries_with_alert_subquery), 1)

    def test_panel_search_does_not_match_internal_observations(self):
        self.active.observations = "Dato interno especial"
        self.active.save(update_fields=("observations",))
        self.client.login(username="cliente", password="secret")

        response = self.client.get(reverse("manual_alerts"), {"q": "interno especial"})

        self.assertNotContains(response, "Activo")
        self.assertContains(response, "No hay productos activos que coincidan")

    @patch("monitor.services.send_product_alert", return_value="301")
    def test_manual_post_sends_and_audits_user(self, send):
        self.client.login(username="cliente", password="secret")
        response = self.client.post(reverse("send_manual_alert", args=[self.active.pk]), follow=True)
        self.assertContains(response, "enviada correctamente")
        alert = Alert.objects.get(status=Alert.Status.SENT)
        self.assertEqual(alert.source, ObservationSource.MANUAL)
        self.assertEqual(alert.requested_by, self.user)
        send.assert_called_once()
