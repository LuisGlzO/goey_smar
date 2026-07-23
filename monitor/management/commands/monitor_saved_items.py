from django.core.management.base import BaseCommand, CommandError

from monitor.services import run_monitor


class Command(BaseCommand):
    help = "Ejecuta una revision inmediata de Guardado para mas tarde."

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, choices=("amazon_a", "amazon_b"))

    def handle(self, *args, **options):
        try:
            run = run_monitor(options["account"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        duration = (run.finished_at - run.started_at).total_seconds() if run.finished_at else 0
        self.stdout.write(
            self.style.SUCCESS(
                f"Ejecucion {run.pk}: {run.items_seen} elementos visibles en {duration:.2f}s. Estado: {run.status}."
            )
        )
        timings = []
        performance = run.performance or {}
        for group in ("stages", "scraper", "alerts"):
            for entry in performance.get(group, []):
                timings.append((entry.get("seconds", 0), group, entry))
        for seconds, group, entry in sorted(
            timings,
            key=lambda timing: timing[0],
            reverse=True,
        )[:8]:
            details = ", ".join(
                f"{key}={value}" for key, value in entry.items() if key not in {"name", "seconds"}
            )
            suffix = f" ({details})" if details else ""
            self.stdout.write(f"  {group}.{entry.get('name')}: {seconds:.3f}s{suffix}")
