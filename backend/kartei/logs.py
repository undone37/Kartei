"""JSON log lines for the container log and the syslog sender (one object per line, stdlib only)."""
import json
import logging
from datetime import datetime, timezone

_PLAIN = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def record_dict(record):
    """The fields of a log record as a dict: time, level, logger, message, extras (e.g. "audit"), exception."""
    out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
           "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
    out |= {k: v for k, v in vars(record).items() if k not in _PLAIN}
    if record.name == "gunicorn.access" and isinstance(record.args, dict):  # gunicorn passes its atoms as the args
        a = record.args
        out["msg"] = f"{a['m']} {a['U']} {a['s']}"
        out["http"] = {"ip": a["h"], "forwarded_for": a["{x-forwarded-for}i"], "method": a["m"], "path": a["U"],
                       "query": a["q"], "status": a["s"], "bytes": a["B"], "ms": a["M"], "user_agent": a["a"]}
    if record.exc_info:
        out["exc"] = logging.Formatter().formatException(record.exc_info)
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(record_dict(record), ensure_ascii=False, default=str)
