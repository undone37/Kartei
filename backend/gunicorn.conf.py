"""Gunicorn settings read from the working directory (Kartei and the relay image): with LOG_FORMAT=json (the default)
the request log and gunicorn's own messages are JSON lines like the application's (kartei/logs.py)."""
import os

accesslog = "-"
# X-Forwarded-* only from the reverse proxy (same list as Django's TRUSTED_PROXIES, see config/settings.py)
forwarded_allow_ips = os.environ.get("TRUSTED_PROXIES", "127.0.0.0/8,::1/128,172.16.0.0/12")
if os.environ.get("LOG_FORMAT", "json") == "json":
    logconfig_dict = {
        "formatters": {"json": {"()": "kartei.logs.JsonFormatter"}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
        "loggers": {"gunicorn.error": {"handlers": ["console"], "level": "INFO", "propagate": False},
                    "gunicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False}},
    }
