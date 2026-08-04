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
        rows = {row["product"]: row for row in response.context["catalog_rows"]}
        self.assertEqual(rows[present]["diagnostic"], "reconciled")
        self.assertEqual(rows[missing]["diagnostic"], "absent")

    def test_ignores_items_from_older_successful_snapshot(self):
        self.snapshot("amazon_a", "B0OLDITEM1")
        latest = self.snapshot("amazon_a", "B0NEWITEM1")

        response = self.client.get(reverse("catalog_cart_comparison"))

        self.assertContains(response, "B0NEWITEM1")
        self.assertNotContains(response, "B0OLDITEM1")
        self.assertEqual(response.context["account_snapshots"][0]["run"], latest)

    def test_does_not_report_catalog_as_missing_without_a_snapshot(self):
        product = Product.objects.create(
            asin="B0NODATA01", name="Sin datos aún", max_price=100,
            scraper_account_id="amazon_b",
        )

        response = self.client.get(reverse("catalog_cart_comparison"))

        row = next(row for row in response.context["catalog_rows"] if row["product"] == product)
        self.assertEqual(row["diagnostic"], "incomplete")
        self.assertContains(response, "Sin datos aún")
        self.assertContains(response, "Sin lecturas exitosas")

    def test_shows_presence_in_each_cart_and_both(self):
        only_a = Product.objects.create(asin="B0ONLYA001", name="Solo A", max_price=100)
        only_b = Product.objects.create(asin="B0ONLYB001", name="Solo B", max_price=100)
        both = Product.objects.create(asin="B0BOTH0001", name="Ambos", max_price=100)
        self.snapshot("amazon_a", only_a.asin, both.asin)
        self.snapshot("amazon_b", only_b.asin, both.asin)

        response = self.client.get(reverse("catalog_cart_comparison"))
        rows = {row["product"].asin: row for row in response.context["catalog_rows"]}

        self.assertEqual(
            [state["present"] for state in rows[both.asin]["cart_states"]],
            [True, True],
        )
        self.assertEqual(
            [state["present"] for state in rows[only_a.asin]["cart_states"]],
            [True, False],
        )
        self.assertEqual(
            [state["present"] for state in rows[only_b.asin]["cart_states"]],
            [False, True],
        )

    def test_reports_assignment_misalignment(self):
        product = Product.objects.create(
            asin="B0MISALIGN", name="En carrito contrario", max_price=100,
            scraper_account_id="amazon_a",
        )
        self.snapshot("amazon_a")
        self.snapshot("amazon_b", product.asin)

        response = self.client.get(reverse("catalog_cart_comparison"))
        row = next(row for row in response.context["catalog_rows"] if row["product"] == product)

        self.assertEqual(row["diagnostic"], "misaligned")
        self.assertContains(response, "Asignación desalineada")

    def test_external_asin_in_both_carts_is_grouped_once(self):
        self.snapshot("amazon_a", "B0EXTERNAL")
        self.snapshot("amazon_b", "B0EXTERNAL")

        response = self.client.get(reverse("catalog_cart_comparison"))

        self.assertEqual(len(response.context["external_rows"]), 1)
        self.assertEqual(
            [state["present"] for state in response.context["external_rows"][0]["cart_states"]],
            [True, True],
        )

    def test_toggle_intent_requires_change_permission_and_is_reversible(self):
        product = Product.objects.create(asin="B0INTENT01", name="Intencional", max_price=100)
        url = reverse("toggle_product_cart_intention", args=[product.pk])

        self.assertEqual(self.client.post(url).status_code, 403)
        self.user.user_permissions.add(Permission.objects.get(codename="change_product"))
        self.assertRedirects(self.client.post(url), reverse("catalog_cart_comparison"))
        product.refresh_from_db()
        self.assertTrue(product.intentionally_not_in_cart)

        self.assertRedirects(self.client.post(url), reverse("catalog_cart_comparison"))
        product.refresh_from_db()
        self.assertFalse(product.intentionally_not_in_cart)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_intentional_mark_is_kept_when_product_reappears(self):
        product = Product.objects.create(
            asin="B0RETURNS1", name="Reaparecido", max_price=100,
            intentionally_not_in_cart=True,
        )
        self.snapshot("amazon_a", product.asin)
        self.snapshot("amazon_b")

        response = self.client.get(reverse("catalog_cart_comparison"))
        row = next(row for row in response.context["catalog_rows"] if row["product"] == product)

        self.assertEqual(row["diagnostic"], "intentional_present")
        product.refresh_from_db()
        self.assertTrue(product.intentionally_not_in_cart)
        self.assertContains(response, "Marcado intencional, pero reapareció")

    def test_filters_catalog_rows_and_keeps_unfiltered_counts(self):
        reconciled = Product.objects.create(asin="B0FILTER01", name="Conciliado", max_price=100)
        absent = Product.objects.create(asin="B0FILTER02", name="Ausente", max_price=100)
        intentional = Product.objects.create(
            asin="B0FILTER03", name="Intencional", max_price=100,
            intentionally_not_in_cart=True,
        )
        self.snapshot("amazon_a", reconciled.asin)
        self.snapshot("amazon_b")

        response = self.client.get(reverse("catalog_cart_comparison"), {"status": "absent"})

        self.assertEqual([row["product"] for row in response.context["catalog_rows"]], [absent])
        self.assertEqual(response.context["status_counts"], {
            "all": 3, "reconciled": 1, "absent": 1, "intentional": 1,
        })
        self.assertNotContains(response, intentional.name)
        self.assertContains(response, "Ausentes en carritos")

    def test_toggle_preserves_valid_status_filter(self):
        product = Product.objects.create(asin="B0FILTER04", name="Filtrado", max_price=100)
        self.user.user_permissions.add(Permission.objects.get(codename="change_product"))

        response = self.client.post(
            reverse("toggle_product_cart_intention", args=[product.pk]) + "?status=absent"
        )

        self.assertRedirects(
            response, reverse("catalog_cart_comparison") + "?status=absent",
            fetch_redirect_response=False,
        )
