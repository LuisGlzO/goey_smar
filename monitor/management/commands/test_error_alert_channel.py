from django.core.management.base import BaseCommand, CommandError

from monitor.telegram import send_monitor_test_alert


class Command(BaseCommand):
    help = "Envia un mensaje de prueba al canal tecnico de errores de Telegram."

    def add_arguments(self, parser):
        parser.add_argument(
            "--message",
            default="",
            help="Texto opcional para identificar la prueba en Telegram.",
        )

    def handle(self, *args, **options):
        try:
            message_id = send_monitor_test_alert(options["message"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        suffix = f" Mensaje ID: {message_id}." if message_id else ""
        self.stdout.write(self.style.SUCCESS(f"Canal tecnico de Telegram verificado.{suffix}"))
