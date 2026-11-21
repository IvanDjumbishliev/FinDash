"""FinDash settings. Production settings are activated with DJANGO_ENV=production."""

from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers
from decouple import Config, RepositoryEmpty, RepositoryEnv
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
env_file = BASE_DIR / ".env"
env = Config(RepositoryEnv(str(env_file)) if env_file.is_file() else RepositoryEmpty())


def env_list(name, default=""):
    return [value.strip() for value in env(name, default=default).split(",") if value.strip()]


def required(name):
    value = env(name, default="")
    if not value.strip():
        raise ImproperlyConfigured(f"{name} is required in production.")
    return value


environment = env("DJANGO_ENV", default="development").lower()
if environment not in {"development", "production"}:
    raise ImproperlyConfigured("DJANGO_ENV must be development or production.")
PRODUCTION = environment == "production"
DEBUG = not PRODUCTION

if PRODUCTION:
    SECRET_KEY = required("DJANGO_SECRET_KEY")
    if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong, unique production key.")
    ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list trusted production hostnames.")
else:
    SECRET_KEY = env("DJANGO_SECRET_KEY", default="") or get_random_secret_key()
    ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

API_KEY = env("API_KEY", default="").strip()
COPILOT_GEMINI_MODEL = env("COPILOT_GEMINI_MODEL", default="gemini-3.8-flash")
BUDGET_GEMINI_MODEL = env("BUDGET_GEMINI_MODEL", default="gemini-3.8-flash")
STATEMENT_GEMINI_MODEL = env("STATEMENT_GEMINI_MODEL", default="gemini-3.8-flash")

# Persistent sessions work across Gunicorn workers and do not depend on the task broker.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "findash-cache",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "api",
    "rest_framework",
    "corsheaders",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if PRODUCTION else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.wsgi.application"


# When a PostgreSQL database is selected, require connection credentials in production.
if PRODUCTION or env("DB_NAME", default=""):
    db_value = required if PRODUCTION else lambda name: env(name, default="")
    db_options = {"connect_timeout": 5}
    if sslmode := env("DB_SSLMODE", default="verify-full" if PRODUCTION else ""):
        db_options["sslmode"] = sslmode
    if sslrootcert := env("DB_SSLROOTCERT", default=""):
        db_options["sslrootcert"] = sslrootcert
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": db_value("DB_NAME"),
            "USER": db_value("DB_USER"),
            "PASSWORD": db_value("DB_PASSWORD"),
            "HOST": db_value("DB_HOST"),
            "PORT": env("DB_PORT", default="5432"),
            "OPTIONS": db_options,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3")),
        }
    }


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if PRODUCTION or env("DJANGO_BUILD_STATIC", default=False, cast=bool)
        else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    "" if PRODUCTION else "http://localhost:5173,http://127.0.0.1:5173",
)
CORS_URLS_REGEX = r"^/api/"
CORS_ALLOW_HEADERS = (*default_headers, "x-starting-balance")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if PRODUCTION:
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    SECURE_HSTS_SECONDS = env("DJANGO_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env("DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool)
    SECURE_HSTS_PRELOAD = env("DJANGO_HSTS_PRELOAD", default=False, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SAMESITE = "Lax"
    if env("DJANGO_TRUST_PROXY_HEADERS", default=False, cast=bool):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

GROCERY_CATALOG_RETAILERS = frozenset(
    value.strip() for value in env("GROCERY_CATALOG_RETAILERS", default="").split(",") if value.strip()
)

NOTIFICATION_RETENTION_DAYS = max(1, int(env("NOTIFICATION_RETENTION_DAYS", default="90")))

CELERY_BROKER_URL = (
    required("CELERY_BROKER_URL") if PRODUCTION else env("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/0")
)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 10
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "socket_connect_timeout": 5,
    "socket_timeout": 5,
    "visibility_timeout": 1800,
}
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SOFT_TIME_LIMIT = 90
CELERY_TASK_TIME_LIMIT = 120
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

NOTIFICATION_MARKET_CHECKS_ENABLED = env("NOTIFICATION_MARKET_CHECKS_ENABLED", default=False, cast=bool)

CELERY_BEAT_SCHEDULE = {
    "notification-renewals": {
        "task": "notifications.schedule_renewals",
        "schedule": max(60, int(env("NOTIFICATION_RENEWAL_INTERVAL_SECONDS", default="3600"))),
    },
    "notification-budgets": {
        "task": "notifications.schedule_budgets",
        "schedule": max(60, int(env("NOTIFICATION_BUDGET_INTERVAL_SECONDS", default="900"))),
    },
    "notification-retention": {
        "task": "notifications.purge",
        "schedule": max(60, int(env("NOTIFICATION_RETENTION_INTERVAL_SECONDS", default="86400"))),
    },
}
if NOTIFICATION_MARKET_CHECKS_ENABLED:
    CELERY_BEAT_SCHEDULE["notification-market"] = {
        "task": "notifications.schedule_market",
        "schedule": max(60, int(env("NOTIFICATION_MARKET_INTERVAL_SECONDS", default="900"))),
    }
