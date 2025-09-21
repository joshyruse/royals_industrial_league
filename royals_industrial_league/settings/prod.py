import os
from .base import *

DEBUG = False
hosts = os.getenv("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h for h in (hosts.split(",") if hosts else []) if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("DJANGO_CSRF_TRUSTED", "").split(",") if o]

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Local prod-mode testing without HTTPS
if os.getenv("LOCAL_NO_SSL", "0") == "1":
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# Where collectstatic will place the built assets
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Whitenoise (static files in prod) ---
# Ensure Whitenoise middleware sits immediately after SecurityMiddleware
try:
    _sec_idx = MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
    if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
        MIDDLEWARE.insert(_sec_idx + 1, "whitenoise.middleware.WhiteNoiseMiddleware")
except ValueError:
    # If SecurityMiddleware isn't present for some reason, prepend Whitenoise conservatively
    if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
        MIDDLEWARE.insert(0, "whitenoise.middleware.WhiteNoiseMiddleware")

# Use hashed, compressed static file storage
STORAGES = globals().get("STORAGES", {})
STORAGES["staticfiles"] = {
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}
globals()["STORAGES"] = STORAGES

# One year cache for hashed assets served by Whitenoise
WHITENOISE_MAX_AGE = 31536000

# Explicit cookie flags (complements base.py defaults)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # keep False if any JS reads the CSRF cookie

# If behind a proxy/load balancer:
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Content Security Policy (django-csp v4+)
INSTALLED_APPS += ["csp"]
MIDDLEWARE.insert(0, "csp.middleware.CSPMiddleware")  # keep early in chain

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": ("'self'", "https://cdn.jsdelivr.net"),
        "style-src": ("'self'", "https://cdn.jsdelivr.net"),
        "img-src": ("'self'", "data:"),
        "font-src": ("'self'", "https://cdn.jsdelivr.net", "data:"),
        "connect-src": ("'self'",),
        "object-src": ("'none'",),
        "frame-ancestors": ("'none'",),
    }
}

# Sentry (optional; enable by setting SENTRY_DSN)
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(dsn=SENTRY_DSN, integrations=[DjangoIntegration()], traces_sample_rate=0.0)


# Structured-ish console logging for production
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
# Apps / middleware / auth backend
INSTALLED_APPS += ["axes"]
INSTALLED_APPS += ["anymail"]
MIDDLEWARE.insert(0, "axes.middleware.AxesMiddleware")
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",   # axes checks first
    "django.contrib.auth.backends.ModelBackend",
]

# Sensible defaults
AXES_FAILURE_LIMIT = 5           # lock after 5 bad attempts
AXES_COOLOFF_TIME = 1            # hours locked
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]

SENTRY_BROWSER_DSN = os.getenv("SENTRY_BROWSER_DSN", "")

# Ratelimiting settings
RATELIMIT_ENABLE = True

from django.urls import reverse_lazy

LOGIN_URL = reverse_lazy("league_login")

# --- Email: Anymail + Brevo (Sendinblue) ---
EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"  # for older Anymail versions, use: anymail.backends.sendinblue.EmailBackend
ANYMAIL = {
    "BREVO_API_KEY": os.getenv("BREVO_API_KEY"),
}
DEFAULT_FROM_EMAIL = "Royals Industrial League <captain@royalsleague.com>"  # must be a verified sender/domain in Brevo
SERVER_EMAIL = "Royals Industrial League <captain@royalsleague.com>"

# --- SMS (Brevo Transactional SMS) ---
# Normalize provider spelling and use environment variables for prod
ENABLE_SMS = (os.getenv("ENABLE_SMS", "0").lower() in ("1", "true", "yes"))
SMS_PROVIDER = (os.getenv("SMS_PROVIDER") or "brevo").lower()

# Unified API key (prefer BREVO_API_KEY; fall back to BREVO_SMS_API_KEY)
BREVO_API_KEY = os.getenv("BREVO_API_KEY") or os.getenv("BREVO_SMS_API_KEY") or ""

# Sender and extras
BREVO_SMS_SENDER = os.getenv("BREVO_SMS_SENDER", "ROYALS")  # 3–11 alpha or a verified number/shortcode
BREVO_ORG_PREFIX_US = os.getenv("BREVO_ORG_PREFIX_US", "Royals")
SMS_DEFAULT_COUNTRY = os.getenv("SMS_DEFAULT_COUNTRY", "US")

# Quiet hours (override via env in prod if needed)
NOTIFY_QUIET_HOURS_START = int(os.getenv("NOTIFY_QUIET_HOURS_START", "21"))  # 9pm local
NOTIFY_QUIET_HOURS_END = int(os.getenv("NOTIFY_QUIET_HOURS_END", "8"))       # 8am local