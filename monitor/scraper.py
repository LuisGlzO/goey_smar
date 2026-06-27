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
    "no está disponible",
    "sin stock",
    "agotado",
    "oferta seleccionada ya no está disponible",
    "currently unavailable",
    "out of stock",
)
MOVE_TO_CART_TERMS = ("mover al carrito", "move to cart")

ITEM_PAYLOADS_JS = """root => {
    const candidates = new Set();
    root.querySelectorAll("[data-asin]").forEach(element => candidates.add(element));
    root.querySelectorAll('a[href*="/dp/"], a[href*="/gp/product/"]').forEach(link => {
        candidates.add(link.closest("[data-asin]") || link.closest(".sc-list-item") || link.closest("li") || link.parentElement);
    });
    return Array.from(candidates).map(element => {
        const link = element.querySelector('a[href*="/dp/"], a[href*="/gp/product/"]');
        return {
            asin: element.getAttribute("data-asin") || "",
            href: link ? link.getAttribute("href") : "",
            text: element.innerText || ""
        };
    });
}"""


@dataclass(frozen=True)
class ScrapedItem:
    asin: str
    price: Decimal | None
    move_to_cart_visible: bool
    unavailable_message_visible: bool
    product_url: str
    raw_text: str
    source: str = "unknown"


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
        source=payload.get("source") or "unknown",
    )


def collect_item_payloads(page, selector: str, source: str, scroll: bool = False) -> list[dict]:
    section = page.locator(selector)
    if not section.count():
        return []
    section.wait_for(state="attached", timeout=10000)
    section.scroll_into_view_if_needed()
    page.wait_for_timeout(800)

    payloads_by_key = {}
    previous_count = 0
    previous_scroll_y = -1
    stable_iterations = 0

    iterations = 30 if scroll else 1
    for _ in range(iterations):
        for payload in section.evaluate(ITEM_PAYLOADS_JS):
            payload["source"] = source
            key = payload.get("asin") or payload.get("href")
            if key:
                current = payloads_by_key.get(key)
                if not current or len(payload.get("text") or "") > len(current.get("text") or ""):
                    payloads_by_key[key] = payload

        if not scroll:
            break

        page.evaluate("window.scrollBy(0, Math.max(600, Math.floor(window.innerHeight * 0.8)))")
        page.wait_for_timeout(700)

        scroll_y = page.evaluate("window.scrollY")
        current_count = len(payloads_by_key)
        if current_count == previous_count and scroll_y == previous_scroll_y:
            stable_iterations += 1
        else:
            stable_iterations = 0
        if stable_iterations >= 2:
            break
        previous_count = current_count
        previous_scroll_y = scroll_y

    section.scroll_into_view_if_needed()
    return list(payloads_by_key.values())


def collect_cart_item_payloads(page) -> list[dict]:
    return collect_item_payloads(page, "#sc-active-cart", "cart", scroll=False)


def collect_saved_item_payloads(page) -> list[dict]:
    return collect_item_payloads(page, "#sc-saved-cart", "saved", scroll=True)


def item_score(item: ScrapedItem) -> tuple:
    return (
        1 if item.source == "cart" else 0,
        1 if item.price is not None else 0,
        1 if item.move_to_cart_visible else 0,
        len(item.raw_text),
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
            payloads = collect_cart_item_payloads(page) + collect_saved_item_payloads(page)
            by_asin = {}
            for payload in payloads:
                item = item_from_payload(payload)
                if item and (item.asin not in by_asin or item_score(item) > item_score(by_asin[item.asin])):
                    by_asin[item.asin] = item
            return list(by_asin.values())
        finally:
            context.close()
