import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-local-development-key")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [item.strip() for item in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if item.strip()]
CSRF_TRUSTED_ORIGINS = [
    item.strip()
    for item in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if item.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "monitor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

if os.getenv("USE_SQLITE", "false").lower() != "true" and os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ["POSTGRES_USER"],
            "PASSWORD": os.environ["POSTGRES_PASSWORD"],
            "HOST": os.getenv("POSTGRES_HOST", "db"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "es-mx"
TIME_ZONE = os.getenv("TZ", "America/Mexico_City")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = os.getenv("DJANGO_SESSION_COOKIE_SECURE", "false").lower() == "true"
CSRF_COOKIE_SECURE = os.getenv("DJANGO_CSRF_COOKIE_SECURE", "false").lower() == "true"

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", "120"))
MONITOR_TASK_EXPIRES_SECONDS = int(os.getenv("MONITOR_TASK_EXPIRES_SECONDS", str(MONITOR_INTERVAL_SECONDS)))
MONITOR_TASK_TIME_LIMIT_SECONDS = int(os.getenv("MONITOR_TASK_TIME_LIMIT_SECONDS", "240"))
MONITOR_RUNNING_STALE_MINUTES = int(os.getenv("MONITOR_RUNNING_STALE_MINUTES", "10"))
MONITOR_FAILURE_ALERT_COOLDOWN_MINUTES = int(os.getenv("MONITOR_FAILURE_ALERT_COOLDOWN_MINUTES", "60"))
MONITOR_INFRASTRUCTURE_FAILURE_RESTART_THRESHOLD = int(os.getenv("MONITOR_INFRASTRUCTURE_FAILURE_RESTART_THRESHOLD", "3"))
MONITOR_AUTO_RESTART_WORKER_ON_INFRA_FAILURE = os.getenv("MONITOR_AUTO_RESTART_WORKER_ON_INFRA_FAILURE", "true").lower() == "true"
CELERY_BEAT_SCHEDULE = {
    "monitor-saved-items": {
        "task": "monitor.tasks.monitor_saved_items",
        "schedule": MONITOR_INTERVAL_SECONDS,
        "options": {"expires": MONITOR_TASK_EXPIRES_SECONDS},
    }
}

AMAZON_SAVED_ITEMS_URL = os.getenv("AMAZON_SAVED_ITEMS_URL", "https://www.amazon.com.mx/gp/cart/view.html")
AMAZON_BASE_URL = os.getenv("AMAZON_BASE_URL", "https://www.amazon.com.mx")
AMAZON_ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "")
AMAZON_CREATORS_API_BASE_URL = os.getenv("AMAZON_CREATORS_API_BASE_URL", "https://creatorsapi.amazon").rstrip("/")
AMAZON_CREATORS_API_TOKEN_URL = os.getenv("AMAZON_CREATORS_API_TOKEN_URL", "")
AMAZON_CREATORS_API_CLIENT_ID = os.getenv("AMAZON_CREATORS_API_CLIENT_ID", "")
AMAZON_CREATORS_API_CLIENT_SECRET = os.getenv("AMAZON_CREATORS_API_CLIENT_SECRET", "")
AMAZON_CREATORS_API_CREDENTIAL_VERSION = os.getenv("AMAZON_CREATORS_API_CREDENTIAL_VERSION", "3")
AMAZON_CREATORS_API_MARKETPLACE = os.getenv("AMAZON_CREATORS_API_MARKETPLACE", "www.amazon.com.mx")
AMAZON_CREATORS_API_PARTNER_TAG = os.getenv("AMAZON_CREATORS_API_PARTNER_TAG", AMAZON_ASSOCIATE_TAG)
AMAZON_CREATORS_API_LANGUAGES = [
    item.strip()
    for item in os.getenv("AMAZON_CREATORS_API_LANGUAGES", "es_MX").split(",")
    if item.strip()
]
AMAZON_CREATORS_API_TIMEOUT_SECONDS = int(os.getenv("AMAZON_CREATORS_API_TIMEOUT_SECONDS", "5"))
AMAZON_PROFILE_DIR = os.getenv("AMAZON_PROFILE_DIR", str(BASE_DIR / ".amazon-profile"))
AMAZON_HEADLESS = os.getenv("AMAZON_HEADLESS", "true").lower() == "true"
AMAZON_TIMEOUT_MS = int(os.getenv("AMAZON_TIMEOUT_MS", "45000"))
AMAZON_BROWSER_LAUNCH_TIMEOUT_MS = int(os.getenv("AMAZON_BROWSER_LAUNCH_TIMEOUT_MS", "60000"))
AMAZON_SCRAPER_MAX_ATTEMPTS = int(os.getenv("AMAZON_SCRAPER_MAX_ATTEMPTS", "2"))
AMAZON_SCRAPER_RETRY_DELAY_SECONDS = float(os.getenv("AMAZON_SCRAPER_RETRY_DELAY_SECONDS", "5"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ERROR_BOT_TOKEN = os.getenv("TELEGRAM_ERROR_BOT_TOKEN", "")
TELEGRAM_ERROR_CHAT_ID = os.getenv("TELEGRAM_ERROR_CHAT_ID", "")

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")

MONITOR_FAILURE_EMAIL_RECIPIENTS = [
    item.strip()
    for item in os.getenv("MONITOR_FAILURE_EMAIL_RECIPIENTS", "").split(",")
    if item.strip()
]
MONITOR_FAILURE_EMAIL_SUBJECT_PREFIX = os.getenv("MONITOR_FAILURE_EMAIL_SUBJECT_PREFIX", "[Goey SMAR]")
