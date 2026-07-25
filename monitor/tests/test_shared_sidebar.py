from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class SharedSidebarTests(TestCase):
    def setUp(self):
        User.objects.create_superuser(
            username="sidebar-admin",
            email="sidebar@example.com",
            password="secret",
        )
        self.client.login(username="sidebar-admin", password="secret")

    def test_sidebar_is_present_once_on_every_tool_view(self):
        for url_name in (
            "dashboard",
            "products",
            "catalog_cart_comparison",
            "affiliate_link_generator",
            "manual_alerts",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'data-sidebar aria-label="Navegación principal"', count=1)
                self.assertContains(response, "Generador de enlaces")
                self.assertContains(response, "Catálogo vs. carritos")

    def test_current_tool_is_marked_active(self):
        response = self.client.get(reverse("affiliate_link_generator"))

        self.assertContains(
            response,
            'class="nav-item active" href="/generador-enlaces/"',
            count=1,
        )

    def test_login_does_not_render_authenticated_sidebar(self):
        self.client.logout()

        response = self.client.get(reverse("login"))

        self.assertNotContains(response, "data-sidebar")
