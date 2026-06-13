import html

import requests
from django.conf import settings

from .links import affiliate_url_for


def send_product_alert(product, check) -> str:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID son obligatorios.")
    product_url = affiliate_url_for(product, check.product_url)
    text = (
        f"<b>Restock detectado</b>\n"
        f"{html.escape(product.name)}\n"
        f"Precio: <b>${check.price:,.2f} MXN</b>\n"
        f"ASIN: <code>{product.asin}</code>\n"
        f'<a href="{html.escape(product_url)}">Ver producto</a>'
    )
    response = requests.post(
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    response.raise_for_status()
    return str(response.json().get("result", {}).get("message_id", ""))
