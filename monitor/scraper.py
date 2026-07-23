import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter
from urllib.parse import urljoin

from django.conf import settings
from .errors import is_infrastructure_error


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False


def _record_timing(timing, name: str, seconds: float, **details) -> None:
    if timing:
        timing.record("scraper", name, seconds, **details)


ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)
PRICE_RE = re.compile(r"(?:MXN\s*|\$\s*)([\d.,]+)", re.IGNORECASE)
UNAVAILABLE_TERMS = (
    "no disponible",
    "no esta disponible",
    "no está disponible",
    "no estÃ¡ disponible",
    "sin stock",
    "agotado",
    "oferta seleccionada ya no esta disponible",
    "oferta seleccionada ya no está disponible",
    "oferta seleccionada ya no estÃ¡ disponible",
    "currently unavailable",
    "out of stock",
)
MOVE_TO_CART_TERMS = ("mover al carrito", "move to cart")
CHROMIUM_PROFILE_LOCK_FILES = (
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "DevToolsActivePort",
)
PROFILE_OWNER_FILE = ".goey-profile-owner"

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


def collect_item_payloads(page, selector: str, source: str, scroll: bool = False, timing=None) -> list[dict]:
    started = perf_counter()
    section = page.locator(selector)
    if not section.count():
        _record_timing(timing, f"collect_{source}", perf_counter() - started, count=0, found_section=False)
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
    payloads = list(payloads_by_key.values())
    _record_timing(
        timing,
        f"collect_{source}",
        perf_counter() - started,
        count=len(payloads),
        found_section=True,
        scroll=scroll,
    )
    return payloads


def collect_cart_item_payloads(page, timing=None) -> list[dict]:
    return collect_item_payloads(page, "#sc-active-cart", "cart", scroll=False, timing=timing)


def collect_saved_item_payloads(page, timing=None) -> list[dict]:
    return collect_item_payloads(page, "#sc-saved-cart", "saved", scroll=True, timing=timing)


def item_score(item: ScrapedItem) -> tuple:
    return (
        1 if item.source == "cart" else 0,
        1 if item.price is not None else 0,
        1 if item.move_to_cart_visible else 0,
        len(item.raw_text),
    )


def cleanup_chromium_profile_locks(profile_dir: str) -> None:
    profile_path = Path(profile_dir)
    for filename in CHROMIUM_PROFILE_LOCK_FILES:
        try:
            (profile_path / filename).unlink(missing_ok=True)
        except OSError:
            pass


def validate_profile_owner(profile_dir: str, account_key: str) -> None:
    profile_path = Path(profile_dir)
    profile_path.mkdir(parents=True, exist_ok=True)
    owner_path = profile_path / PROFILE_OWNER_FILE
    try:
        file_descriptor = owner_path.open("x", encoding="utf-8")
    except FileExistsError:
        owner = owner_path.read_text(encoding="utf-8").strip()
        if owner != account_key:
            raise RuntimeError(
                f"El perfil de Amazon pertenece a {owner or 'una cuenta desconocida'}, no a {account_key}."
            )
    else:
        with file_descriptor:
            file_descriptor.write(account_key)


def scrape_saved_items_once(headless: bool, account_key: str, profile_dir: str, timing=None) -> list[ScrapedItem]:
    from playwright.sync_api import sync_playwright

    with timing.stage("cleanup_chromium_locks", group="scraper") if timing else _nullcontext():
        validate_profile_owner(profile_dir, account_key)
        cleanup_chromium_profile_locks(profile_dir)
    with sync_playwright() as playwright:
        with timing.stage("launch_chromium", group="scraper") if timing else _nullcontext():
            context = playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=headless,
                locale="es-MX",
                args=[
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-dev-shm-usage",
                    "--no-zygote",
                ],
                timeout=settings.AMAZON_BROWSER_LAUNCH_TIMEOUT_MS,
            )
        try:
            with timing.stage("open_page", group="scraper") if timing else _nullcontext():
                page = context.pages[0] if context.pages else context.new_page()
            with timing.stage("goto_amazon_cart", group="scraper") if timing else _nullcontext():
                page.goto(settings.AMAZON_SAVED_ITEMS_URL, wait_until="domcontentloaded", timeout=settings.AMAZON_TIMEOUT_MS)
            with timing.stage("post_load_wait", group="scraper") if timing else _nullcontext():
                page.wait_for_timeout(3000)
            with timing.stage("auth_check", group="scraper") if timing else _nullcontext():
                account_label = page.locator("#nav-link-accountList-nav-line-1")
                account_text = account_label.first.inner_text().lower() if account_label.count() else ""
            if (
                "signin" in page.url.lower()
                or page.locator("#ap_email").count()
                or "identificate" in account_text
                or "identifícate" in account_text
                or "sign in" in account_text
            ):
                raise RuntimeError(
                    f"La sesion de Amazon para {account_key} no es valida; "
                    f"ejecute init_amazon_session --account {account_key}."
                )
            payloads = collect_cart_item_payloads(page, timing=timing) + collect_saved_item_payloads(page, timing=timing)
            with timing.stage("parse_payloads", group="scraper", payload_count=len(payloads)) if timing else _nullcontext():
                by_asin = {}
                for payload in payloads:
                    item = item_from_payload(payload)
                    if item and (item.asin not in by_asin or item_score(item) > item_score(by_asin[item.asin])):
                        by_asin[item.asin] = item
                items = list(by_asin.values())
            _record_timing(timing, "scrape_result", 0, item_count=len(items), payload_count=len(payloads))
            return items
        finally:
            with timing.stage("close_chromium", group="scraper") if timing else _nullcontext():
                context.close()


def scrape_saved_items(account_key: str, profile_dir: str, headless: bool | None = None, timing=None) -> list[ScrapedItem]:
    headless = settings.AMAZON_HEADLESS if headless is None else headless
    attempts = max(settings.AMAZON_SCRAPER_MAX_ATTEMPTS, 1)
    last_exc = None
    for attempt in range(1, attempts + 1):
        started = perf_counter()
        try:
            items = scrape_saved_items_once(headless, account_key, profile_dir, timing=timing)
            _record_timing(timing, "scrape_attempt", perf_counter() - started, attempt=attempt, status="success")
            return items
        except Exception as exc:
            last_exc = exc
            _record_timing(timing, "scrape_attempt", perf_counter() - started, attempt=attempt, status="failed")
            if attempt >= attempts or not is_infrastructure_error(exc):
                raise
            time.sleep(settings.AMAZON_SCRAPER_RETRY_DELAY_SECONDS)
    raise last_exc
