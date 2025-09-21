from .base import *
import os
import environ

env = environ.Env()

# Try Render Secret Files first, then local project root as a fallback.
# If neither exists, we just rely on real environment variables.
try:
    from .base import BASE_DIR  # already defined in base.py
except Exception:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_env_candidates = [
    os.path.join("/etc/secrets", ".dev.env"),           # Render Secret File path
    os.path.join(str(BASE_DIR), ".dev.env"),             # Local development file
]
for _p in _env_candidates:
    if os.path.exists(_p):
        environ.Env.read_env(_p)
        break
# royals_industrial_league/settings/prod.py  (and mirror in base.py)

DEBUG = True
ALLOWED_HOSTS = ["*"]  # dev
EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"
ANYMAIL = {
    "BREVO_API_KEY": os.getenv("BREVO_API_KEY_DEV", ""),
    "DEBUG_API_REQUESTS": True,
}
DEFAULT_FROM_EMAIL = os.getenv("EMAIL_FROM_DEV", "Royals Dev <captain-dev@royalsleague.com>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = "[DEV] "

# Optional: verbose logging in dev
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        # Your app package
        "league": {
            "handlers": ["console"],
            "level": "INFO",   # show .info() and above
            "propagate": False,
        },
        # Optionally quiet Django noise
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}

# Debug toolbar
INSTALLED_APPS += [
    "anymail",
    "debug_toolbar",
    "widget_tweaks",
    "sslserver",
]
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
INTERNAL_IPS = ["127.0.0.1"]

# Faster password hasher for quicker dev/test user creation
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Dev-only: redirect/whitelist email recipients if configured via env
# (see league/emaildev.py)
import importlib
try:
    importlib.import_module("league.emaildev")
except Exception:
    pass

# --- SMS Enable by Environment ---
ENABLE_SMS = (os.getenv("ENABLE_SMS", "0").lower() in ("1", "true", "yes"))
# Correct the typo and normalize provider spelling
SMS_PROVIDER = "brevo"

# Back-compat: allow several env var names for the API key
BREVO_API_KEY = (
    os.getenv("BREVO_API_KEY_DEV")
    or os.getenv("BREVO_SMS_API_KEY_DEV")
    or os.getenv("BREVO_API_KEY")
    or os.getenv("BREVO_SMS_API_KEY")
    or ""
)
BREVO_SMS_SENDER = "RoyalsIL"  # up to 11 chars (A-Z, 0-9); or a verified long code/short code in some regions
BREVO_ORG_PREFIX_US = "Royals"
SMS_DEFAULT_COUNTRY = "US"
# Optional feature flag some environments used
NOTIFY_QUIET_HOURS = (0, 0)