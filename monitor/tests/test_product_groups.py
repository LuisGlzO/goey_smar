from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from monitor.models import Product, ProductGroup


class ProductGroupModelTests(TestCase):
    def test_color_validation_and_set_null_on_delete(self):
        group = ProductGroup(name="Ofertas", color="invalid")
        with self.assertRaises(ValidationError):
            group.full_clean()

        group = ProductGroup.objects.create(
            name="Ofertas", description="Productos prioritarios", color="#30e3ca"
        )
        product = Product.objects.create(
            asin="B0GROUP001", name="Producto", max_price=Decimal("100"), group=group
        )
        group.delete()
        product.refresh_from_db()
        self.assertIsNone(product.group)


class ProductGroupManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("groups-manager", password="secret")
        self.client.login(username="groups-manager", password="secret")

    def grant(self, *codenames):
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))

    def test_crud_uses_equivalent_product_permissions(self):
        self.assertEqual(self.client.get(reverse("product_groups")).status_code, 403)
        self.grant("view_product", "add_product", "change_product", "delete_product")

        response = self.client.post(reverse("product_group_create"), {
            "name": "Tecnología", "description": "Dispositivos", "color": "#123ABC",
        })
        self.assertRedirects(response, reverse("product_groups"))
        group = ProductGroup.objects.get()

        response = self.client.post(reverse("product_group_edit", args=[group.pk]), {
            "name": "Tecnología premium", "description": "", "color": "#ABCDEF",
        })
        self.assertRedirects(response, reverse("product_groups"))
        group.refresh_from_db()
        self.assertEqual(group.color, "#ABCDEF")

        product = Product.objects.create(
            asin="B0GROUP002", name="Asignado", max_price=Decimal("100"), group=group
        )
        response = self.client.post(reverse("product_group_delete", args=[group.pk]))
        self.assertRedirects(response, reverse("product_groups"))
        product.refresh_from_db()
        self.assertIsNone(product.group)

    def test_delete_uses_reusable_confirmation_dialog(self):
        self.grant("view_product", "delete_product")
        group = ProductGroup.objects.create(name="Confirmación", color="#123456")

        response = self.client.get(reverse("product_groups"))

        self.assertContains(response, 'data-confirm-dialog', count=1)
        self.assertContains(response, 'data-confirm-title="Eliminar grupo"')
        self.assertContains(response, f'¿Eliminar el grupo “{group.name}”?')
        self.assertNotContains(response, "return confirm(")

    def test_assignment_view_assigns_and_unassigns_multiple_available_products(self):
        self.grant("view_product", "change_product")
        group = ProductGroup.objects.create(name="Destino", color="#123456")
        other_group = ProductGroup.objects.create(name="Otro", color="#654321")
        assigned = Product.objects.create(
            asin="B0GROUP006", name="Ya asignado", max_price=100, group=group
        )
        ungrouped_a = Product.objects.create(
            asin="B0GROUP007", name="Disponible A", max_price=100
        )
        ungrouped_b = Product.objects.create(
            asin="B0GROUP008", name="Disponible B", max_price=100
        )
        unavailable = Product.objects.create(
            asin="B0GROUP009", name="No disponible", max_price=100, group=other_group
        )

        edit_response = self.client.get(reverse("product_group_edit", args=[group.pk]))
        self.assertNotContains(edit_response, assigned.name)
        self.assertNotContains(edit_response, "Productos disponibles")

        response = self.client.get(reverse("product_group_products", args=[group.pk]))
        self.assertContains(response, assigned.name)
        self.assertContains(response, ungrouped_a.name)
        self.assertContains(response, ungrouped_b.name)
        self.assertNotContains(response, unavailable.name)

        response = self.client.post(reverse("product_group_products", args=[group.pk]), {
            "products": [str(ungrouped_a.pk), str(ungrouped_b.pk)],
        })
        self.assertRedirects(response, reverse("product_group_products", args=[group.pk]))
        assigned.refresh_from_db()
        ungrouped_a.refresh_from_db()
        ungrouped_b.refresh_from_db()
        unavailable.refresh_from_db()
        self.assertIsNone(assigned.group)
        self.assertEqual(ungrouped_a.group, group)
        self.assertEqual(ungrouped_b.group, group)
        self.assertEqual(unavailable.group, other_group)

        response = self.client.post(reverse("product_group_products", args=[group.pk]), {
            "products": [str(unavailable.pk)],
        })
        self.assertEqual(response.status_code, 200)
        unavailable.refresh_from_db()
        self.assertEqual(unavailable.group, other_group)


class ManualAlertGroupsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alerts-groups", password="secret")
        self.user.user_permissions.add(Permission.objects.get(codename="send_manual_alert"))
        self.client.login(username="alerts-groups", password="secret")
        self.group = ProductGroup.objects.create(
            name="Gaming", description="Consolas y juegos", color="#445566"
        )
        self.assigned = Product.objects.create(
            asin="B0GROUP003", name="Consola", max_price=Decimal("100"), group=self.group
        )
        self.ungrouped = Product.objects.create(
            asin="B0GROUP004", name="Control", max_price=Decimal("100")
        )
        Product.objects.create(
            asin="B0GROUP005", name="Inactivo agrupado", max_price=Decimal("100"),
            group=self.group, is_active=False,
        )

    def test_landing_lists_groups_and_active_counts(self):
        empty = ProductGroup.objects.create(name="Vacío", color="#778899")
        response = self.client.get(reverse("manual_alerts"))
        self.assertContains(response, self.group.name)
        self.assertContains(response, empty.name)
        self.assertContains(response, "Sin grupo")
        self.assertEqual(response.context["groups"].get(pk=self.group.pk).active_product_count, 1)

    def test_landing_respects_explicit_group_display_order(self):
        first = ProductGroup.objects.create(name="Primero", color="#111111", display_order=0)
        self.group.display_order = 2
        self.group.save(update_fields=("display_order",))
        middle = ProductGroup.objects.create(name="Segundo", color="#222222", display_order=1)

        response = self.client.get(reverse("manual_alerts"))

        self.assertEqual(
            [group.pk for group in response.context["groups"]],
            [first.pk, middle.pk, self.group.pk],
        )

    def test_group_and_global_search_behaviors(self):
        response = self.client.get(reverse("manual_alerts"), {"group": self.group.pk})
        self.assertContains(response, self.assigned.name)
        self.assertNotContains(response, self.ungrouped.name)

        response = self.client.get(reverse("manual_alerts"), {
            "group": self.group.pk, "q": self.ungrouped.asin,
        })
        self.assertContains(response, self.ungrouped.name)
        self.assertNotContains(response, self.assigned.name)

        self.assertEqual(
            self.client.get(reverse("manual_alerts"), {"group": "invalid"}).status_code,
            404,
        )
