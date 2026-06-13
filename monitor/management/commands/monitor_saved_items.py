from django.core.management.base import BaseCommand, CommandError

from monitor.services import run_monitor


class Command(BaseCommand):
    help = "Ejecuta una revisión inmediata de Guardado para más tarde."

    def handle(self, *args, **options):
        try:
            run = run_monitor()
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Ejecución {run.pk}: {run.items_seen} elementos visibles."))
