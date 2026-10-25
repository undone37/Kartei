"""Webhooks: contact changes POSTed to other systems.

Every change to a contact goes through audit.log(), which calls enqueue() in the same transaction, so a change that
is rolled back sends nothing. The exporter delivers due events every few seconds (deliver_due), signed with the
webhook's secret; failures are retried with growing pauses for about a day, then given up.

Payload (JSON): {"id", "event", "occurred_at", "uid", "contact"}; contact is the contact as the REST API returns it,
in its state at sending time (null once it is deleted). Headers: X-Kartei-Event, X-Kartei-Delivery,
X-Kartei-Timestamp and X-Kartei-Signature = "sha256=" + HMAC-SHA256(secret, f"{timestamp}.{body}").
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings as dj
from django.utils import timezone

from .models import AuditEntry, Webhook, WebhookDelivery

log = logging.getLogger(__name__)
TIMEOUT = 10
RETRY_MINUTES = (1, 5, 30, 120, 360, 720)  # after the 7th failed attempt the delivery is given up (about a day)
KEEP_DAYS = 30
EVENT_OF = {"create": "contact.created", "update": "contact.updated", "merge": "contact.updated",
            "delete": "contact.deleted", "restore": "contact.restored"}


def enqueue(entry):
    """Queue the event of an audit entry for every webhook that wants it (called by audit.log)."""
    if entry.target_type != "record":
        return
    event = EVENT_OF.get(entry.action)
    if entry.action == "import":  # an import creates or updates: created if it is the contact's first entry
        first = not AuditEntry.objects.filter(target_type="record", target_id=entry.target_id).exclude(pk=entry.pk).exists()
        event = "contact.created" if first else "contact.updated"
    if not event:
        return
    hooks = [h for h in Webhook.objects.filter(enabled=True) if h.wants(event)]
    if hooks:
        now = timezone.now()
        WebhookDelivery.objects.bulk_create(
            WebhookDelivery(webhook=h, event=event, record_uid=entry.target_id, next_at=now) for h in hooks)


def payload(d):
    from .api import READ, records_qs, visible_fields  # api imports audit, which imports this module
    from .api_v1 import ser_contact
    contact = None
    if d.record_uid:
        r = records_qs().filter(uid=d.record_uid, deleted_at__isnull=True).first()
        contact = ser_contact(r, visible_fields(READ)) if r else None
    return {"id": d.pk, "event": d.event, "occurred_at": d.occurred_at.isoformat(),
            "uid": str(d.record_uid) if d.record_uid else None, "contact": contact}


def signature(secret, timestamp, body):
    return "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def send(hook, event, delivery_id, data):
    """POST one event. Returns (ok, status code or None, error text)."""
    body = json.dumps(data, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    req = Request(hook.url, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"Kartei/{dj.KARTEI_VERSION}",
        "X-Kartei-Event": event, "X-Kartei-Delivery": str(delivery_id), "X-Kartei-Timestamp": ts,
        "X-Kartei-Signature": signature(hook.secret, ts, body)})
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:  # ponytail: system CAs only; add a CA setting if internal TLS needs it
            return True, resp.status, ""
    except HTTPError as e:
        return False, e.code, f"HTTP {e.code}"
    except (URLError, OSError, ValueError) as e:
        return False, None, str(getattr(e, "reason", e))[:300]


def _record(hook, ok, code, error):
    hook.last_status = {"at": timezone.now().isoformat(), "ok": ok, "code": code, "error": error}
    hook.save(update_fields=["last_status"])


def deliver_due(limit=200):
    """Send due deliveries (oldest first). Returns the number sent successfully."""
    sent = 0
    now = timezone.now()
    due = list(WebhookDelivery.objects.filter(status="pending", next_at__lte=now, webhook__enabled=True)
               .select_related("webhook").order_by("pk")[:limit])
    for d in due:
        ok, code, error = send(d.webhook, d.event, d.pk, payload(d))
        d.attempts += 1
        if ok:
            d.status, d.last_error = "delivered", ""
            sent += 1
        elif d.attempts > len(RETRY_MINUTES):
            d.status, d.last_error = "failed", error
            log.warning("webhook %s: gave up delivery %s (%s)", d.webhook.name, d.pk, error)
        else:
            d.next_at, d.last_error = timezone.now() + timedelta(minutes=RETRY_MINUTES[d.attempts - 1]), error
        d.save(update_fields=["status", "attempts", "next_at", "last_error"])
        _record(d.webhook, ok, code, error)
    return sent


def cleanup():
    WebhookDelivery.objects.filter(occurred_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).exclude(status="pending").delete()


def ping(hook):
    """Send a test event right away (Settings → API → Test)."""
    ok, code, error = send(hook, "ping", 0, {"id": 0, "event": "ping", "occurred_at": timezone.now().isoformat(),
                                             "uid": None, "contact": None})
    _record(hook, ok, code, error)
    return {"ok": ok, "code": code, "error": error}


def stats(hook):
    qs = WebhookDelivery.objects.filter(webhook=hook)
    return {"pending": qs.filter(status="pending").count(), "failed": qs.filter(status="failed").count()}
