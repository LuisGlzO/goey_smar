from django.core.management.base import BaseCommand

from monitor.services import recover_stale_monitor_runs


class Command(BaseCommand):
    help = "Marca como fallidas las ejecuciones running que ya superaron la ventana stale."

    def handle(self, *args, **options):
        recovered = recover_stale_monitor_runs()
        self.stdout.write(self.style.SUCCESS(f"Ejecuciones stale recuperadas: {recovered}."))
