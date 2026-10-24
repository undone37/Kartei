"""Push the CardDAV cards to the relay in the DMZ (relay app, separate host). Kartei connects out; the relay never in.

Each run (exporter, at the export interval, or "sync now") asks the relay which cards it has ({uid: etag}), then sends
the changed cards (both vCard flavours, rendered here), the uids to delete and the CardDAV login (username + password
hash). The etag is the built-in server's etag, so a card is only re-rendered when it changed. Comparing against the
relay's real state makes every run a full sync: strays and lost cards are fixed without a separate cursor.
Guards: nothing is pushed with 0 contacts, nor when more than carddav_relay_max_delete_percent would be deleted.
"""
import hashlib
import json
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.utils import timezone

from .carddav import _etag, _fields, _records, _schema_hash
from .models import Settings, ref_names
from .msg import msg
from .vcard import render

CHUNK = 2 * 1024 * 1024  # bytes of vCards per request (the relay accepts up to 16 MB)


class RelayError(Exception):
    pass


def _context(s):
    if not s.carddav_relay_tls_verify:
        return ssl._create_unverified_context()
    if s.carddav_relay_ca_cert.strip():
        return ssl.create_default_context(cadata=s.carddav_relay_ca_cert.strip() + "\n")
    return ssl.create_default_context()


def call(s, method, body=None):
    """One request to <relay>/push. Returns the parsed JSON answer."""
    if not (s.carddav_relay_url and s.carddav_relay_token):
        raise RelayError(msg("relay_not_configured"))
    headers, data = {"Authorization": f"Bearer {s.carddav_relay_token}"}, None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    try:
        req = Request(s.carddav_relay_url.rstrip("/") + "/push", data, headers, method=method)
        with urlopen(req, timeout=60, context=_context(s)) as r:
            return json.loads(r.read() or b"{}")
    except HTTPError as e:
        raise RelayError(msg("relay_unauthorized") if e.code == 401 else f"HTTP {e.code}: {e.reason}")
    except URLError as e:
        raise RelayError(str(e.reason))
    except (OSError, ValueError) as e:  # TLS/CA errors, timeouts, broken JSON
        raise RelayError(str(e))


def token_sha256(s):
    return hashlib.sha256(s.carddav_relay_token.encode()).hexdigest() if s.carddav_relay_token_enc else ""


def _sync(s):
    fields, names = _fields(), ref_names()
    schema = _schema_hash(fields, s, names)
    wanted = {str(r.uid): _etag(r, schema) for r in _records().defer("image")}
    if not wanted:  # never wipe the phones because of an empty database
        raise RelayError(msg("relay_no_records"))
    have = call(s, "GET").get("cards", {})
    delete = sorted(set(have) - set(wanted))
    if have and len(delete) > len(have) * s.carddav_relay_max_delete_percent / 100:
        raise RelayError(msg("relay_too_many_deletes", n=len(delete), total=len(have),
                             limit=s.carddav_relay_max_delete_percent))
    changed = [u for u, e in wanted.items() if have.get(u) != e]
    cred = {"username": s.carddav_username, "password_hash": s.carddav_password_hash}
    out, batch, size = {"updated": 0, "deleted": 0, "total": len(have)}, [], 0

    def send(cards, delete=()):
        res = call(s, "POST", {"cards": cards, "delete": list(delete), "credentials": cred})
        out["updated"] += res.get("updated", 0)
        out["deleted"] += res.get("deleted", 0)
        out["total"] = res.get("total", out["total"])

    for i in range(0, len(changed), 500):  # bounded query size; rendered cards are sent in ~CHUNK requests
        for r in _records().filter(uid__in=changed[i:i + 500]):
            ios, android = (render(r, fields, f, s.base_url, names) for f in ("ios", "android"))
            batch.append({"uid": str(r.uid), "etag": _etag(r, schema), "ios": ios, "android": android})
            size += len(ios) + len(android)
            if size >= CHUNK:
                send(batch, delete)
                batch, size, delete = [], 0, ()
    send(batch, delete)  # also when nothing changed: keeps the login current
    return out


def run():
    """Exporter tick. Returns the status dict, or None when disabled."""
    Settings.objects.filter(pk=1).update(carddav_relay_requested=None)
    s = Settings.get()
    if not s.carddav_relay_enabled:
        return None
    started = time.monotonic()
    try:
        status = _sync(s)
    except RelayError as e:
        status = {"error": str(e)}
    status |= {"at": timezone.now().isoformat(), "seconds": round(time.monotonic() - started, 1)}
    Settings.objects.filter(pk=1).update(carddav_relay_status=status)  # not save(): don't clobber admin edits
    return status


def test(s):
    """Settings check for the admin UI: reach the relay and authenticate, no writes."""
    try:
        return {"ok": True, "cards": len(call(s, "GET").get("cards", {}))}
    except RelayError as e:
        return {"error": str(e)}


def validate(s):
    errors = {}
    url = str(s.carddav_relay_url or "").strip()
    s.carddav_relay_url = url
    if url and not (url.startswith("https://") and len(url) > 8 and " " not in url):
        errors["carddav_relay_url"] = "invalid_url"  # https only: the request carries the push token
    if not isinstance(s.carddav_relay_max_delete_percent, int) or not 0 <= s.carddav_relay_max_delete_percent <= 100:
        errors["carddav_relay_max_delete_percent"] = "invalid_number"
    s.carddav_relay_ca_cert = str(s.carddav_relay_ca_cert or "")
    if s.carddav_relay_ca_cert.strip():
        try:
            ssl.create_default_context(cadata=s.carddav_relay_ca_cert.strip() + "\n")
        except (ssl.SSLError, ValueError):
            errors["carddav_relay_ca_cert"] = "invalid"
    s.carddav_relay_enabled, s.carddav_relay_tls_verify = bool(s.carddav_relay_enabled), bool(s.carddav_relay_tls_verify)
    if s.carddav_relay_enabled and not (url and s.carddav_relay_token_enc):
        errors["carddav_relay_enabled"] = "relay_incomplete"
    return errors


def ser(s):
    return {"carddav_relay_token_sha256": token_sha256(s), "carddav_relay_status": s.carddav_relay_status,
            "carddav_relay_requested": s.carddav_relay_requested}
