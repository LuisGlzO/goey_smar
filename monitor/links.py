from urllib.parse import quote, urlencode, urljoin

from django.conf import settings


def default_affiliate_tag() -> str:
    return settings.AMAZON_CREATORS_API_PARTNER_TAG or settings.AMAZON_ASSOCIATE_TAG


def affiliate_url_for(product, fallback_url=""):
    if product.affiliate_url:
        return product.affiliate_url
    affiliate_tag = default_affiliate_tag()
    if affiliate_tag:
        base_url = settings.AMAZON_BASE_URL.rstrip("/") + "/"
        query = urlencode(
            {
                "tag": affiliate_tag,
                "linkCode": "ogi",
                "th": "1",
                "psc": "1",
            },
            quote_via=quote,
        )
        return urljoin(base_url, f"dp/{product.asin}") + f"?{query}"
    return fallback_url
