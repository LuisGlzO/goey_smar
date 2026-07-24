from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from monitor.models import CartSnapshotItem, MonitorRun, Product


class CatalogCartComparisonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("manager", password="secret")
        self.user.user_permissions.add(Permission.objects.get(codename="view_product"))
        self.client.login(username="manager", password="secret")

    def snapshot(self, account, *asins):
        run = MonitorRun.objects.create(
            worker_key=f"scraper:{account}",
            status=MonitorRun.Status.SUCCESS,
            finished_at=timezone.now(),
            items_seen=len(asins),
        )
        for asin in asins:
            CartSnapshotItem.objects.create(
                run=run, scraper_account_id=account, asin=asin, source="saved",
                price=Decimal("199.00"),
                product_url=f"https://www.amazon.com.mx/dp/{asin}",
                raw_text=f"Nombre visible {asin}",
            )
        return run

    def test_requires_product_view_permission(self):
        self.user.user_permissions.clear()
        self.assertEqual(self.client.get(reverse("catalog_cart_comparison")).status_code, 403)

    def test_compares_latest_snapshot_for_each_assigned_account(self):
        present = Product.objects.create(
            asin="B0PRESENT1", name="Presente A", max_price=100,
            scraper_account_id="amazon_a",
        )
        missing = Product.objects.create(
            asin="B0MISSING1", name="Faltante B", max_price=100,
            scraper_account_id="amazon_b",
        )
        self.snapshot("amazon_a", present.asin, "B0UNKNOWN1")
        self.snapshot("amazon_b")

        response = self.client.get(reverse("catalog_cart_comparison"))

        self.assertContains(response, "B0UNKNOWN1")
        self.assertContains(response, missing.name)
        self.assertNotIn(present, response.context["only_in_catalog"])

    def test_ignores_items_from_older_successful_snapshot(self):
        self.snapshot("amazon_a", "B0OLDITEM1")
        latest = self.snapshot("amazon_a", "B0NEWITEM1")

        response = self.client.get(reverse("catalog_cart_comparison"))

        self.assertContains(response, "B0NEWITEM1")
        self.assertNotContains(response, "B0OLDITEM1")
        self.assertEqual(response.context["account_snapshots"][0]["run"], latest)

    def test_does_not_report_catalog_as_missing_without_a_snapshot(self):
        Product.objects.create(
            asin="B0NODATA01", name="Sin datos aún", max_price=100,
            scraper_account_id="amazon_b",
        )

        response = self.client.get(reverse("catalog_cart_comparison"))

        self.assertNotContains(response, "Sin datos aún")
        self.assertContains(response, "Sin lecturas exitosas")
