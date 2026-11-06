"""Gunicorn settings read from the working directory (Kartei and the relay image): with LOG_FORMAT=json (the default)
the request log and gunicorn's own messages are JSON lines like the application's (kartei/logs.py)."""
import os

accesslog = "-"
if os.environ.get("LOG_FORMAT", "json") == "json":
    logconfig_dict = {
        "formatters": {"json": {"()": "kartei.logs.JsonFormatter"}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
        "loggers": {"gunicorn.error": {"handlers": ["console"], "level": "INFO", "propagate": False},
                    "gunicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False}},
    }
