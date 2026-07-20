import logging
import os
import signal
import sys
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from .email import send_monitor_failure_email
from .errors import is_infrastructure_error
from .models import Alert, MonitorRun, MonitorSettings, Product, ProductCheck
from .performance import MonitorPerformance
from .scraper import scrape_saved_items
from .telegram import send_monitor_failure_alert, send_product_alert

logger = logging.getLogger(__name__)
STALE_RUN_ERROR = "stale_run_recovered"
WORKER_RESTART_EXIT_CODE = 70


def recover_stale_monitor_runs(now=None):
    now = now or timezone.now()
    stale_cutoff = now - timedelta(minutes=django_settings.MONITOR_RUNNING_STALE_MINUTES)
    return (
        MonitorRun.objects.filter(status=MonitorRun.Status.RUNNING, started_at__lt=stale_cutoff)
        .update(
            status=MonitorRun.Status.FAILED,
            finished_at=now,
            error=f"{STALE_RUN_ERROR}: exceeded {django_settings.MONITOR_RUNNING_STALE_MINUTES} minutes",
        )
    )


@transaction.atomic
def start_monitor_run():
    monitor_settings, _ = MonitorSettings.objects.select_for_update().get_or_create(pk=1)
    now = timezone.now()
    recover_stale_monitor_runs(now=now)
    running_cutoff = now - timedelta(minutes=django_settings.MONITOR_RUNNING_STALE_MINUTES)
    if MonitorRun.objects.filter(status=MonitorRun.Status.RUNNING, started_at__gte=running_cutoff).exists():
        return (
            MonitorRun.objects.create(
                status=MonitorRun.Status.SKIPPED,
                finished_at=now,
                error="previous_run_still_running",
            ),
            monitor_settings,
        )
    return MonitorRun.objects.create(), monitor_settings


def send_monitor_failure_notifications(run, exc):
    cooldown_cutoff = timezone.now() - timedelta(minutes=django_settings.MONITOR_FAILURE_ALERT_COOLDOWN_MINUTES)
    recent_failure = (
        MonitorRun.objects.filter(status=MonitorRun.Status.FAILED, started_at__gte=cooldown_cutoff)
        .exclude(pk=run.pk)
        .exists()
    )
    if recent_failure:
        logger.info(
            "Se omite alerta de fallo del monitor por cooldown de %s minutos.",
            django_settings.MONITOR_FAILURE_ALERT_COOLDOWN_MINUTES,
        )
        return

    try:
        send_monitor_failure_alert(run, exc)
        return
    except Exception:
        logger.exception("No se pudo enviar la alerta de fallo del monitor por Telegram.")

    try:
        send_monitor_failure_email(run, exc)
    except Exception:
        logger.exception("No se pudo enviar el email de fallo del monitor.")


def running_inside_celery_worker():
    if os.getenv("GOEY_CELERY_WORKER_PROCESS") == "1":
        return True
    args = " ".join(sys.argv).lower()
    return "celery" in args and "worker" in args


def consecutive_infrastructure_failures(limit):
    count = 0
    runs = MonitorRun.objects.exclude(status=MonitorRun.Status.SKIPPED).order_by("-started_at", "-pk")[:limit]
    for run in runs:
        if run.status != MonitorRun.Status.FAILED or not is_infrastructure_error(run.error):
            break
        count += 1
    return count


def request_worker_restart_after_infrastructure_failures():
    threshold = django_settings.MONITOR_INFRASTRUCTURE_FAILURE_RESTART_THRESHOLD
    if not django_settings.MONITOR_AUTO_RESTART_WORKER_ON_INFRA_FAILURE or threshold <= 0:
        return
    failures = consecutive_infrastructure_failures(threshold)
    if failures < threshold:
        return

    logger.error(
        "Se detectaron %s fallos consecutivos de infraestructura. Se solicita reinicio del worker.",
        failures,
    )
    if not running_inside_celery_worker():
        logger.error("No se reinicia automaticamente porque el proceso actual no parece ser un Celery worker.")
        return

    parent_pid = os.getppid()
    if parent_pid > 1:
        os.kill(parent_pid, signal.SIGTERM)
    os._exit(WORKER_RESTART_EXIT_CODE)


def determine_availability(item):
    if item.move_to_cart_visible:
        return ProductCheck.Availability.AVAILABLE
    if item.unavailable_message_visible:
        return ProductCheck.Availability.UNAVAILABLE
    return ProductCheck.Availability.UNKNOWN


def monitor_pause_reason(settings, now=None):
    now = timezone.localtime(now or timezone.now())
    if settings.is_active_at(now.time()):
        return ""
    if not settings.enabled:
        return "monitor_disabled"
    if settings.active_from and settings.active_until:
        return f"outside_active_window:{settings.active_from.strftime('%H:%M')}-{settings.active_until.strftime('%H:%M')}"
    return "outside_active_window"


def anti_false_restock_cooldown_active(sent_alerts, monitor_settings, now):
    cooldown_minutes = monitor_settings.anti_false_restock_cooldown_minutes if monitor_settings else 0
    if cooldown_minutes <= 0:
        return False
    return sent_alerts.filter(created_at__gte=now - timedelta(minutes=cooldown_minutes)).exists()


def alert_decision(product, check, now=None, monitor_settings=None):
    now = now or timezone.now()
    monitor_settings = monitor_settings or MonitorSettings.load()
    if not check.move_to_cart_visible:
        return False, "move_to_cart_missing"
    if check.availability != ProductCheck.Availability.AVAILABLE:
        return False, "not_available"
    if check.price is None:
        return False, "price_missing"
    if check.price > product.max_price:
        return False, "price_above_target"

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sent_alerts = Alert.objects.filter(product=product, status=Alert.Status.SENT)
    if anti_false_restock_cooldown_active(sent_alerts, monitor_settings, now):
        return False, "anti_false_restock_cooldown"

    if sent_alerts.filter(created_at__gte=start_of_day).count() >= product.max_alerts_per_day:
        return False, "daily_limit"

    previous = ProductCheck.objects.filter(product=product, checked_at__lt=check.checked_at).first()
    last_sent = sent_alerts.first()
    if not last_sent:
        return True, "first_availability"
    if previous and previous.availability != ProductCheck.Availability.AVAILABLE:
        return True, "restock"

    previous_sent_price = last_sent.product_check.price
    if previous_sent_price and check.price < previous_sent_price:
        drop = ((previous_sent_price - check.price) / previous_sent_price) * Decimal("100")
        if drop >= product.significant_price_drop_percent:
            return True, "significant_price_drop"

    if now - last_sent.created_at >= timedelta(minutes=product.cooldown_minutes):
        return True, "cooldown_elapsed"
    return False, "cooldown"


@transaction.atomic
def process_item(run, product, item, monitor_settings=None, timing=None):
    check = ProductCheck.objects.create(
        run=run,
        product=product,
        availability=determine_availability(item),
        price=item.price,
        move_to_cart_visible=item.move_to_cart_visible,
        unavailable_message_visible=item.unavailable_message_visible,
        product_url=item.product_url,
        raw_text=item.raw_text,
    )
    with timing.stage("alert_decision", group="alerts", asin=product.asin) if timing else _nullcontext():
        should_send, reason = alert_decision(product, check, monitor_settings=monitor_settings)
    if not should_send:
        Alert.objects.create(product=product, product_check=check, status=Alert.Status.SKIPPED, reason=reason)
        return check
    try:
        message_id = send_product_alert(product, check, timing=timing)
        Alert.objects.create(product=product, product_check=check, status=Alert.Status.SENT, reason=reason, details=message_id)
    except Exception as exc:
        Alert.objects.create(product=product, product_check=check, status=Alert.Status.FAILED, reason="telegram_error", details=str(exc))
    return check


def process_missing_product(run, product):
    check = ProductCheck.objects.create(
        run=run,
        product=product,
        availability=ProductCheck.Availability.UNKNOWN,
        raw_text="El ASIN activo no apareció entre los elementos visibles.",
    )
    Alert.objects.create(product=product, product_check=check, status=Alert.Status.SKIPPED, reason="not_visible")


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False


def run_monitor():
    timing = MonitorPerformance()
    run, settings = start_monitor_run()
    if run.status == MonitorRun.Status.SKIPPED and run.error == "previous_run_still_running":
        run.performance = timing.finish()
        run.save(update_fields=("performance",))
        return run
    try:
        with timing.stage("pause_check"):
            pause_reason = monitor_pause_reason(settings)
        if pause_reason:
            run.status = MonitorRun.Status.SKIPPED
            run.error = pause_reason
            return run

        with timing.stage("scrape_saved_items"):
            items = scrape_saved_items(timing=timing)
        with timing.stage("load_active_products"):
            products = {product.asin: product for product in Product.objects.filter(is_active=True)}
        with timing.stage("process_visible_items", item_count=len(items)):
            for item in items:
                product = products.pop(item.asin, None)
                if product:
                    process_item(run, product, item, settings, timing=timing)
        with timing.stage("process_missing_products", product_count=len(products)):
            for product in products.values():
                process_missing_product(run, product)
        run.items_seen = len(items)
        run.status = MonitorRun.Status.SUCCESS
    except Exception as exc:
        run.status = MonitorRun.Status.FAILED
        run.error = str(exc)
        run.finished_at = timezone.now()
        run.performance = timing.finish()
        run.save(update_fields=("items_seen", "status", "error", "finished_at", "performance"))
        send_monitor_failure_notifications(run, exc)
        if is_infrastructure_error(exc):
            request_worker_restart_after_infrastructure_failures()
        raise
    finally:
        if run.finished_at is None:
            run.finished_at = timezone.now()
            run.performance = timing.finish()
            run.save(update_fields=("items_seen", "status", "error", "finished_at", "performance"))
    return run
