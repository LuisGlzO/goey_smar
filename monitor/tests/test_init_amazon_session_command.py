from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from monitor.management.commands import init_amazon_session as command_module


class InitAmazonSessionCommandTests(SimpleTestCase):
    @override_settings(AMAZON_SAVED_ITEMS_URL="https://www.amazon.com.mx/cart")
    def test_opens_configured_url_for_selected_account(self):
        playwright = MagicMock()
        context = MagicMock()
        page = MagicMock()
        context.pages = [page]
        with (
            patch("builtins.input", return_value=""),
            patch.object(command_module, "validate_profile_owner") as validate_owner,
            patch.object(
                command_module, "scraper_profile_dir", return_value="C:/profiles/amazon_a"
            ) as profile_dir,
            patch.object(command_module, "get_sync_playwright") as get_sync_playwright,
        ):
            sync_playwright = MagicMock()
            get_sync_playwright.return_value = sync_playwright
            sync_playwright.return_value.__enter__.return_value = playwright
            playwright.chromium.launch_persistent_context.return_value = context

            call_command("init_amazon_session", account="amazon_a")

        profile_dir.assert_called_once_with("amazon_a")
        validate_owner.assert_called_once_with("C:/profiles/amazon_a", "amazon_a")
        playwright.chromium.launch_persistent_context.assert_called_once_with(
            "C:/profiles/amazon_a", headless=False, locale="es-MX"
        )
        page.goto.assert_called_once_with("https://www.amazon.com.mx/cart")
        context.close.assert_called_once()
