from celery import shared_task

from .services import run_monitor


@shared_task(name="monitor.tasks.monitor_saved_items")
def monitor_saved_items():
    run = run_monitor()
    return run.pk

