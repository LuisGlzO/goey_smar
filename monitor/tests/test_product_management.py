from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from monitor.amazon_creators import CreatorProductContent
from django.db.models import ProtectedError

from monitor.models import Product, ProductGroup, ScraperAccount


class ProductManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("manager", password="secret")
        self.product = Product.objects.create(
            asin="B0ABC12345", name="Producto inicial", max_price=Decimal("1000")
        )

    def grant(self, *codenames):
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
        self.client.login(username="manager", password="secret")

    def payload(self, **overrides):
        values = {
            "asin": "B0NEW12345", "name": "Producto nuevo", "observations": "",
            "affiliate_url": "",
            "scraper_account": "amazon_a",
            "max_price": "900.00", "priority": "20", "is_active": "on",
            "cooldown_minutes": "60", "max_alerts_per_day": "3",
            "significant_price_drop_percent": "5.00",
        }
        values.update(overrides)
        return values

    def test_list_requires_view_permission(self):
        self.client.login(username="manager", password="secret")
        self.assertEqual(self.client.get(reverse("products")).status_code, 403)
        self.grant("view_product")
        self.assertContains(self.client.get(reverse("products")), "Producto inicial")

    def test_search_status_and_pagination(self):
        for index in range(25):
            Product.objects.create(
                asin=f"A{index:09d}", name=f"Catálogo {index}", max_price=100,
                is_active=index != 7,
            )
        self.grant("view_product")
        response = self.client.get(reverse("products"), {"status": "inactive"})
        self.assertContains(response, "Catálogo 7")
        self.assertNotContains(response, "Producto inicial")
        response = self.client.get(reverse("products"), {"q": "Producto inicial"})
        self.assertEqual(list(response.context["page"]), [self.product])
        response = self.client.get(reverse("products"))
        self.assertEqual(response.context["page"].paginator.per_page, 25)
        self.assertEqual(response.context["page"].paginator.num_pages, 2)

    @patch("monitor.views.safe_get_product_content")
    def test_create_fetches_image_without_replacing_local_name(self, get_content):
        get_content.return_value = CreatorProductContent(
            "Nombre Amazon", "https://m.media-amazon.com/photo.jpg", "https://amazon/item"
        )
        self.grant("view_product", "add_product")
        response = self.client.post(reverse("product_create"), self.payload())
        self.assertRedirects(response, reverse("products"))
        product = Product.objects.get(asin="B0NEW12345")
        self.assertEqual(product.name, "Producto nuevo")
        self.assertEqual(product.observations, "")
        self.assertEqual(product.image_url, "https://m.media-amazon.com/photo.jpg")
        self.assertIsNotNone(product.image_refreshed_at)

    @patch("monitor.views.safe_get_product_content")
    def test_create_uses_creators_title_when_name_is_empty(self, get_content):
        get_content.return_value = CreatorProductContent(
            "Nombre Amazon", "https://m.media-amazon.com/photo.jpg", "https://amazon/item"
        )
        self.grant("view_product", "add_product")
        response = self.client.post(reverse("product_create"), self.payload(name=""))
        self.assertRedirects(response, reverse("products"))
        product = Product.objects.get(asin="B0NEW12345")
        self.assertEqual(product.name, "Nombre Amazon")
        self.assertEqual(product.image_url, "https://m.media-amazon.com/photo.jpg")
        get_content.assert_called_once_with("B0NEW12345")

    @patch("monitor.views.safe_get_product_content", return_value=None)
    def test_create_with_empty_name_is_not_saved_when_creators_fails(self, get_content):
        self.grant("view_product", "add_product")
        response = self.client.post(reverse("product_create"), self.payload(name=""))
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "name",
            "Creators API no devolvió un nombre. Escribe uno o intenta nuevamente.",
        )
        self.assertFalse(Product.objects.filter(asin="B0NEW12345").exists())

    @patch("monitor.views.safe_get_product_content", return_value=None)
    def test_observations_are_saved_and_searchable(self, get_content):
        self.grant("view_product", "add_product")
        response = self.client.post(
            reverse("product_create"),
            self.payload(observations="Prioridad del cliente, no publicar esta nota"),
        )
        self.assertRedirects(response, reverse("products"))
        product = Product.objects.get(asin="B0NEW12345")
        self.assertEqual(product.observations, "Prioridad del cliente, no publicar esta nota")

        response = self.client.get(reverse("products"), {"q": "Prioridad del cliente"})
        self.assertContains(response, "Producto nuevo")

    def test_create_requires_scraper_account(self):
        self.grant("view_product", "add_product")
        payload = self.payload()
        payload.pop("scraper_account")
        response = self.client.post(reverse("product_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "scraper_account", "Este campo es obligatorio.")

    @patch("monitor.views.safe_get_product_content", return_value=None)
    def test_create_and_edit_can_assign_and_clear_group(self, get_content):
        group = ProductGroup.objects.create(name="Grupo catálogo", color="#123456")
        self.grant("view_product", "add_product", "change_product")
        response = self.client.post(
            reverse("product_create"), self.payload(group=str(group.pk))
        )
        self.assertRedirects(response, reverse("products"))
        product = Product.objects.get(asin="B0NEW12345")
        self.assertEqual(product.group, group)

        response = self.client.post(
            reverse("product_edit", args=[product.pk]),
            self.payload(asin=product.asin, name=product.name, group=""),
        )
        self.assertRedirects(response, reverse("products"))
        product.refresh_from_db()
        self.assertIsNone(product.group)

    @patch("monitor.views.safe_get_product_content", return_value=None)
    def test_edit_can_reassign_account_without_replacing_history(self, get_content):
        self.grant("view_product", "change_product")
        response = self.client.post(
            reverse("product_edit", args=[self.product.pk]),
            self.payload(asin=self.product.asin, name=self.product.name, scraper_account="amazon_b"),
        )
        self.assertRedirects(response, reverse("products"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.scraper_account_id, "amazon_b")

    def test_account_with_products_is_protected_from_deletion(self):
        with self.assertRaises(ProtectedError):
            ScraperAccount.objects.get(pk="amazon_a").delete()

    @patch("monitor.views.safe_get_product_content", return_value=None)
    def test_api_failure_does_not_cancel_creation(self, get_content):
        self.grant("view_product", "add_product")
        response = self.client.post(reverse("product_create"), self.payload(), follow=True)
        self.assertContains(response, "Producto creado")
        self.assertTrue(Product.objects.filter(asin="B0NEW12345", image_url="").exists())

    @patch("monitor.views.safe_get_product_content")
    def test_edit_changed_asin_refreshes_image(self, get_content):
        self.product.image_url = "https://old/image.jpg"
        self.product.save(update_fields=("image_url",))
        get_content.return_value = CreatorProductContent("Amazon", "https://new/image.jpg", "")
        self.grant("view_product", "change_product")
        response = self.client.post(
            reverse("product_edit", args=[self.product.pk]),
            self.payload(asin="B0EDIT1234", name="Nombre local"),
        )
        self.assertRedirects(response, reverse("products"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.image_url, "https://new/image.jpg")
        self.assertEqual(self.product.name, "Nombre local")

    @patch("monitor.views.safe_get_product_content")
    def test_edit_uses_creators_title_when_name_is_empty(self, get_content):
        get_content.return_value = CreatorProductContent(
            "Nombre Amazon editado", "https://new/image.jpg", ""
        )
        self.grant("view_product", "change_product")
        response = self.client.post(
            reverse("product_edit", args=[self.product.pk]),
            self.payload(asin=self.product.asin, name=""),
        )
        self.assertRedirects(response, reverse("products"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Nombre Amazon editado")
        self.assertEqual(self.product.image_url, "https://new/image.jpg")
        get_content.assert_called_once_with(self.product.asin)

    def test_bulk_update_changes_only_selected_products_and_accepts_zero(self):
        other = Product.objects.create(asin="B0XYZ12345", name="Otro", max_price=100)
        untouched = Product.objects.create(asin="B0ZZZ12345", name="Sin cambios", max_price=100)
        self.grant("view_product", "change_product")
        response = self.client.post(reverse("products_bulk_update"), {
            "product_ids": f"{self.product.pk},{other.pk}",
            "cooldown_minutes": "0", "max_alerts_per_day": "7",
        })
        self.assertRedirects(response, reverse("products"))
        self.product.refresh_from_db(); other.refresh_from_db(); untouched.refresh_from_db()
        self.assertEqual((self.product.cooldown_minutes, self.product.max_alerts_per_day), (0, 7))
        self.assertEqual((other.cooldown_minutes, other.max_alerts_per_day), (0, 7))
        self.assertEqual((untouched.cooldown_minutes, untouched.max_alerts_per_day), (60, 99))

    def test_bulk_update_changes_price_status_and_cart(self):
        other = Product.objects.create(asin="B0XYZ12345", name="Otro", max_price=100)
        untouched = Product.objects.create(asin="B0ZZZ12345", name="Sin cambios", max_price=100)
        self.grant("view_product", "change_product")
        response = self.client.post(reverse("products_bulk_update"), {
            "product_ids": f"{self.product.pk},{other.pk}",
            "cooldown_minutes": "",
            "max_alerts_per_day": "",
            "max_price": "0",
            "is_active": "false",
            "scraper_account": "amazon_b",
        })
        self.assertRedirects(response, reverse("products"))
        self.product.refresh_from_db(); other.refresh_from_db(); untouched.refresh_from_db()
        for product in (self.product, other):
            self.assertEqual(product.max_price, Decimal("0"))
            self.assertFalse(product.is_active)
            self.assertEqual(product.scraper_account_id, "amazon_b")
        self.assertEqual(untouched.max_price, Decimal("100"))
        self.assertTrue(untouched.is_active)
        self.assertEqual(untouched.scraper_account_id, "amazon_a")

    def test_new_product_defaults_are_high_99_and_one_percent(self):
        product = Product.objects.create(asin="B0DEFAULT1", name="Defaults", max_price=100)
        self.assertEqual(product.priority, Product.Priority.HIGH)
        self.assertEqual(product.max_alerts_per_day, 99)
        self.assertEqual(product.significant_price_drop_percent, Decimal("1"))
        self.grant("add_product")
        form = self.client.get(reverse("product_create")).context["form"]
        self.assertEqual(form["priority"].value(), Product.Priority.HIGH)
        self.assertEqual(form["max_alerts_per_day"].value(), 99)
        self.assertEqual(form["significant_price_drop_percent"].value(), 1)

    def test_bulk_update_rejects_empty_selection_and_empty_values(self):
        self.grant("view_product", "change_product")
        response = self.client.post(reverse("products_bulk_update"), {
            "product_ids": "", "cooldown_minutes": "", "max_alerts_per_day": "",
            "max_price": "", "is_active": "", "scraper_account": "",
        }, follow=True)
        self.assertContains(response, "Selecciona al menos un producto")
        self.product.refresh_from_db()
        self.assertEqual(self.product.cooldown_minutes, 60)
