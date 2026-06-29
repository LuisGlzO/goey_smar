import traceback

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone


def send_monitor_failure_email(run, exc: Exception) -> int:
    recipients = settings.MONITOR_FAILURE_EMAIL_RECIPIENTS
    if not recipients:
        return 0

    started_at = timezone.localtime(run.started_at).strftime("%Y-%m-%d %H:%M:%S %Z")
    finished_at = timezone.localtime(run.finished_at or timezone.now()).strftime("%Y-%m-%d %H:%M:%S %Z")
    subject = f"{settings.MONITOR_FAILURE_EMAIL_SUBJECT_PREFIX} Scraper fallido"
    body = (
        "La ejecucion del scraper fallo y requiere revision.\n\n"
        f"Run ID: {run.pk}\n"
        f"Estado: {run.status}\n"
        f"Inicio: {started_at}\n"
        f"Fin: {finished_at}\n"
        f"Error: {exc}\n\n"
        "Posibles causas: sesion de Amazon invalida, CAPTCHA, login requerido, "
        "cambio de selectores o error de infraestructura.\n\n"
        "Traceback:\n"
        f"{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}"
    )
    return send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=False,
    )
