"""Amazon search Tracker discovery adapter."""

from .amazon_discovery import navigate_amazon_public


def collect_amazon_trackers(url, *, max_pages=20, timeout=20, session=None):
    """Collect a client-configured public Amazon search."""
    return navigate_amazon_public(
        url,
        max_pages=max_pages,
        timeout=timeout,
        session=session,
    )
