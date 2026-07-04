INFRASTRUCTURE_ERROR_TERMS = (
    "pthread_create: resource temporarily unavailable",
    "browsertype.launch_persistent_context",
    "target page, context or browser has been closed",
    "page.goto: timeout",
    "timeout",
    "chrome-headless-shell",
)


def is_infrastructure_error(exc_or_message) -> bool:
    message = str(exc_or_message).lower()
    return any(term in message for term in INFRASTRUCTURE_ERROR_TERMS)
