"""Unauthenticated navigation of public Mercado Libre seller listings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests


ITEM_ID_RE = re.compile(r"^MLM\d+$")
DIRECT_ITEM_RE = re.compile(r"/(MLM)-?(\d{6,})(?:[-/?#]|$)", re.IGNORECASE)
BLOCK_MARKERS = (
    "access denied",
    "acceso denegado",
    "security challenge",
    "actividad inusual",
)
CAPTCHA_MARKERS = ("captcha", "recaptcha", "no soy un robot")
ERROR_MARKERS = ("algo salió mal", "something went wrong", "service unavailable")
ALLOWED_HOST_SUFFIX = "mercadolibre.com.mx"
VOID_TAGS = {"area", "base", "br", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class MercadoLibreConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class MercadoLibreReview:
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
    href: str = ""
    title_parts: list[str] = field(default_factory=list)
    price_whole: str = ""
    price_fraction: str = ""


class _MercadoLibrePageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[_Card] = []
        self.next_href = ""
        self.product_hints = 0
        self._card: _Card | None = None
        self._card_depth = 0
        self._capture: str | None = None
        self._capture_depth = 0
        self._price_depth = 0
        self._anchor_is_next = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if self._card is None and tag == "li" and "ui-search-layout__item" in classes:
            self._card = _Card()
            self._card_depth = 1
            self.product_hints += 1
        elif self._card is not None and tag not in VOID_TAGS:
            self._card_depth += 1

        if tag == "a":
            label = " ".join((attrs.get("title", ""), attrs.get("aria-label", ""))).lower()
            self._anchor_is_next = (
                "andes-pagination__link" in classes and "siguiente" in label
            )
            if self._anchor_is_next and attrs.get("href"):
                self.next_href = attrs["href"].strip()

        if self._card is None:
            return
        if tag == "a" and "poly-component__title" in classes:
            self._card.href = attrs.get("href", "").strip()
            self._capture = "title"
            self._capture_depth = self._card_depth
        elif "poly-price__amount" in classes:
            self._price_depth = self._card_depth
        elif self._price_depth and "andes-money-amount__fraction" in classes:
            self._capture = "price_whole"
            self._capture_depth = self._card_depth
        elif self._price_depth and "andes-money-amount__cents" in classes:
            self._capture = "price_fraction"
            self._capture_depth = self._card_depth

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self._anchor_is_next and value.lower() == "siguiente":
            self._anchor_is_next = False
        if not self._card or not self._capture:
            return
        if self._capture == "title":
            self._card.title_parts.append(value)
        elif self._capture == "price_whole":
            self._card.price_whole += value
        elif self._capture == "price_fraction":
            self._card.price_fraction += value

    def handle_endtag(self, tag):
        if tag == "a":
            self._anchor_is_next = False
        if self._card is None:
            return
        if self._capture and self._capture_depth == self._card_depth:
            self._capture = None
        if self._price_depth == self._card_depth:
            self._price_depth = 0
        self._card_depth -= 1
        if self._card_depth == 0:
            self.cards.append(self._card)
            self._card = None


def _is_allowed_host(hostname):
    host = (hostname or "").lower().rstrip(".")
    return host == ALLOWED_HOST_SUFFIX or host.endswith(f".{ALLOWED_HOST_SUFFIX}")


def normalize_mercado_libre_url(url, *, base_url=None):
    candidate = urljoin(base_url, str(url or "").strip()) if base_url else str(url or "").strip()
    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https" or not _is_allowed_host(parts.hostname):
        raise MercadoLibreConfigurationError(
            "La URL debe usar HTTPS y un dominio oficial de Mercado Libre México."
        )
    if parts.username or parts.password or parts.port not in (None, 443):
        raise MercadoLibreConfigurationError(
            "La URL de Mercado Libre contiene credenciales o un puerto no permitido."
        )
    host = parts.hostname.lower().rstrip(".")
    return urlunsplit(("https", host, parts.path or "/", urlencode(parse_qsl(parts.query)), ""))


def _item_id(href):
    parts = urlsplit(href)
    fragment_values = dict(parse_qsl(parts.fragment))
    query_values = dict(parse_qsl(parts.query))
    candidate = (fragment_values.get("wid") or query_values.get("wid") or "").upper()
    if ITEM_ID_RE.fullmatch(candidate):
        return candidate
    match = DIRECT_ITEM_RE.search(parts.path)
    return f"{match.group(1).upper()}{match.group(2)}" if match else None


def canonical_item_url(item_id):
    return f"https://articulo.mercadolibre.com.mx/{item_id[:3]}-{item_id[3:]}"


def _parse_price(card):
    whole = re.sub(r"\D", "", card.price_whole)
    if not whole:
        return None
    cents = re.sub(r"\D", "", card.price_fraction)[:2] or "00"
    try:
        return Decimal(f"{whole}.{cents}")
    except InvalidOperation:
        return None


def parse_mercado_libre_page(html, page_url):
    parser = _MercadoLibrePageParser()
    parser.feed(html or "")
    items, malformed = [], 0
    for card in parser.cards:
        external_id = _item_id(card.href)
        title = " ".join(card.title_parts).strip()
        price = _parse_price(card)
        if not external_id or not title or price is None:
            malformed += 1
            continue
        items.append({
            "external_id": external_id,
            "name": title,
            "price": price,
            "url": canonical_item_url(external_id),
        })
    next_url = (
        normalize_mercado_libre_url(parser.next_href, base_url=page_url)
        if parser.next_href else None
    )
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


def navigate_mercado_libre_public(url, *, max_pages=50, timeout=20, session=None):
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise MercadoLibreConfigurationError("max_pages debe ser un entero positivo.")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise MercadoLibreConfigurationError("timeout debe ser positivo.")
    current = normalize_mercado_libre_url(url)
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
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
                    ),
                    "Accept-Language": "es-MX,es;q=0.9",
                },
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
                redirected = normalize_mercado_libre_url(location, base_url=current)
            except MercadoLibreConfigurationError:
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
            items, next_url, hints, malformed = parse_mercado_libre_page(response.text, current)
        except (MercadoLibreConfigurationError, ValueError):
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
    return MercadoLibreReview(
        tuple(products.values()), pages_found, not issues, tuple(dict.fromkeys(issues))
    )
