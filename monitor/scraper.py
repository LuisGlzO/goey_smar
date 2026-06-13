import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from django.conf import settings
from playwright.sync_api import sync_playwright

ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)
PRICE_RE = re.compile(r"(?:MXN\s*|\$\s*)([\d.,]+)", re.IGNORECASE)
UNAVAILABLE_TERMS = (
    "no disponible",
    "sin stock",
    "agotado",
    "oferta seleccionada ya no está disponible",
    "currently unavailable",
    "out of stock",
)
MOVE_TO_CART_TERMS = ("mover al carrito", "move to cart")


@dataclass(frozen=True)
class ScrapedItem:
    asin: str
    price: Decimal | None
    move_to_cart_visible: bool
    unavailable_message_visible: bool
    product_url: str
    raw_text: str


def extract_asin(href: str, data_asin: str = "") -> str | None:
    candidate = data_asin.strip().upper()
    if re.fullmatch(r"[A-Z0-9]{10}", candidate):
        return candidate
    match = ASIN_RE.search(href)
    return match.group(1).upper() if match else None


def parse_price(text: str) -> Decimal | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    value = match.group(1)
    if "," in value and "." in value:
        value = value.replace(",", "")
    elif value.count(",") == 1 and len(value.rsplit(",", 1)[1]) == 2:
        value = value.replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def item_from_payload(payload: dict) -> ScrapedItem | None:
    href = payload.get("href") or ""
    asin = extract_asin(href, payload.get("asin") or "")
    if not asin:
        return None
    text = " ".join((payload.get("text") or "").split())
    lowered = text.lower()
    return ScrapedItem(
        asin=asin,
        price=parse_price(text),
        move_to_cart_visible=any(term in lowered for term in MOVE_TO_CART_TERMS),
        unavailable_message_visible=any(term in lowered for term in UNAVAILABLE_TERMS),
        product_url=urljoin("https://www.amazon.com.mx", href) if href else f"https://www.amazon.com.mx/dp/{asin}",
        raw_text=text[:4000],
    )


def scrape_saved_items(headless: bool | None = None) -> list[ScrapedItem]:
    headless = settings.AMAZON_HEADLESS if headless is None else headless
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            settings.AMAZON_PROFILE_DIR,
            headless=headless,
            locale="es-MX",
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(settings.AMAZON_SAVED_ITEMS_URL, wait_until="domcontentloaded", timeout=settings.AMAZON_TIMEOUT_MS)
            page.wait_for_timeout(3000)
            account_label = page.locator("#nav-link-accountList-nav-line-1")
            account_text = account_label.first.inner_text().lower() if account_label.count() else ""
            if (
                "signin" in page.url.lower()
                or page.locator("#ap_email").count()
                or "identifícate" in account_text
                or "sign in" in account_text
            ):
                raise RuntimeError("La sesión de Amazon no es válida; ejecute init_amazon_session.")
            saved_items = page.locator("#sc-saved-cart [data-asin]")
            payloads = saved_items.evaluate_all(
                """elements => elements.map(element => {
                    const link = element.querySelector('a[href*="/dp/"], a[href*="/gp/product/"]');
                    return {
                        asin: element.getAttribute("data-asin") || "",
                        href: link ? link.getAttribute("href") : "",
                        text: element.innerText || ""
                    };
                })"""
            )
            by_asin = {}
            for payload in payloads:
                item = item_from_payload(payload)
                if item and (item.asin not in by_asin or len(item.raw_text) > len(by_asin[item.asin].raw_text)):
                    by_asin[item.asin] = item
            return list(by_asin.values())
        finally:
            context.close()
