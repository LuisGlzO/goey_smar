import html
import traceback

import requests
from django.conf import settings
from django.utils import timezone

from .amazon_creators import safe_get_product_content
from .links import affiliate_url_for


def send_telegram_message(chat_id: str, text: str, disable_web_page_preview: bool = False) -> str:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN es obligatorio.")
    if not chat_id:
        raise RuntimeError("El chat de Telegram es obligatorio.")
    response = requests.post(
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview,
        },
        timeout=15,
    )
    response.raise_for_status()
    return str(response.json().get("result", {}).get("message_id", ""))


def send_telegram_photo(chat_id: str, photo_url: str, caption: str) -> str:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN es obligatorio.")
    if not chat_id:
        raise RuntimeError("El chat de Telegram es obligatorio.")
    image_response = requests.get(photo_url, stream=True, timeout=30)
    image_response.raise_for_status()
    response = requests.post(
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendPhoto",
        data={
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
        },
        files={"photo": image_response.raw},
        timeout=15,
    )
    response.raise_for_status()
    return str(response.json().get("result", {}).get("message_id", ""))


def send_product_alert(product, check) -> str:
    if not settings.TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID es obligatorio.")
    creator_content = safe_get_product_content(product.asin)
    product_name = creator_content.title if creator_content and creator_content.title else product.name
    product_url = (
        product.affiliate_url
        or (creator_content.detail_page_url if creator_content and creator_content.detail_page_url else "")
        or affiliate_url_for(product, check.product_url)
    )
    text = (
        f"🚨🚨🚨 alerta de {html.escape(product_name)}\n\n"
        f"{html.escape(product_url)}"
    )
    if creator_content and creator_content.image_url:
        return send_telegram_photo(settings.TELEGRAM_CHAT_ID, creator_content.image_url, text)
    return send_telegram_message(settings.TELEGRAM_CHAT_ID, text)


def send_monitor_failure_alert(run, exc: Exception) -> str:
    if not settings.TELEGRAM_ERROR_CHAT_ID:
        raise RuntimeError("TELEGRAM_ERROR_CHAT_ID es obligatorio para alertas de errores.")

    started_at = timezone.localtime(run.started_at).strftime("%Y-%m-%d %H:%M:%S %Z")
    finished_at = timezone.localtime(run.finished_at or timezone.now()).strftime("%Y-%m-%d %H:%M:%S %Z")
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(trace) > 1800:
        trace = f"{trace[:1800]}\n... traceback truncado ..."

    text = (
        "<b>Scraper fallido</b>\n"
        f"Run ID: <code>{run.pk}</code>\n"
        f"Estado: <code>{html.escape(run.status)}</code>\n"
        f"Inicio: <code>{html.escape(started_at)}</code>\n"
        f"Fin: <code>{html.escape(finished_at)}</code>\n"
        f"Error: <code>{html.escape(str(exc))}</code>\n\n"
        "Posibles causas: sesion invalida, CAPTCHA, login requerido, selectores o infraestructura.\n\n"
        f"<pre>{html.escape(trace)}</pre>"
    )
    return send_telegram_message(settings.TELEGRAM_ERROR_CHAT_ID, text, disable_web_page_preview=True)
