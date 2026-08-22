from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from monitor.management.commands import init_mercadolibre_discovery_session as command_module


class InitMercadoLibreDiscoverySessionCommandTests(SimpleTestCase):
    def test_opens_public_url_with_exclusive_persistent_profile(self):
        with TemporaryDirectory() as profile_dir, override_settings(
            MERCADOLIBRE_DISCOVERY_PROFILE_DIR=profile_dir
        ):
            playwright = MagicMock()
            context = MagicMock()
            page = MagicMock()
            context.pages = [page]
            playwright.chromium.launch_persistent_context.return_value = context

            with (
                patch("builtins.input", return_value=""),
                patch.object(command_module, "get_sync_playwright") as get_sync_playwright,
            ):
                sync_playwright = MagicMock()
                get_sync_playwright.return_value = sync_playwright
                sync_playwright.return_value.__enter__.return_value = playwright

                call_command(
                    "init_mercadolibre_discovery_session",
                    url="https://listado.mercadolibre.com.mx/pagina/tieronezone/#tracking",
                )

            launch = playwright.chromium.launch_persistent_context
            self.assertEqual(launch.call_args.args[0], profile_dir)
            self.assertFalse(launch.call_args.kwargs["headless"])
            page.goto.assert_called_once_with(
                "https://listado.mercadolibre.com.mx/pagina/tieronezone/",
                wait_until="domcontentloaded",
            )
            context.close.assert_called_once()
