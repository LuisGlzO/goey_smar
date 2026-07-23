from django.core.management.base import BaseCommand

from monitor.services import recover_stale_monitor_runs


class Command(BaseCommand):
    help = "Marca como fallidas las ejecuciones running que ya superaron la ventana stale."

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, choices=("amazon_a", "amazon_b"))

    def handle(self, *args, **options):
        recovered = recover_stale_monitor_runs(worker_key=f"scraper:{options['account']}")
        self.stdout.write(self.style.SUCCESS(f"Ejecuciones stale recuperadas: {recovered}."))
