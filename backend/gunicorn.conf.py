"""Gunicorn settings read from the working directory (Kartei and the relay image): with LOG_FORMAT=json (the default)
the request log and gunicorn's own messages are JSON lines like the application's (kartei/logs.py)."""
import os
import sys

if os.environ.get("DEBUG") == "1":  # DEBUG shows tracebacks and allows a built-in SECRET_KEY: never on a server
    raise RuntimeError("DEBUG=1 is for development only (manage.py runserver); remove it from .env")

accesslog = "-"
# X-Forwarded-* only from the reverse proxy (same list as Django's TRUSTED_PROXIES, see config/proxies.py)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.proxies import trusted  # noqa: E402

forwarded_allow_ips = ",".join(trusted(os.environ.get("TRUSTED_PROXIES", "auto")))
if os.environ.get("LOG_FORMAT", "json") == "json":
    logconfig_dict = {
        "formatters": {"json": {"()": "kartei.logs.JsonFormatter"}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
        "loggers": {"gunicorn.error": {"handlers": ["console"], "level": "INFO", "propagate": False},
                    "gunicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False}},
    }
