from django.conf import settings
from django.core.management.base import BaseCommand
from playwright.sync_api import sync_playwright


class Command(BaseCommand):
    help = "Abre Amazon para iniciar sesión manualmente y guarda el perfil persistente."

    def handle(self, *args, **options):
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(settings.AMAZON_PROFILE_DIR, headless=False, locale="es-MX")
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(settings.AMAZON_SAVED_ITEMS_URL)
            self.stdout.write("Inicie sesión y abra Guardado para más tarde. Presione Enter aquí al terminar.")
            input()
            context.close()
        self.stdout.write(self.style.SUCCESS("Sesión guardada."))

