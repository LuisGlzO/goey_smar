import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CREATORS_API_BASE_URL = "https://creatorsapi.amazon"
V2_TOKEN_ENDPOINT = "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token"
V3_TOKEN_ENDPOINT = "https://api.amazon.com/auth/o2/token"


@dataclass(frozen=True)
class CreatorProductContent:
    title: str
    image_url: str
    detail_page_url: str


_token_cache = {"access_token": "", "expires_at": 0.0}


def _marketplace_from_base_url() -> str:
    parsed = urlparse(settings.AMAZON_BASE_URL)
    return parsed.netloc or "www.amazon.com.mx"


def _credential_version() -> str:
    return settings.AMAZON_CREATORS_API_CREDENTIAL_VERSION.strip()


def _is_v2_credentials() -> bool:
    return _credential_version().startswith("2.")


def creators_api_is_configured() -> bool:
    return bool(
        settings.AMAZON_CREATORS_API_CLIENT_ID
        and settings.AMAZON_CREATORS_API_CLIENT_SECRET
        and settings.AMAZON_CREATORS_API_PARTNER_TAG
    )


def _token_endpoint() -> str:
    configured = settings.AMAZON_CREATORS_API_TOKEN_URL.strip()
    if configured:
        return configured
    return V2_TOKEN_ENDPOINT if _is_v2_credentials() else V3_TOKEN_ENDPOINT


def _fetch_access_token() -> str:
    if _is_v2_credentials():
        response = requests.post(
            _token_endpoint(),
            data={
                "grant_type": "client_credentials",
                "client_id": settings.AMAZON_CREATORS_API_CLIENT_ID,
                "client_secret": settings.AMAZON_CREATORS_API_CLIENT_SECRET,
                "scope": "creatorsapi/default",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=settings.AMAZON_CREATORS_API_TIMEOUT_SECONDS,
        )
    else:
        response = requests.post(
            _token_endpoint(),
            json={
                "grant_type": "client_credentials",
                "client_id": settings.AMAZON_CREATORS_API_CLIENT_ID,
                "client_secret": settings.AMAZON_CREATORS_API_CLIENT_SECRET,
                "scope": "creatorsapi::default",
            },
            headers={"Content-Type": "application/json"},
            timeout=settings.AMAZON_CREATORS_API_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    payload = response.json()
    access_token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = time.time() + max(expires_in - 60, 60)
    return access_token


def get_access_token() -> str:
    if _token_cache["access_token"] and _token_cache["expires_at"] > time.time():
        return _token_cache["access_token"]
    return _fetch_access_token()


def _authorization_header(access_token: str) -> str:
    if _is_v2_credentials():
        return f"Bearer {access_token}, Version {_credential_version()}"
    return f"Bearer {access_token}"


def _first_image_url(item: dict) -> str:
    primary = (item.get("images") or {}).get("primary") or {}
    for size in ("large", "medium", "small"):
        image = primary.get(size) or {}
        if image.get("url"):
            return image["url"]
    return ""


def _title(item: dict) -> str:
    return (((item.get("itemInfo") or {}).get("title") or {}).get("displayValue") or "").strip()


def _items_from_response(payload: dict) -> list[dict]:
    container = payload.get("itemsResult") or payload.get("itemResults") or {}
    return container.get("items") or []


def get_product_content(asin: str) -> CreatorProductContent | None:
    if not creators_api_is_configured():
        return None

    marketplace = settings.AMAZON_CREATORS_API_MARKETPLACE or _marketplace_from_base_url()
    request_payload = {
        "itemIds": [asin],
        "itemIdType": "ASIN",
        "marketplace": marketplace,
        "partnerTag": settings.AMAZON_CREATORS_API_PARTNER_TAG,
        "resources": ["images.primary.large", "itemInfo.title"],
    }
    if settings.AMAZON_CREATORS_API_LANGUAGES:
        request_payload["languagesOfPreference"] = settings.AMAZON_CREATORS_API_LANGUAGES

    access_token = get_access_token()
    response = requests.post(
        f"{settings.AMAZON_CREATORS_API_BASE_URL}/catalog/v1/getItems",
        json=request_payload,
        headers={
            "Authorization": _authorization_header(access_token),
            "Content-Type": "application/json",
            "x-marketplace": marketplace,
        },
        timeout=settings.AMAZON_CREATORS_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    asin = asin.upper()
    for item in _items_from_response(response.json()):
        if item.get("asin", "").upper() != asin:
            continue
        return CreatorProductContent(
            title=_title(item),
            image_url=_first_image_url(item),
            detail_page_url=item.get("detailPageURL") or "",
        )
    return None


def safe_get_product_content(asin: str) -> CreatorProductContent | None:
    try:
        return get_product_content(asin)
    except Exception:
        logger.exception("No se pudo obtener contenido desde Creators API para ASIN %s.", asin)
        return None
