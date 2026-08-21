import html

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import DiscoveryNotification, DiscoverySource
from .telegram import send_telegram_message


CHANNEL_SETTING_BY_SOURCE_TYPE = {
    DiscoverySource.SourceType.AMAZON_TOP_100: "TELEGRAM_TOP100_CHANNEL_ID",
    DiscoverySource.SourceType.AMAZON_NEWEST: "TELEGRAM_NEWEST_CHANNEL_ID",
    DiscoverySource.SourceType.AMAZON_TRACKERS: "TELEGRAM_TRACKERS_CHANNEL_ID",
    DiscoverySource.SourceType.MERCADO_LIBRE_SELLER: "TELEGRAM_MERCADOLIBRE_CHANNEL_ID",
}


def _message(payload):
    labels = {"new": "Nuevo", "reentry": "Reingreso", "price_drop": "Bajó de precio"}
    title = html.escape(str(payload.get("name") or payload.get("external_id") or "Producto"))
    source = html.escape(str(payload.get("source_name") or "Descubrimiento"))
    event = labels.get(payload.get("event_type"), payload.get("event_type", "Evento"))
    lines = [f"<b>{html.escape(event)}</b> · {source}", title]
    if payload.get("price") is not None:
        lines.append(f"Precio: ${html.escape(str(payload['price']))}")
    if payload.get("url"):
        lines.append(f'<a href="{html.escape(str(payload["url"]), quote=True)}">Ver fuente pública</a>')
    return "\n".join(lines)


def deliver_discovery_notification(notification_id):
    """Deliver one outbox row. A sent row is a no-op on repeated execution."""
    delivery_error = None
    with transaction.atomic():
        notification = (
            DiscoveryNotification.objects.select_for_update()
            .select_related("event__run__source")
            .get(pk=notification_id)
        )
        if notification.status == DiscoveryNotification.Status.SENT:
            return notification.telegram_message_id
        notification.status = DiscoveryNotification.Status.PROCESSING
        notification.delivery_started_at = timezone.now()
        notification.error = ""
        notification.save(update_fields=("status", "delivery_started_at", "error"))
        source_type = notification.event.run.source.source_type
        setting_name = CHANNEL_SETTING_BY_SOURCE_TYPE[source_type]
        chat_id = getattr(settings, setting_name)
        if not chat_id:
            raise RuntimeError(f"{setting_name} no está configurado; notificación privada no enviada.")
        if str(chat_id) == str(getattr(settings, "TELEGRAM_CHAT_ID", "")):
            raise RuntimeError(
                f"{setting_name} no puede coincidir con TELEGRAM_CHAT_ID del canal comercial."
            )
        token = settings.TELEGRAM_DISCOVERY_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError("No hay token configurado para las notificaciones de descubrimiento.")
        try:
            message_id = send_telegram_message(
                chat_id,
                _message(notification.payload),
                disable_web_page_preview=True,
                bot_token=token,
            )
        except Exception as exc:
            delivery_error = exc
            notification.status = DiscoveryNotification.Status.FAILED
            notification.failed_at = timezone.now()
            notification.error = str(exc) or exc.__class__.__name__
            notification.save(update_fields=("status", "failed_at", "error"))
        else:
            notification.status = DiscoveryNotification.Status.SENT
            notification.sent_at = timezone.now()
            notification.failed_at = None
            notification.error = ""
            notification.telegram_message_id = message_id
            notification.save(update_fields=(
                "status", "sent_at", "failed_at", "error", "telegram_message_id"
            ))
    if delivery_error:
        raise delivery_error
    return message_id
