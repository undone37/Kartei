"""Kartei settings. Only bootstrap values come from env; everything else lives in kartei.Settings (DB)."""
import mimetypes
import os
import sys
import tempfile
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
mimetypes.add_type("application/manifest+json", ".webmanifest")  # PWA manifest, served by whitenoise
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))

DEBUG = os.environ.get("DEBUG", "0") == "1"
TESTING = sys.argv[1:2] == ["test"]  # no background syslog sender in tests
SECRET_KEY = os.environ.get("SECRET_KEY") or ("dev-insecure-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set when DEBUG is off")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost").split(",") + ["127.0.0.1"]  # loopback: container healthcheck
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if DEBUG:  # the Vite dev server (npm run dev) proxies the API; its address is the browser's origin
    CSRF_TRUSTED_ORIGINS += ["http://localhost:5173", "http://127.0.0.1:5173"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# rate limits use the client address from X-Forwarded-For (set by the reverse proxy); 0 if Kartei is reached directly
PROXY_HEADERS = os.environ.get("PROXY_HEADERS", "1") == "1"
# X-Forwarded-For/-Proto count only from these addresses (the reverse proxy); anyone else could fake their address
# and so get around rate limits, the monitoring allowlist and the audit log. Default: loopback and Docker networks.
TRUSTED_PROXIES = [x.strip() for x in os.environ.get("TRUSTED_PROXIES", "127.0.0.0/8,::1/128,172.16.0.0/12").split(",") if x.strip()]
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG and os.environ.get("SECURE_COOKIES", "1") == "1"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "kartei",
]
if sys.argv[1:2] == ["test"]:
    INSTALLED_APPS.append("relay")  # the DMZ relay (config.relay_settings) is tested in the same run

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "kartei.net.security_headers",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "kartei.net.ip_middleware",
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

# an empty DATABASE_URL counts as unset (dj_database_url would fall back to a dummy backend)
# shown in the user menu: the release tag (set by the image build) and where the source code is (AGPL: forks that run
# a modified version point this at their code)
KARTEI_VERSION = os.environ.get("KARTEI_VERSION") or "dev"
KARTEI_SOURCE_URL = os.environ.get("KARTEI_SOURCE_URL") or "https://github.com/undone37/Kartei"

DATABASES = {"default": dj_database_url.parse(
    os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600,
    conn_health_checks=True)}  # a reused connection is checked first (e.g. after a cluster failover)

AUTHENTICATION_BACKENDS = ["kartei.auth.DbLDAPBackend", "django.contrib.auth.backends.ModelBackend"]

LANGUAGE_CODE = "de"
TIME_ZONE = "Europe/Berlin"
# one cache for all gunicorn workers of a container, so rate limits (failed sign-ins etc.) count across them
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"} if TESTING else
          {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
           "LOCATION": os.environ.get("CACHE_DIR", os.path.join(tempfile.gettempdir(), "kartei-cache"))}}
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_IMMUTABLE_FILE_TEST = lambda path, url: "/assets/" in url  # vite hashes these
WHITENOISE_ALLOW_ALL_ORIGINS = False  # no Access-Control-Allow-Origin: * on static files; the app is same-origin

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # CSV imports

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,  # else django.request is off and server errors leave no traceback in the log
    # JSON lines in production (LOG_FORMAT=json, the default without DEBUG), so log shippers and the SIEM can parse them
    "formatters": {"json": {"()": "kartei.logs.JsonFormatter"}},
    "handlers": {"syslog": {"class": "kartei.syslog.Handler"},  # sends only once enabled in the settings
                 "console": {"class": "logging.StreamHandler",
                             **({"formatter": "json"} if os.environ.get("LOG_FORMAT", "text" if DEBUG else "json") == "json" else {})}},
    "root": {"handlers": ["console"] + ([] if TESTING else ["syslog"]), "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {"kartei.audit": {"level": "WARNING" if TESTING else "INFO"}},  # audit events reach the SIEM whatever LOG_LEVEL says
}
