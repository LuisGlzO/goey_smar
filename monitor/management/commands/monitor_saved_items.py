from django.core.management.base import BaseCommand, CommandError

from monitor.services import run_monitor


class Command(BaseCommand):
    help = "Ejecuta una revision inmediata de Guardado para mas tarde."

    def handle(self, *args, **options):
        try:
            run = run_monitor()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        duration = (run.finished_at - run.started_at).total_seconds() if run.finished_at else 0
        self.stdout.write(
            self.style.SUCCESS(
                f"Ejecucion {run.pk}: {run.items_seen} elementos visibles en {duration:.2f}s. Estado: {run.status}."
            )
        )
