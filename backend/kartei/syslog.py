"""Audit events (and optionally application warnings) to a SIEM: RFC 5424 syslog with the JSON log record as message.

UDP sends one datagram per event; TCP and TLS use octet-counting framing (RFC 6587). A handler on the root logger
queues the events and a daemon thread per process sends them, so a slow or unreachable SIEM never blocks a request.
The thread re-reads the settings every minute (and right after an admin saves them in this process); while the SIEM
is unreachable it keeps the event, retries with backoff and drops new events once the queue is full (counted).
ponytail: per-process sender (gunicorn workers, exporter); a central relay only if workers multiply.
"""
import json
import logging
import os
import queue
import socket
import ssl
import threading
import time
from datetime import datetime, timezone

from django.db import close_old_connections
from django.utils import timezone as djtz

from .logs import record_dict

FACILITIES = {"kern": 0, "user": 1, "daemon": 3, "auth": 4, "authpriv": 10, "local0": 16, "local1": 17, "local2": 18,
              "local3": 19, "local4": 20, "local5": 21, "local6": 22, "local7": 23}
SEVERITY = {"CRITICAL": 2, "ERROR": 3, "WARNING": 4, "INFO": 6, "DEBUG": 7}
AUDIT = "kartei.audit"
QUEUE_MAX, REFRESH, TIMEOUT = 10_000, 60, 5
HOST = socket.gethostname()


UDP_MAX = 8000  # bytes per datagram; bigger ones fail (or get fragmented and lost) on the way to the SIEM


def line(rec, facility, limit=None):
    """One RFC 5424 message: <PRI>1 TIMESTAMP HOST APP PROCID MSGID - JSON. limit: shorten the JSON to fit (UDP):
    first without the changed values (e.g. a whole email template), then the message text itself."""
    pri = FACILITIES.get(facility, 16) * 8 + SEVERITY.get(rec["level"], 6)
    msgid = "audit" if rec["logger"] == AUDIT else "app"
    head = f"<{pri}>1 {rec['ts']} {HOST} kartei {os.getpid()} {msgid} - "
    body = json.dumps(rec, ensure_ascii=False, default=str)
    if limit and len(head.encode()) + len(body.encode()) > limit:
        rec = {**rec, "truncated": True, "exc": str(rec.get("exc", ""))[:1000] or None}
        if isinstance(rec.get("audit"), dict):
            rec["audit"] = {**rec["audit"], "changes": sorted(rec["audit"].get("changes") or [])}  # names only
        body = json.dumps(rec, ensure_ascii=False, default=str)
        if len(head.encode()) + len(body.encode()) > limit:
            rec["msg"] = str(rec.get("msg", ""))[:500]
            body = json.dumps({k: rec[k] for k in ("ts", "level", "logger", "msg", "truncated") if k in rec},
                              ensure_ascii=False, default=str)
    return (head + body).encode()


def frame(data, protocol):
    return data if protocol == "udp" else str(len(data)).encode() + b" " + data


def config(s):
    return {"enabled": s.syslog_enabled and bool(s.syslog_host), "host": s.syslog_host, "port": s.syslog_port,
            "protocol": s.syslog_protocol, "ca": s.syslog_ca_cert.strip(), "verify": s.syslog_tls_verify,
            "facility": s.syslog_facility, "content": s.syslog_content}


def connect(cfg):
    """A send(bytes) callable plus close() for the configured target; raises OSError/ssl.SSLError."""
    family, kind, proto, _, addr = socket.getaddrinfo(
        cfg["host"], cfg["port"], type=socket.SOCK_DGRAM if cfg["protocol"] == "udp" else socket.SOCK_STREAM)[0]
    sock = socket.socket(family, kind, proto)
    sock.settimeout(TIMEOUT)
    try:
        if cfg["protocol"] == "udp":
            sock.connect(addr)
            return sock
        sock.connect(addr)
        if cfg["protocol"] == "tls":
            ctx = ssl.create_default_context(cadata=cfg["ca"] or None)
            if not cfg["verify"]:
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=cfg["host"])
        return sock
    except BaseException:
        sock.close()
        raise


def send_test(s):
    """Settings check for the admin UI: one test event, sent synchronously. Returns None or the error text."""
    cfg = config(s)
    if not cfg["host"]:
        return "syslog_no_host"
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "level": "INFO", "logger": AUDIT,
           "msg": "test", "audit": {"event": "test", "area": "settings", "object": "syslog"}}
    try:
        sock = connect(cfg)
        try:
            sock.sendall(frame(line(rec, cfg["facility"], UDP_MAX if cfg["protocol"] == "udp" else None), cfg["protocol"]))
        finally:
            sock.close()
    except (OSError, ssl.SSLError, ValueError) as e:
        return str(e) or type(e).__name__
    return None


class Sender(threading.Thread):
    def __init__(self):
        super().__init__(name="kartei-syslog", daemon=True)
        self.queue = queue.Queue(QUEUE_MAX)
        self.cfg = None  # unknown until the first refresh: events are queued meanwhile
        self.refresh_at = 0.0
        self.sent = self.dropped = 0
        self.error = ""
        self.status_at = 0.0

    def wants(self, record):
        if record.name.startswith("kartei.syslog"):
            return False  # never our own complaints
        if self.cfg is not None and not self.cfg["enabled"]:
            return False
        if record.name == AUDIT:
            return True
        if record.name == "django.request" and getattr(record, "status_code", 500) < 500:
            return False  # every 401/404 is a warning there; sign-in failures arrive as audit events instead
        return (self.cfg or {}).get("content", "audit_and_app") == "audit_and_app" and record.levelno >= logging.WARNING

    def put(self, rec):
        try:
            self.queue.put_nowait(rec)
        except queue.Full:
            self.dropped += 1

    def reload(self):
        self.refresh_at = 0.0

    def _refresh(self):
        from .models import Settings
        close_old_connections()
        try:
            new = config(Settings.get())
        except Exception:  # database not reachable or not migrated yet: try again next round
            return
        finally:
            close_old_connections()
        self.cfg = new
        self.refresh_at = time.monotonic() + REFRESH

    def _report(self, force=False):
        """Status for the settings page and the monitoring endpoint, at most once a minute."""
        if not force and time.monotonic() - self.status_at < 60:
            return
        from .models import Settings
        self.status_at = time.monotonic()
        now = djtz.now().isoformat()
        status = {"at": now, "sent": self.sent, "dropped": self.dropped, "error": self.error}
        status |= {"error_at": now} if self.error else {"ok_at": now}
        try:
            Settings.objects.filter(pk=1).update(syslog_status=status)
        except Exception:
            pass
        finally:
            close_old_connections()

    def run(self):
        sock, pending, backoff = None, None, 1
        while True:
            if time.monotonic() >= self.refresh_at:
                old = self.cfg
                self._refresh()
                if sock and old != self.cfg:
                    sock.close()
                    sock = None
            if pending is None:
                try:
                    pending = self.queue.get(timeout=5)
                except queue.Empty:
                    continue
            cfg = self.cfg
            if cfg is None:
                time.sleep(1)  # settings not readable yet
                continue
            if not cfg["enabled"] or (pending["logger"] != AUDIT and cfg["content"] != "audit_and_app"):
                pending = None
                continue
            try:
                sock = sock or connect(cfg)
                sock.sendall(frame(line(pending, cfg["facility"], UDP_MAX if cfg["protocol"] == "udp" else None), cfg["protocol"]))
                self.sent, pending, backoff = self.sent + 1, None, 1
                if self.error:
                    self.error = ""
                    self._report(force=True)
            except (OSError, ssl.SSLError, ValueError) as e:
                if sock:
                    sock.close()
                sock = None
                first = not self.error
                self.error = str(e) or type(e).__name__
                if first:
                    self._report(force=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            self._report()


class Handler(logging.Handler):
    """Hands matching records to the sender thread, started on first use."""
    sender = None
    lock = threading.Lock()

    def emit(self, record):
        try:
            if Handler.sender is None:
                with Handler.lock:
                    if Handler.sender is None:
                        Handler.sender = Sender()
                        Handler.sender.start()
            if Handler.sender.wants(record):
                Handler.sender.put(record_dict(record))
        except Exception:
            self.handleError(record)


def reload(s):
    """After the admin saved the settings: this process uses them at once (other processes within a minute)."""
    if Handler.sender:
        Handler.sender.cfg = config(s)
        Handler.sender.reload()
