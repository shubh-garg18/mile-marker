"""Django settings for the ELD Trip Planner API.

Every environment-specific value is read from the environment with a local-friendly
default. The API is stateless and token-free: no models, no sessions, no CSRF.
"""

import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


DEBUG = _env_bool("DEBUG", False)

# `or`, not a default argument. An empty SECRET_KEY= line in a .env file is
# present as far as os.environ.get is concerned, so a default would be skipped and
# Django would fail later with "must not be empty".
#
# The fallback is generated rather than a constant committed to this repository,
# because a known-value placeholder is what quietly ships to production. It is
# safe here only because the service is stateless: no sessions, no auth, no CSRF,
# nothing signed, so a key that differs per process costs nothing. Set the
# variable in any real deployment.
SECRET_KEY = os.environ.get("SECRET_KEY") or get_random_secret_key()

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS") or ["localhost", "127.0.0.1", "testserver"]
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)

# Exact origins only. CORS_ALLOW_ALL_ORIGINS is never set.
CORS_ALLOWED_ORIGINS = _env_list("CORS_ALLOWED_ORIGINS") or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

# No models, so no database is ever opened.
DATABASES = {}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "eld-trip-planner",
        "TIMEOUT": 60 * 60 * 24,
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = False  # Trip arithmetic is naive home-terminal local time.

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "trips.api.errors.exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    # JSON only. Dropping the browsable renderer also removes DRF's dependency on
    # collected static files, which with the manifest storage above would turn a
    # browser visit into a bare 500. Rendering happens after the exception
    # handler runs, so that 500 would never reach it.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # One plan request can spend up to twenty upstream calls, and ORS's free tier
    # allows forty a minute in total. Without a ceiling a single client can drain
    # the whole window and every other user sees UPSTREAM_RATE_LIMITED.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("PLAN_RATE_LIMIT", "12/min")},
}

# --- OpenRouteService (server-side only; never exposed to the client) ---
ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
ORS_TIMEOUT_SECONDS = float(os.environ.get("ORS_TIMEOUT_SECONDS", "15"))

# The time standard every sheet is drawn in. §395.8(a) requires the home
# terminal's for the whole trip, even when the route crosses time zones, so this
# is a property of the carrier rather than of the route. It is reported to the
# client for display; no conversion is performed against it.
HOME_TERMINAL_TIMEZONE = os.environ.get("HOME_TERMINAL_TIMEZONE", "America/Chicago")

# --- RODS header placeholders (the brief supplies no carrier data) ---
LOG_SHEET_HEADER = {
    "driver_name": os.environ.get("LOG_DRIVER_NAME", "Shubh Garg"),
    "carrier_name": os.environ.get("LOG_CARRIER_NAME", "Spotter Freight Lines, LLC"),
    "office_address": os.environ.get(
        "LOG_OFFICE_ADDRESS", "1400 Corridor Way, Fort Worth, TX 76106"
    ),
    "terminal_address": os.environ.get(
        "LOG_TERMINAL_ADDRESS", "1400 Corridor Way, Fort Worth, TX 76106"
    ),
    "tractor_number": os.environ.get("LOG_TRACTOR_NUMBER", "4417"),
    "trailer_number": os.environ.get("LOG_TRAILER_NUMBER", "2290"),
    "shipping_document": os.environ.get("LOG_SHIPPING_DOCUMENT", "BOL 88-4417"),
    "shipper_commodity": os.environ.get("LOG_SHIPPER_COMMODITY", "General freight, palletized"),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
