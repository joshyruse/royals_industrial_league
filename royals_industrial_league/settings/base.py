import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]  # adjust if your tree differs

SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("DJANGO_SECRET_KEY", "dev-not-secret")  # Render uses SECRET_KEY; keep legacy fallback
DEBUG = False  # overridden in dev.py

# Prefer modern env name; fall back to legacy DJANGO_ALLOWED_HOSTS for local/docker
hosts = os.getenv("ALLOWED_HOSTS") or os.getenv("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h for h in (hosts.split(",") if hosts else []) if h]

# Prefer modern env name; fall back to legacy DJANGO_CSRF_TRUSTED for local/docker
csrf = os.getenv("CSRF_TRUSTED_ORIGINS") or os.getenv("DJANGO_CSRF_TRUSTED", "")
CSRF_TRUSTED_ORIGINS = [o for o in csrf.split(",") if o]

# Canonical absolute base for building links in emails/SMS; dev/prod override as needed
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party (enabled in prod.py when needed): "csp",
    # your apps:
    "league",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Whitenoise (safe for dev & prod; comment if you already serve via nginx):
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # CSP goes here in prod.py: "csp.middleware.CSPMiddleware",
]

ROOT_URLCONF = "royals_industrial_league.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "league.context_processors.notifications_context",
                "league.context_processors.sms_flags"
            ],
            "builtins": [
                "django.templatetags.static",
            ],
        },
    },
]

WSGI_APPLICATION = "royals_industrial_league.wsgi.application"
ASGI_APPLICATION = "royals_industrial_league.asgi.application"

# DB (dev defaults to sqlite; override via env in dev/prod)
DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("DB_NAME", BASE_DIR / "db.sqlite3"),
        "USER": os.getenv("DB_USER", ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", ""),
        "PORT": os.getenv("DB_PORT", ""),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",        # preferred
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",

    # ---- Legacy verifier only (needed for md5$... hashes) ----
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"  # set yours
USE_I18N = True
USE_TZ = True

# static files change
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

# Whitenoise compression+hashing
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Security defaults (safe; hardened in prod.py)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Rate Limit enabling
RATELIMIT_ENABLE = True
RATELIMIT_CACHE = "default"  # use Redis in prod if available
RATELIMIT_HEADER = "X-RateLimit-Remaining"  # optional helpful header
# Tell django_ratelimit which view to call when a limit is exceeded
RATELIMIT_VIEW = "league.views.ratelimit_429"

# --- Auth redirects (shared across all envs) ---
from django.urls import reverse_lazy

LOGIN_URL = reverse_lazy('league_login')   # our /login/ route (custom-named)
LOGIN_REDIRECT_URL = '/'            # where to send users after login
LOGOUT_REDIRECT_URL = '/login/'     # after logout

BREVO_SMS_API_KEY = os.getenv("BREVO_SMS_API_KEY", "")
BREVO_SMS_SENDER = os.getenv("BREVO_SMS_SENDER", "ROYALS")
NOTIFY_QUIET_HOURS = (
    int(os.getenv("NOTIFY_QUIET_HOURS_START", "21")),
    int(os.getenv("NOTIFY_QUIET_HOURS_END", "8")),
)

# --- SMS feature flag (single source of truth) ---
ENABLE_SMS = (os.getenv("ENABLE_SMS", "0").lower() in ("1", "true", "yes"))
# --- end ---

# Provider spelling normalized
SMS_PROVIDER = (os.getenv("SMS_PROVIDER") or "brevo").lower()

# Unified API key (prefer BREVO_API_KEY, fall back to existing BREVO_SMS_API_KEY)
BREVO_API_KEY = (
    os.getenv("BREVO_API_KEY")
    or os.getenv("BREVO_SMS_API_KEY")
    or BREVO_SMS_API_KEY
)

# Sender/name & misc (already defined above; keep env overrides here if needed)
# BREVO_SMS_SENDER is already set above from env with a default; keep it.
BREVO_ORG_PREFIX_US = os.getenv("BREVO_ORG_PREFIX_US", "Royals")
SMS_DEFAULT_COUNTRY = os.getenv("SMS_DEFAULT_COUNTRY", "US")
# --- end SMS defaults ---