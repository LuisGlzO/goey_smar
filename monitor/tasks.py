from celery import shared_task
from django.conf import settings

from .services import run_monitor


@shared_task(
    name="monitor.tasks.monitor_saved_items",
    soft_time_limit=max(settings.MONITOR_TASK_TIME_LIMIT_SECONDS - 15, 1),
    time_limit=settings.MONITOR_TASK_TIME_LIMIT_SECONDS,
)
def monitor_saved_items():
    run = run_monitor()
    return run.pk
