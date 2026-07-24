from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class AdminNavigationTests(TestCase):
    def test_admin_has_link_back_to_tools_dashboard(self):
        User.objects.create_superuser(
            username="admin-navigation",
            email="admin@example.com",
            password="secret",
        )
        self.client.login(username="admin-navigation", password="secret")

        response = self.client.get(reverse("admin:index"))

        self.assertContains(response, "Panel de herramientas")
        self.assertContains(response, f'href="{reverse("dashboard")}"')
        self.assertContains(response, "scrollbar-color:")
