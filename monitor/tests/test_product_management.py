from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from monitor.amazon_creators import CreatorProductContent
from monitor.models import Product


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
            "asin": "B0NEW12345", "name": "Producto nuevo", "affiliate_url": "",
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
        self.assertEqual(product.image_url, "https://m.media-amazon.com/photo.jpg")
        self.assertIsNotNone(product.image_refreshed_at)

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
        self.assertEqual((untouched.cooldown_minutes, untouched.max_alerts_per_day), (60, 3))

    def test_bulk_update_rejects_empty_selection_and_empty_values(self):
        self.grant("view_product", "change_product")
        response = self.client.post(reverse("products_bulk_update"), {
            "product_ids": "", "cooldown_minutes": "", "max_alerts_per_day": "",
        }, follow=True)
        self.assertContains(response, "Selecciona al menos un producto")
        self.product.refresh_from_db()
        self.assertEqual(self.product.cooldown_minutes, 60)
