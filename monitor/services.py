import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from .email import send_monitor_failure_email
from .models import Alert, MonitorRun, MonitorSettings, Product, ProductCheck
from .scraper import scrape_saved_items
from .telegram import send_monitor_failure_alert, send_product_alert

logger = logging.getLogger(__name__)


@transaction.atomic
def start_monitor_run():
    monitor_settings, _ = MonitorSettings.objects.select_for_update().get_or_create(pk=1)
    stale_cutoff = timezone.now() - timedelta(minutes=django_settings.MONITOR_RUNNING_STALE_MINUTES)
    if MonitorRun.objects.filter(status=MonitorRun.Status.RUNNING, started_at__gte=stale_cutoff).exists():
        return (
            MonitorRun.objects.create(
                status=MonitorRun.Status.SKIPPED,
                finished_at=timezone.now(),
                error="previous_run_still_running",
            ),
            monitor_settings,
        )
    return MonitorRun.objects.create(), monitor_settings


def send_monitor_failure_notifications(run, exc):
    email_sent = False
    try:
        email_sent = send_monitor_failure_email(run, exc) > 0
    except Exception:
        logger.exception("No se pudo enviar el email de fallo del monitor.")

    if email_sent:
        return

    try:
        send_monitor_failure_alert(run, exc)
    except Exception:
        logger.exception("No se pudo enviar la alerta de fallo del monitor por Telegram.")


def determine_availability(item):
    if item.move_to_cart_visible or item.price is not None:
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


def alert_decision(product, check, now=None):
    now = now or timezone.now()
    if check.availability != ProductCheck.Availability.AVAILABLE:
        return False, "not_available"
    if check.price is None:
        return False, "price_missing"
    if check.price > product.max_price:
        return False, "price_above_target"

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sent_alerts = Alert.objects.filter(product=product, status=Alert.Status.SENT)
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
def process_item(run, product, item):
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
    should_send, reason = alert_decision(product, check)
    if not should_send:
        Alert.objects.create(product=product, product_check=check, status=Alert.Status.SKIPPED, reason=reason)
        return check
    try:
        message_id = send_product_alert(product, check)
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


def run_monitor():
    run, settings = start_monitor_run()
    if run.status == MonitorRun.Status.SKIPPED and run.error == "previous_run_still_running":
        return run
    try:
        pause_reason = monitor_pause_reason(settings)
        if pause_reason:
            run.status = MonitorRun.Status.SKIPPED
            run.error = pause_reason
            return run

        items = scrape_saved_items()
        products = {product.asin: product for product in Product.objects.filter(is_active=True)}
        for item in items:
            product = products.pop(item.asin, None)
            if product:
                process_item(run, product, item)
        for product in products.values():
            process_missing_product(run, product)
        run.items_seen = len(items)
        run.status = MonitorRun.Status.SUCCESS
    except Exception as exc:
        run.status = MonitorRun.Status.FAILED
        run.error = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=("items_seen", "status", "error", "finished_at"))
        send_monitor_failure_notifications(run, exc)
        raise
    finally:
        if run.finished_at is None:
            run.finished_at = timezone.now()
            run.save(update_fields=("items_seen", "status", "error", "finished_at"))
    return run
