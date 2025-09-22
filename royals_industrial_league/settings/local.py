# royals_industrial_league/settings/local.py

from .base import *
import os
import environ

env = environ.Env()

try:
    from .base import BASE_DIR  # already defined in base.py
except Exception:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- General ---
DEBUG = True

SECRET_KEY = env(
    "SECRET_KEY",
    default="insecure-local-secret-key",  # only for local dev!
)

# --- Database ---
# Default: local SQLite file
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = 0  # no persistent connections

# --- Static files ---
# Use WhiteNoise in finder mode, no manifest (avoid 500s if missing assets)
STORAGES = globals().get("STORAGES", {})
STORAGES["staticfiles"] = {
    "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
}
globals()["STORAGES"] = STORAGES

WHITENOISE_USE_FINDERS = True

# --- Hosts / CSRF ---
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# --- Email ---
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "Royals Local <captain-local@royalsleague.com>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = "[LOCAL] "

# --- Logging ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "league": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Debugging tools ---
INSTALLED_APPS += [
    "debug_toolbar",
    "widget_tweaks",
    "sslserver",
]
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
INTERNAL_IPS = ["127.0.0.1"]

# --- Password hashing speed-up for local ---
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# --- SMS ---
ENABLE_SMS = True  # default off for local
SMS_PROVIDER = "brevo"
BREVO_API_KEY = ""  # empty for local
BREVO_SMS_SENDER = "RoyalsIL"
SMS_DEFAULT_COUNTRY = "US"
NOTIFY_QUIET_HOURS = (0, 0)

# --- Email dev redirect support ---
import importlib
try:
    importlib.import_module("league.emaildev")
except Exception:
    pass