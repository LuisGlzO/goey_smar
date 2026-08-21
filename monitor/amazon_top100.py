"""Amazon Best Sellers (Top 100) discovery adapter."""

from .amazon_discovery import navigate_amazon_public


def collect_amazon_top100(url, *, max_pages=20, timeout=20, session=None):
    """Collect a Top 100 review through the common public Amazon navigator."""
    return navigate_amazon_public(
        url,
        max_pages=max_pages,
        timeout=timeout,
        session=session,
    )
