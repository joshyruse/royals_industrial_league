# royals_industrial_league/settings/local.py

from .base import *
import os
import environ

# Prevent .dev.env (or your shell) from forcing Postgres locally
os.environ.pop("DATABASE_URL", None)

env = environ.Env()
# Load the same .dev.env so you get Twilio, email, etc.
env_file = BASE_DIR / ".dev.env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

# --- Local-only overrides ---
# Prefer a LOCAL_SMS_PROVIDER if present; otherwise default to twilio for local.
_local_sms = os.getenv("LOCAL_SMS_PROVIDER", "").strip().lower()
if _local_sms:
    os.environ["SMS_PROVIDER"] = _local_sms

# --- General ---
DEBUG = True

SECRET_KEY = env(
    "SECRET_KEY",
    default="insecure-local-secret-key",  # only for local dev!
)

# --- Database ---
# Default: local SQLite file
# local.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
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

# --- SMS Enable by Environment ---
ENABLE_SMS = (os.getenv("ENABLE_SMS", "0").lower() in ("1", "true", "yes"))

# --- SMS Settings (prefer Twilio locally unless explicitly set) ---
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "twilio").lower()  # default to twilio on local
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")

# --- SMS Settings for Brevo ---
BREVO_SMS_SENDER = "RoyalsIL"  # up to 11 chars (A-Z, 0-9); or a verified long code/short code in some regions
BREVO_ORG_PREFIX_US = "Royals"
SMS_DEFAULT_COUNTRY = "US"
# Optional feature flag some environments used
NOTIFY_QUIET_HOURS = (0, 0)

# --- Email dev redirect support ---
import importlib
try:
    importlib.import_module("league.emaildev")
except Exception:
    pass