from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from monitor.amazon_creators import CreatorProductContent
from monitor.forms import AffiliateLinkGeneratorForm


class AffiliateLinkGeneratorFormTests(TestCase):
    def test_normalizes_deduplicates_and_accepts_common_separators(self):
        form = AffiliateLinkGeneratorForm({
            "asins": "b0abc12345, B0XYZ12345\nB0ABC12345",
        })

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["asins"], ["B0ABC12345", "B0XYZ12345"])

    def test_rejects_invalid_asin(self):
        form = AffiliateLinkGeneratorForm({"asins": "INVALID"})

        self.assertFalse(form.is_valid())
        self.assertIn("exactamente 10", form.errors["asins"][0])


@override_settings(
    AMAZON_CREATORS_API_CLIENT_ID="client",
    AMAZON_CREATORS_API_CLIENT_SECRET="secret",
    AMAZON_CREATORS_API_PARTNER_TAG="creator-20",
)
class AffiliateLinkGeneratorViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("link-manager", password="secret")
        self.user.user_permissions.add(Permission.objects.get(codename="view_product"))
        self.client.login(username="link-manager", password="secret")

    def test_requires_product_view_permission(self):
        self.user.user_permissions.clear()
        self.assertEqual(self.client.get(reverse("affiliate_link_generator")).status_code, 403)

    @patch("monitor.views.get_products_content")
    def test_returns_creator_urls_without_persisting(self, get_products_content):
        get_products_content.return_value = {
            "B0ABC12345": CreatorProductContent(
                title="Producto Amazon",
                image_url="https://images.example/product.jpg",
                detail_page_url="https://amazon.com.mx/dp/B0ABC12345?tag=creator-20",
            )
        }

        response = self.client.post(
            reverse("affiliate_link_generator"),
            {"asins": "B0ABC12345, B0MISSING1"},
        )

        self.assertContains(response, "https://amazon.com.mx/dp/B0ABC12345?tag=creator-20")
        self.assertContains(response, "Creators API no devolvió un enlace")
        get_products_content.assert_called_once_with(["B0ABC12345", "B0MISSING1"])

    @patch("monitor.views.get_products_content")
    def test_splits_large_queries_into_api_batches_of_ten(self, get_products_content):
        get_products_content.return_value = {}
        asins = [f"A{index:09d}" for index in range(11)]

        self.client.post(reverse("affiliate_link_generator"), {"asins": ",".join(asins)})

        self.assertEqual(get_products_content.call_count, 2)
        self.assertEqual(len(get_products_content.call_args_list[0].args[0]), 10)
        self.assertEqual(len(get_products_content.call_args_list[1].args[0]), 1)
