from datetime import timedelta
import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .discovery import _finish_failed_run, _start_discovery_run, process_discovery_review
from .discovery_collectors import collect_discovery_source
from .discovery_notifications import deliver_discovery_notification
from .models import DiscoveryEvent, DiscoveryNotification, DiscoveryRun, DiscoverySource
from .services import run_creators_api_monitor, run_monitor

logger = logging.getLogger(__name__)


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


@shared_task(name="monitor.tasks.dispatch_due_discovery_sources")
def dispatch_due_discovery_sources():
    """Reserve due sources first, then publish one independent task per source."""
    now = timezone.now()
    with transaction.atomic():
        candidates = list(
            DiscoverySource.objects.select_for_update(skip_locked=True)
            .filter(is_active=True)
            .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
            .exclude(runs__status=DiscoveryRun.Status.RUNNING)
            .order_by("next_run_at", "pk")[: settings.DISCOVERY_DISPATCH_BATCH_SIZE]
        )
        for source in candidates:
            source.dispatch_reserved_at = now
            source.next_run_at = now + timedelta(minutes=source.interval_minutes)
            source.save(update_fields=("dispatch_reserved_at", "next_run_at", "updated_at"))

    published = 0
    for index, source in enumerate(candidates):
        try:
            run_discovery_source.apply_async(
                args=(source.pk,),
                queue=settings.DISCOVERY_QUEUE,
                countdown=index * settings.DISCOVERY_STAGGER_SECONDS,
                expires=settings.DISCOVERY_TASK_EXPIRES_SECONDS,
            )
            published += 1
        except Exception as exc:
            DiscoveryRun.objects.create(
                source=source,
                status=DiscoveryRun.Status.FAILED,
                finished_at=timezone.now(),
                error=f"dispatch_failed: {str(exc) or exc.__class__.__name__}",
            )
            DiscoverySource.objects.filter(pk=source.pk).update(next_run_at=now)
    return published


@shared_task(
    bind=True,
    name="monitor.tasks.run_discovery_source",
    max_retries=2,
    soft_time_limit=285,
    time_limit=300,
)
def run_discovery_source(self, source_id, diagnostic=False):
    run = _start_discovery_run(source_id, allow_inactive=diagnostic)
    if run.status == DiscoveryRun.Status.SKIPPED:
        return run.pk
    source = run.source
    try:
        review = collect_discovery_source(source)
        items = review["items"]
        if diagnostic:
            now = timezone.now()
            DiscoveryRun.objects.filter(pk=run.pk).update(
                status=(DiscoveryRun.Status.SUCCESS if review.get("is_complete", True)
                        else DiscoveryRun.Status.INCOMPLETE),
                finished_at=now,
                pages_found=review.get("pages_found", 0),
                products_found=len(items),
                is_diagnostic=True,
                issues=review.get("issues", []),
            )
            logger.info(
                "discovery_diagnostic_complete source_id=%s run_id=%s products=%s complete=%s",
                source_id, run.pk, len(items), review.get("is_complete", True),
            )
            return run.pk
        run = process_discovery_review(
            source,
            items,
            pages_found=review.get("pages_found", 0),
            is_complete=review.get("is_complete", True),
            run=run,
        )
    except Exception as exc:
        if DiscoveryRun.objects.filter(pk=run.pk, status=DiscoveryRun.Status.RUNNING).exists():
            _finish_failed_run(run, exc)
        if isinstance(exc, NotImplementedError):
            raise
        raise self.retry(exc=exc, countdown=settings.DISCOVERY_RETRY_DELAY_SECONDS)

    for notification_id in run.events.filter(notification__status="pending").values_list(
        "notification__pk", flat=True
    ):
        send_discovery_notification.apply_async(
            args=(notification_id,),
            queue=settings.DISCOVERY_NOTIFICATIONS_QUEUE,
            expires=settings.DISCOVERY_NOTIFICATION_EXPIRES_SECONDS,
        )
    logger.info(
        "discovery_run_complete source_id=%s run_id=%s status=%s products=%s events=%s notifications=%s",
        source_id, run.pk, run.status, run.products_found, run.events_created,
        run.notifications_created,
    )
    return run.pk


@shared_task(bind=True, name="monitor.tasks.send_discovery_notification", max_retries=3)
def send_discovery_notification(self, notification_id):
    try:
        return deliver_discovery_notification(notification_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=settings.DISCOVERY_RETRY_DELAY_SECONDS)


@shared_task(name="monitor.tasks.cleanup_discovery_history")
def cleanup_discovery_history():
    """Apply the discovery-only retention policy without touching commercial tables."""
    cutoff = timezone.now() - timedelta(days=settings.DISCOVERY_RETENTION_DAYS)
    old_runs = DiscoveryRun.objects.filter(started_at__lt=cutoff).exclude(
        status=DiscoveryRun.Status.RUNNING
    )
    run_ids = list(old_runs.order_by("pk").values_list("pk", flat=True)[:settings.DISCOVERY_RETENTION_BATCH_SIZE])
    events = DiscoveryEvent.objects.filter(run_id__in=run_ids).count()
    notifications = DiscoveryNotification.objects.filter(event__run_id__in=run_ids).count()
    deleted_runs = len(run_ids)
    if run_ids:
        DiscoveryRun.objects.filter(pk__in=run_ids).delete()
    logger.info(
        "discovery_cleanup_complete cutoff=%s runs=%s events=%s notifications=%s",
        cutoff.isoformat(), deleted_runs, events, notifications,
    )
    return {"runs": deleted_runs, "events": events, "notifications": notifications}
