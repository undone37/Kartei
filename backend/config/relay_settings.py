"""Settings for the CardDAV relay in the DMZ (DJANGO_SETTINGS_MODULE=config.relay_settings).

Only the relay app: no Kartei app, admin, sessions or static files; its own SQLite file. The relay never connects
anywhere: Kartei pushes to /push, phones read /carddav/.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("SECRET_KEY") or ("dev-insecure-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set when DEBUG is off")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost").split(",") + ["127.0.0.1"]  # loopback: healthcheck
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
PROXY_HEADERS = os.environ.get("PROXY_HEADERS", "1") == "1"  # see kartei.net; 0 if phones reach the relay directly

# hex SHA-256 of the push token Kartei sends as "Authorization: Bearer <token>"; empty = push disabled
RELAY_PUSH_TOKEN_SHA256 = os.environ.get("RELAY_PUSH_TOKEN_SHA256", "").strip().lower()

INSTALLED_APPS = ["relay"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware",
              "django.middleware.common.CommonMiddleware"]  # checks ALLOWED_HOSTS
ROOT_URLCONF = "config.relay_urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = []

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": os.environ.get("RELAY_DB", BASE_DIR / "relay.sqlite3"),
    # pushes write while phones read
    "OPTIONS": {"init_command": "PRAGMA journal_mode=WAL;", "transaction_mode": "IMMEDIATE", "timeout": 20},
}}

USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024  # one push request; Kartei sends chunks of about 2 MB

LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
