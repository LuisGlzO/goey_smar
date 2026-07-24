import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from .email import send_monitor_failure_email
from .amazon_creators import creators_api_is_configured, get_products_content
from .errors import is_infrastructure_error
from .models import (
    Alert, CartSnapshotItem, MonitorRun, MonitorSettings, ObservationSource,
    Product, ProductCheck, ScraperAccount,
)
from .performance import MonitorPerformance
from .telegram import send_monitor_failure_alert, send_product_alert

logger = logging.getLogger(__name__)
STALE_RUN_ERROR = "stale_run_recovered"
WORKER_RESTART_EXIT_CODE = 70
MAX_STEPPED_COOLDOWN_MINUTES = 360
COOLDOWN_RESET_REASONS = {
    "first_availability",
    "restock",
    "significant_price_drop",
}


@dataclass
class ObservedItem:
    asin: str
    price: Decimal | None
    move_to_cart_visible: bool
    unavailable_message_visible: bool
    product_url: str
    raw_text: str
    creator_content: object | None = None


def scrape_saved_items(*args, **kwargs):
    # Playwright se carga únicamente dentro del worker del scraper; el panel web
    # y el monitor API no dependen de su runtime binario.
    from .scraper import scrape_saved_items as run_scraper
    return run_scraper(*args, **kwargs)


def recover_stale_monitor_runs(now=None, worker_key=None):
    now = now or timezone.now()
    stale_cutoff = now - timedelta(minutes=django_settings.MONITOR_RUNNING_STALE_MINUTES)
    queryset = MonitorRun.objects.filter(status=MonitorRun.Status.RUNNING, started_at__lt=stale_cutoff)
    if worker_key:
        queryset = queryset.filter(worker_key=worker_key)
    return (
        queryset
        .update(
            status=MonitorRun.Status.FAILED,
            finished_at=now,
            error=f"{STALE_RUN_ERROR}: exceeded {django_settings.MONITOR_RUNNING_STALE_MINUTES} minutes",
        )
    )


@transaction.atomic
def start_monitor_run(source, worker_key):
    monitor_settings, _ = MonitorSettings.objects.select_for_update().get_or_create(pk=1)
    now = timezone.now()
    recover_stale_monitor_runs(now=now, worker_key=worker_key)
    running_cutoff = now - timedelta(minutes=django_settings.MONITOR_RUNNING_STALE_MINUTES)
    if MonitorRun.objects.filter(
        status=MonitorRun.Status.RUNNING, started_at__gte=running_cutoff, worker_key=worker_key
    ).exists():
        return (
            MonitorRun.objects.create(
                status=MonitorRun.Status.SKIPPED,
                finished_at=now,
                error="previous_run_still_running",
                source=source,
                worker_key=worker_key,
            ),
            monitor_settings,
        )
    return MonitorRun.objects.create(source=source, worker_key=worker_key), monitor_settings


def send_monitor_failure_notifications(run, exc):
    cooldown_cutoff = timezone.now() - timedelta(minutes=django_settings.MONITOR_FAILURE_ALERT_COOLDOWN_MINUTES)
    recent_failure = (
        MonitorRun.objects.filter(
            status=MonitorRun.Status.FAILED,
            started_at__gte=cooldown_cutoff,
            worker_key=run.worker_key,
        )
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


def consecutive_infrastructure_failures(limit, worker_key):
    count = 0
    runs = (
        MonitorRun.objects.filter(worker_key=worker_key)
        .exclude(status=MonitorRun.Status.SKIPPED)
        .order_by("-started_at", "-pk")[:limit]
    )
    for run in runs:
        if run.status != MonitorRun.Status.FAILED or not is_infrastructure_error(run.error):
            break
        count += 1
    return count


def request_worker_restart_after_infrastructure_failures(worker_key):
    threshold = django_settings.MONITOR_INFRASTRUCTURE_FAILURE_RESTART_THRESHOLD
    if not django_settings.MONITOR_AUTO_RESTART_WORKER_ON_INFRA_FAILURE or threshold <= 0:
        return
    failures = consecutive_infrastructure_failures(threshold, worker_key)
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


def effective_cooldown_minutes(product):
    """Return the current cooldown without mutating the product's configured base."""
    effective = product.cooldown_minutes
    maximum = max(product.cooldown_minutes, MAX_STEPPED_COOLDOWN_MINUTES)
    automatic_reasons = (
        Alert.objects.filter(product=product, status=Alert.Status.SENT)
        .exclude(source=ObservationSource.MANUAL)
        .order_by("-created_at", "-pk")
        .values_list("reason", flat=True)
    )
    for reason in automatic_reasons:
        if reason == "cooldown_elapsed":
            effective = min(effective * 2, maximum)
            continue
        # Reset reasons and unknown historical reasons both end the current
        # consecutive cooldown-elapsed streak at the configured base.
        if reason in COOLDOWN_RESET_REASONS:
            break
        break
    return effective


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

    previous = None
    if check.source == ObservationSource.SCRAPER:
        previous = ProductCheck.objects.filter(
            product=product,
            source=ObservationSource.SCRAPER,
            checked_at__lt=check.checked_at,
        ).first()
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

    if now - last_sent.created_at >= timedelta(minutes=effective_cooldown_minutes(product)):
        return True, "cooldown_elapsed"
    return False, "cooldown"


def manual_alert_decision(product, now=None, monitor_settings=None):
    now = now or timezone.now()
    monitor_settings = monitor_settings or MonitorSettings.load()
    if not product.is_active:
        return False, "product_inactive"
    sent_alerts = Alert.objects.filter(product=product, status=Alert.Status.SENT)
    if anti_false_restock_cooldown_active(sent_alerts, monitor_settings, now):
        return False, "anti_false_restock_cooldown"
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if sent_alerts.filter(created_at__gte=start_of_day).count() >= product.max_alerts_per_day:
        return False, "daily_limit"
    last_sent = sent_alerts.first()
    if last_sent and now - last_sent.created_at < timedelta(minutes=effective_cooldown_minutes(product)):
        return False, "cooldown"
    return True, "manual_request"


def _reserve_alert(product, check, source, requested_by=None, monitor_settings=None):
    now = timezone.now()
    reservation_seconds = getattr(django_settings, "ALERT_RESERVATION_SECONDS", 90)
    with transaction.atomic():
        product = Product.objects.select_for_update().get(pk=product.pk)
        Alert.objects.filter(
            product=product,
            status=Alert.Status.PROCESSING,
            reservation_expires_at__lte=now,
        ).update(status=Alert.Status.FAILED, reason="reservation_expired", details="La reserva de envio expiro.")
        if Alert.objects.filter(
            product=product,
            status=Alert.Status.PROCESSING,
            reservation_expires_at__gt=now,
        ).exists():
            return Alert.objects.create(
                product=product, product_check=check, source=source, requested_by=requested_by,
                status=Alert.Status.SKIPPED, reason="alert_in_progress",
            )
        if source == ObservationSource.MANUAL:
            should_send, reason = manual_alert_decision(product, now=now, monitor_settings=monitor_settings)
        else:
            should_send, reason = alert_decision(product, check, now=now, monitor_settings=monitor_settings)
        if not should_send:
            return Alert.objects.create(
                product=product, product_check=check, source=source, requested_by=requested_by,
                status=Alert.Status.SKIPPED, reason=reason,
            )
        return Alert.objects.create(
            product=product, product_check=check, source=source, requested_by=requested_by,
            status=Alert.Status.PROCESSING, reason=reason,
            reservation_expires_at=now + timedelta(seconds=reservation_seconds),
        )


def request_product_alert(
    product, check, source, requested_by=None, monitor_settings=None, timing=None, creator_content=None
):
    alert = _reserve_alert(product, check, source, requested_by=requested_by, monitor_settings=monitor_settings)
    if alert.status != Alert.Status.PROCESSING:
        return alert
    try:
        message_id = send_product_alert(product, check, timing=timing, creator_content=creator_content)
        alert.status = Alert.Status.SENT
        alert.details = message_id
    except Exception as exc:
        alert.status = Alert.Status.FAILED
        alert.reason = "telegram_error"
        alert.details = str(exc)
    alert.reservation_expires_at = None
    alert.save(update_fields=("status", "reason", "details", "reservation_expires_at"))
    return alert


def process_item(run, product, item, monitor_settings=None, timing=None):
    check = ProductCheck.objects.create(
        run=run,
        product=product,
        source=run.source,
        availability=determine_availability(item),
        price=item.price,
        move_to_cart_visible=item.move_to_cart_visible,
        unavailable_message_visible=item.unavailable_message_visible,
        product_url=item.product_url,
        raw_text=item.raw_text,
    )
    with timing.stage("alert_decision", group="alerts", asin=product.asin) if timing else _nullcontext():
        request_product_alert(
            product, check, run.source, monitor_settings=monitor_settings, timing=timing,
            creator_content=getattr(item, "creator_content", None),
        )
    return check


def process_missing_product(run, product):
    check = ProductCheck.objects.create(
        run=run,
        product=product,
        source=run.source,
        availability=ProductCheck.Availability.UNKNOWN,
        raw_text="El ASIN activo no apareció entre los elementos visibles.",
    )
    Alert.objects.create(
        product=product, product_check=check, source=run.source,
        status=Alert.Status.SKIPPED, reason="not_visible"
    )


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False


def scraper_profile_dir(account_key):
    if not ScraperAccount.objects.filter(pk=account_key).exists():
        raise ValueError(f"Cuenta scraper desconocida: {account_key}")
    configured_worker = django_settings.AMAZON_SCRAPER_ACCOUNT
    if configured_worker and configured_worker != account_key:
        raise RuntimeError(
            f"El worker de {configured_worker} rechazo una tarea destinada a {account_key}."
        )
    try:
        return django_settings.AMAZON_PROFILE_DIRS[account_key]
    except KeyError as exc:
        raise ValueError(f"No hay un perfil configurado para {account_key}.") from exc


def run_monitor(account_key):
    profile_dir = scraper_profile_dir(account_key)
    timing = MonitorPerformance()
    worker_key = f"scraper:{account_key}"
    run, settings = start_monitor_run(ObservationSource.SCRAPER, worker_key)
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
            items = scrape_saved_items(
                account_key=account_key,
                profile_dir=profile_dir,
                timing=timing,
            )
        with timing.stage("store_cart_snapshot", item_count=len(items)):
            CartSnapshotItem.objects.bulk_create([
                CartSnapshotItem(
                    run=run,
                    scraper_account_id=account_key,
                    asin=item.asin,
                    source=item.source,
                    price=item.price,
                    product_url=item.product_url,
                    raw_text=item.raw_text,
                )
                for item in items
            ])
        with timing.stage("load_active_products"):
            products = {
                product.asin: product
                for product in Product.objects.filter(is_active=True, scraper_account_id=account_key)
            }
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
            request_worker_restart_after_infrastructure_failures(worker_key)
        raise
    finally:
        if run.finished_at is None:
            run.finished_at = timezone.now()
            run.performance = timing.finish()
            run.save(update_fields=("items_seen", "status", "error", "finished_at", "performance"))
    return run


def _chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _fetch_creator_batch(asins):
    attempts = max(getattr(django_settings, "AMAZON_CREATORS_API_MAX_ATTEMPTS", 2), 1)
    for attempt in range(1, attempts + 1):
        try:
            return get_products_content(asins)
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(getattr(django_settings, "AMAZON_CREATORS_API_RETRY_DELAY_SECONDS", 1))


def run_creators_api_monitor():
    timing = MonitorPerformance()
    run, settings = start_monitor_run(ObservationSource.CREATORS_API, "creators_api:default")
    if run.status == MonitorRun.Status.SKIPPED and run.error == "previous_run_still_running":
        run.performance = timing.finish()
        run.save(update_fields=("performance",))
        return run
    try:
        pause_reason = monitor_pause_reason(settings)
        if pause_reason:
            run.status = MonitorRun.Status.SKIPPED
            run.error = pause_reason
            return run
        if not creators_api_is_configured():
            raise RuntimeError("Creators API no esta configurada.")

        products = list(Product.objects.filter(is_active=True))
        batch_size = min(max(getattr(django_settings, "AMAZON_CREATORS_API_BATCH_SIZE", 10), 1), 10)
        failures = []
        batches = list(_chunks(products, batch_size))
        for batch_index, batch in enumerate(batches):
            asins = [product.asin for product in batch]
            try:
                with timing.stage("creators_api_batch", asin_count=len(asins)):
                    content_by_asin = _fetch_creator_batch(asins)
            except Exception as exc:
                failures.append(str(exc))
                content_by_asin = {}
            for product in batch:
                content = content_by_asin.get(product.asin)
                if content is None:
                    check = ProductCheck.objects.create(
                        run=run, product=product, source=ObservationSource.CREATORS_API,
                        availability=ProductCheck.Availability.UNKNOWN,
                        raw_text="Creators API no devolvio datos para este ASIN.",
                    )
                    Alert.objects.create(
                        product=product, product_check=check, source=ObservationSource.CREATORS_API,
                        status=Alert.Status.SKIPPED, reason="api_data_missing",
                    )
                    continue
                Product.objects.filter(pk=product.pk).update(
                    image_url=content.image_url,
                    image_refreshed_at=timezone.now(),
                )
                item = ObservedItem(
                    asin=product.asin,
                    price=content.price,
                    move_to_cart_visible=content.available is True,
                    unavailable_message_visible=content.available is False,
                    product_url=content.detail_page_url,
                    raw_text=f"Creators API primary offer available={content.available} price={content.price}",
                    creator_content=content,
                )
                process_item(run, product, item, settings, timing=timing)
            delay = getattr(django_settings, "AMAZON_CREATORS_API_BATCH_DELAY_SECONDS", 0)
            if delay and batch_index < len(batches) - 1:
                time.sleep(delay)
        run.items_seen = len(products)
        if failures and len(failures) == len(batches):
            raise RuntimeError(f"Fallaron todos los lotes de Creators API: {failures[0]}")
        run.status = MonitorRun.Status.SUCCESS
        if failures:
            run.error = f"partial_batch_failures:{len(failures)}"
    except Exception as exc:
        run.status = MonitorRun.Status.FAILED
        run.error = str(exc)
        run.finished_at = timezone.now()
        run.performance = timing.finish()
        run.save(update_fields=("items_seen", "status", "error", "finished_at", "performance"))
        send_monitor_failure_notifications(run, exc)
        raise
    finally:
        if run.finished_at is None:
            run.finished_at = timezone.now()
            run.performance = timing.finish()
            run.save(update_fields=("items_seen", "status", "error", "finished_at", "performance"))
    return run
