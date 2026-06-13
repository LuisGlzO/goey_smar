from urllib.parse import quote, urljoin

from django.conf import settings


def affiliate_url_for(product, fallback_url=""):
    if product.affiliate_url:
        return product.affiliate_url
    if settings.AMAZON_ASSOCIATE_TAG:
        base_url = settings.AMAZON_BASE_URL.rstrip("/") + "/"
        return urljoin(base_url, f"dp/{product.asin}") + f"?tag={quote(settings.AMAZON_ASSOCIATE_TAG, safe='')}"
    return fallback_url

