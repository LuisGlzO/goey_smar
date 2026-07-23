from django.core.management.base import BaseCommand, CommandError

from monitor.scraper import scrape_saved_items
from monitor.services import determine_availability, scraper_profile_dir


class Command(BaseCommand):
    help = "Lista los elementos detectados en carrito y Guardado para más tarde sin enviar alertas."

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, choices=("amazon_a", "amazon_b"))

    def handle(self, *args, **options):
        account_key = options["account"]
        try:
            items = scrape_saved_items(account_key, scraper_profile_dir(account_key))
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if not items:
            self.stdout.write("No se detectaron elementos en carrito ni en Guardado para más tarde.")
            return

        for item in items:
            preview = item.raw_text[:160].replace("\n", " ")
            self.stdout.write(
                f"source={item.source} ASIN={item.asin} price={item.price} availability={determine_availability(item)} "
                f"move_to_cart={item.move_to_cart_visible} unavailable_text={item.unavailable_message_visible} "
                f"url={item.product_url}\n  {preview}"
            )
