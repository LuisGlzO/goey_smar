"""Common, unauthenticated navigation for public Amazon discovery pages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests


ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
POSITION_RE = re.compile(r"#?\s*(\d+)")
BLOCK_MARKERS = (
    "automated access to amazon data",
    "sorry, we just need to make sure you're not a robot",
    "api-services-support@amazon.com",
    "to discuss automated access",
)
CAPTCHA_MARKERS = ("captcha", "validatecaptcha", "enter the characters you see below")
ERROR_MARKERS = ("sorry! something went wrong", "dogs of amazon", "service unavailable")
TRACKING_QUERY_PREFIXES = ("ref", "tag", "linkcode", "creative", "camp", "ascsubtag")
AMAZON_HOST_SUFFIXES = {
    "amazon.com", "amazon.ca", "amazon.com.mx", "amazon.com.br", "amazon.co.uk",
    "amazon.de", "amazon.fr", "amazon.it", "amazon.es", "amazon.nl", "amazon.se",
    "amazon.pl", "amazon.com.be", "amazon.com.tr", "amazon.ae", "amazon.sa",
    "amazon.eg", "amazon.in", "amazon.co.jp", "amazon.com.au", "amazon.sg",
}


class AmazonDiscoveryConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class AmazonDiscoveryReview:
    items: tuple[dict, ...]
    pages_found: int
    is_complete: bool
    issues: tuple[str, ...] = ()

    def as_dict(self):
        return {
            "items": list(self.items),
            "pages_found": self.pages_found,
            "is_complete": self.is_complete,
            "issues": list(self.issues),
        }


@dataclass
class _Card:
    asin: str
    href: str = ""
    title_parts: list[str] = field(default_factory=list)
    price_whole: str = ""
    price_fraction: str = ""
    position_text: str = ""
    malformed: bool = False


class _AmazonPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[_Card] = []
        self.next_href = ""
        self.product_hints = 0
        self._card: _Card | None = None
        self._card_depth = 0
        self._capture: str | None = None
        self._capture_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        asin = attrs.get("data-asin", "").strip().upper()
        if asin:
            self.product_hints += 1
        if self._card is None and asin:
            self._card = _Card(asin=asin)
            self._card_depth = 1
        elif self._card is not None and tag not in {"area", "base", "br", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
            self._card_depth += 1

        if tag == "a" and "s-pagination-next" in classes and "s-pagination-disabled" not in classes:
            self.next_href = attrs.get("href", "").strip()

        if self._card is None:
            return
        if tag == "a" and attrs.get("href") and not self._card.href:
            href = attrs["href"]
            if "/dp/" in href or "/gp/product/" in href:
                self._card.href = href
        capture = None
        if "a-price-whole" in classes:
            capture = "price_whole"
        elif "a-price-fraction" in classes:
            capture = "price_fraction"
        elif "zg-bdg-text" in classes or "zg-badge-text" in classes:
            capture = "position_text"
        elif tag in ("h2", "h3") or "a-size-base-plus" in classes or "p13n-sc-truncate" in classes:
            capture = "title"
        if capture:
            self._capture = capture
            self._capture_depth = self._card_depth

    def handle_data(self, data):
        if not self._card or not self._capture:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._capture == "title":
            self._card.title_parts.append(value)
        elif self._capture == "price_whole":
            self._card.price_whole += value
        elif self._capture == "price_fraction":
            self._card.price_fraction += value
        else:
            self._card.position_text += value

    def handle_endtag(self, tag):
        if self._card is None:
            return
        if self._capture and self._capture_depth == self._card_depth:
            self._capture = None
        self._card_depth -= 1
        if self._card_depth == 0:
            self.cards.append(self._card)
            self._card = None


def _is_allowed_host(hostname):
    host = (hostname or "").lower().rstrip(".")
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in AMAZON_HOST_SUFFIXES)


def normalize_amazon_url(url, *, base_url=None):
    candidate = urljoin(base_url, str(url or "").strip()) if base_url else str(url or "").strip()
    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https" or not _is_allowed_host(parts.hostname):
        raise AmazonDiscoveryConfigurationError("La URL debe usar HTTPS y un dominio oficial de Amazon.")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise AmazonDiscoveryConfigurationError("La URL de Amazon contiene credenciales o un puerto no permitido.")
    host = parts.hostname.lower().rstrip(".")
    query = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit(("https", host, parts.path or "/", urlencode(query), ""))


def canonical_product_url(host, asin):
    return f"https://{host}/dp/{asin}"


def _parse_price(card):
    raw = card.price_whole.replace(".", "").replace(",", "")
    if not raw:
        return None
    fraction = re.sub(r"\D", "", card.price_fraction)[:2] or "00"
    try:
        return Decimal(f"{re.sub(r'\D', '', raw)}.{fraction}")
    except InvalidOperation:
        return None


def parse_amazon_page(html, page_url):
    parser = _AmazonPageParser()
    parser.feed(html or "")
    host = urlsplit(page_url).hostname
    items, malformed = [], 0
    for card in parser.cards:
        title = " ".join(card.title_parts).strip()
        if not ASIN_RE.fullmatch(card.asin) or not title:
            malformed += 1
            continue
        match = POSITION_RE.search(card.position_text)
        items.append({
            "external_id": card.asin,
            "name": title,
            "price": _parse_price(card),
            "url": canonical_product_url(host, card.asin),
            "position": int(match.group(1)) if match else None,
        })
    next_url = normalize_amazon_url(parser.next_href, base_url=page_url) if parser.next_href else None
    return items, next_url, parser.product_hints, malformed


def _page_problem(response):
    body = (response.text or "").lower()
    if response.status_code >= 500:
        return "http_error"
    if response.status_code in (401, 403, 429) or any(marker in body for marker in BLOCK_MARKERS):
        return "blocked"
    if any(marker in body for marker in CAPTCHA_MARKERS):
        return "captcha"
    if response.status_code >= 400 or any(marker in body for marker in ERROR_MARKERS):
        return "error_page"
    if not body.strip():
        return "empty_page"
    return None


def navigate_amazon_public(url, *, max_pages=20, timeout=20, session=None):
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise AmazonDiscoveryConfigurationError("max_pages debe ser un entero positivo.")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise AmazonDiscoveryConfigurationError("timeout debe ser positivo.")
    current = normalize_amazon_url(url)
    client = session or requests.Session()
    visited, products, issues = set(), {}, []
    pages_found = 0
    while current:
        if current in visited:
            issues.append("pagination_cycle")
            break
        if pages_found >= max_pages:
            issues.append("page_limit")
            break
        visited.add(current)
        try:
            response = client.get(
                current,
                timeout=timeout,
                allow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GoeyDiscovery/1.0)"},
            )
        except requests.Timeout:
            issues.append("timeout")
            break
        except requests.RequestException:
            issues.append("network_error")
            break
        if response.is_redirect:
            location = response.headers.get("Location")
            if not location:
                issues.append("invalid_redirect")
                break
            try:
                redirected = normalize_amazon_url(location, base_url=current)
            except AmazonDiscoveryConfigurationError:
                issues.append("invalid_redirect")
                break
            if redirected in visited:
                issues.append("redirect_cycle")
                break
            current = redirected
            continue
        pages_found += 1
        problem = _page_problem(response)
        if problem:
            issues.append(problem)
            break
        try:
            items, next_url, hints, malformed = parse_amazon_page(response.text, current)
        except (AmazonDiscoveryConfigurationError, ValueError):
            issues.append("unexpected_structure")
            break
        if malformed:
            issues.append("incomplete_products")
        if not items:
            issues.append("unexpected_structure" if hints else "empty_content")
            break
        for item in items:
            products.setdefault(item["external_id"], item)
        current = next_url
    return AmazonDiscoveryReview(tuple(products.values()), pages_found, not issues, tuple(dict.fromkeys(issues)))
