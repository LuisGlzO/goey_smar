"""Public discovery collectors, isolated from the commercial monitor."""

from django.conf import settings

from .amazon_newest import collect_amazon_newest
from .amazon_top100 import collect_amazon_top100
from .amazon_trackers import collect_amazon_trackers
from .mercado_libre_discovery import navigate_mercado_libre_public
from .models import DiscoverySource


def collect_discovery_source(source):
    configuration = source.configuration or {}
    if source.source_type == DiscoverySource.SourceType.MERCADO_LIBRE_SELLER:
        return navigate_mercado_libre_public(
            source.url,
            max_pages=configuration.get(
                "max_pages", getattr(settings, "MERCADOLIBRE_DISCOVERY_MAX_PAGES", 50)
            ),
            timeout=configuration.get(
                "timeout_seconds",
                getattr(settings, "MERCADOLIBRE_DISCOVERY_TIMEOUT_SECONDS", 20),
            ),
        ).as_dict()
    options = {
        "timeout": configuration.get(
            "timeout_seconds", getattr(settings, "AMAZON_DISCOVERY_TIMEOUT_SECONDS", 20)
        ),
    }
    if source.source_type == DiscoverySource.SourceType.AMAZON_TOP_100:
        return collect_amazon_top100(
            source.url,
            max_pages=getattr(settings, "AMAZON_TOP100_DISCOVERY_MAX_PAGES", 20),
            **options,
        ).as_dict()
    if source.source_type == DiscoverySource.SourceType.AMAZON_NEWEST:
        return collect_amazon_newest(
            source.url,
            max_pages=getattr(settings, "AMAZON_NEWEST_DISCOVERY_MAX_PAGES", 20),
            **options,
        ).as_dict()
    if source.source_type == DiscoverySource.SourceType.AMAZON_TRACKERS:
        return collect_amazon_trackers(
            source.url,
            max_pages=getattr(settings, "AMAZON_TRACKERS_DISCOVERY_MAX_PAGES", 20),
            **options,
        ).as_dict()
    raise NotImplementedError(
        f"No hay recolector habilitado todavía para {source.get_source_type_display()}."
    )
