"""Amazon Newest discovery adapter."""

from .amazon_discovery import navigate_amazon_public


def collect_amazon_newest(url, *, max_pages=20, timeout=20, session=None):
    """Collect a newest-first search through the common Amazon navigator."""
    return navigate_amazon_public(
        url,
        max_pages=max_pages,
        timeout=timeout,
        session=session,
    )
