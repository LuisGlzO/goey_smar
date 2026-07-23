from celery import shared_task
from django.conf import settings

from .services import run_creators_api_monitor, run_monitor


@shared_task(
    name="monitor.tasks.monitor_saved_items",
    soft_time_limit=max(settings.MONITOR_TASK_TIME_LIMIT_SECONDS - 15, 1),
    time_limit=settings.MONITOR_TASK_TIME_LIMIT_SECONDS,
)
def monitor_saved_items(account_key):
    run = run_monitor(account_key)
    return run.pk


@shared_task(
    name="monitor.tasks.monitor_creators_api",
    soft_time_limit=max(settings.AMAZON_CREATORS_API_TASK_TIME_LIMIT_SECONDS - 15, 1),
    time_limit=settings.AMAZON_CREATORS_API_TASK_TIME_LIMIT_SECONDS,
)
def monitor_creators_api():
    run = run_creators_api_monitor()
    return run.pk
