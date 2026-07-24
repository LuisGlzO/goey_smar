from django.conf import settings
from django.core.management.base import BaseCommand

from monitor.scraper import validate_profile_owner
from monitor.services import scraper_profile_dir


def get_sync_playwright():
    from playwright.sync_api import sync_playwright

    return sync_playwright


class Command(BaseCommand):
    help = "Abre Amazon para iniciar sesión manualmente y guarda el perfil persistente."

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, choices=("amazon_a", "amazon_b"))

    def handle(self, *args, **options):
        profile_dir = scraper_profile_dir(options["account"])
        validate_profile_owner(profile_dir, options["account"])
        with get_sync_playwright()() as playwright:
            context = playwright.chromium.launch_persistent_context(profile_dir, headless=False, locale="es-MX")
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(settings.AMAZON_SAVED_ITEMS_URL)
            self.stdout.write("Inicie sesión y abra Guardado para más tarde. Presione Enter aquí al terminar.")
            input()
            context.close()
        self.stdout.write(self.style.SUCCESS("Sesión guardada."))
