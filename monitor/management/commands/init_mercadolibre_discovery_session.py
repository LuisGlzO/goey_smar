from django.conf import settings
from django.core.management.base import BaseCommand

from monitor.mercado_libre_discovery import (
    chromium_user_agent,
    cleanup_mercado_libre_profile_locks,
    normalize_mercado_libre_url,
)


def get_sync_playwright():
    from playwright.sync_api import sync_playwright

    return sync_playwright


class Command(BaseCommand):
    help = "Inicializa el perfil público persistente exclusivo de Mercado Libre Discovery."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default="https://listado.mercadolibre.com.mx/",
            help="URL pública que se abrirá para resolver la verificación.",
        )

    def handle(self, *args, **options):
        url = normalize_mercado_libre_url(options["url"])
        profile_dir = settings.MERCADOLIBRE_DISCOVERY_PROFILE_DIR
        cleanup_mercado_libre_profile_locks(profile_dir)
        with get_sync_playwright()() as playwright:
            context = playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                locale="es-MX",
                timezone_id="America/Mexico_City",
                viewport={"width": 1440, "height": 1000},
                user_agent=chromium_user_agent(playwright),
                args=("--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"),
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            self.stdout.write(
                "Resuelva la verificación de Mercado Libre y confirme que el listado sea visible. "
                "Presione Enter aquí al terminar."
            )
            input()
            context.close()
        self.stdout.write(self.style.SUCCESS(f"Perfil guardado en {profile_dir}."))
