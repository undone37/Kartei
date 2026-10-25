"""DMZ relay: read-only CardDAV for phones (kartei.dav protocol) + the push endpoint Kartei writes to.

The relay never opens a connection itself. Kartei (inside) calls /push with a bearer token whose SHA-256 is set in
RELAY_PUSH_TOKEN_SHA256; the plain token never needs to exist on the DMZ host.
"""
import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timedelta, timezone as tz

from django.conf import settings
from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from kartei import dav

from .models import Book, Card

ETAG = re.compile(r'"[\w.-]{1,64}"')
MAX_VCARD = 2 * 1024 * 1024  # one card incl. photo
TOMBSTONE_DAYS = 30  # phones that haven't synced for longer start over


class Cards:
    def __init__(self, flavour, book):
        self.flavour, self.book = flavour, book

    def ctag(self):
        return f'"{self.book.ctag}"'

    def etags(self, uid=None):
        qs = Card.objects.filter(deleted=False)
        return [(str(u), e) for u, e in (qs if uid is None else qs.filter(uid=uid)).values_list("uid", "etag")]

    def cards(self, uids=None):
        qs = Card.objects.filter(deleted=False)
        qs = qs if uids is None else qs.filter(uid__in=uids)
        return [(str(u), e, v) for u, e, v in qs.values_list("uid", "etag", self.flavour)]

    def sync_token(self):
        return f"urn:kartei:sync:{int(timezone.now().timestamp() * 1e6)}"

    def changes(self, token):
        m = re.fullmatch(r"urn:kartei:sync:(\d+)", token)
        if not m:
            return None
        since = datetime.fromtimestamp(int(m[1]) / 1e6, tz=tz.utc) - timedelta(seconds=5)
        if self.book.tombstones_since and since < self.book.tombstones_since:
            return None
        cards = Card.objects.filter(changed_at__gte=since)
        return ([str(u) for u in cards.filter(deleted=False).values_list("uid", flat=True)],
                [str(u) for u in cards.filter(deleted=True).values_list("uid", flat=True)])


def well_known(request):
    return dav.well_known(request)


@csrf_exempt
def carddav(request, uid=None):
    b = Book.get()
    return dav.serve(request, uid, b.username, b.password_hash, lambda flavour: Cards(flavour, b))


def _token_ok(request):
    expected = settings.RELAY_PUSH_TOKEN_SHA256
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not expected or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(hashlib.sha256(header[7:].strip().encode()).hexdigest(), expected)


def _bad(reason):
    return JsonResponse({"error": reason}, status=400)


def _uid(value):
    try:
        return str(uuid.UUID(value)) if isinstance(value, str) and len(value) == 36 else None
    except ValueError:
        return None


def _card(c):
    """Validated (uid, etag, ios, android) or None."""
    if not isinstance(c, dict) or set(c) != {"uid", "etag", "ios", "android"}:
        return None
    uid, etag, ios, android = _uid(c["uid"]), c["etag"], c["ios"], c["android"]
    if not uid or not isinstance(etag, str) or not ETAG.fullmatch(etag):
        return None
    for v in (ios, android):
        if not isinstance(v, str) or len(v) > MAX_VCARD or not v.startswith("BEGIN:VCARD"):
            return None
    return uid, etag, ios, android


@csrf_exempt
def push(request):
    """GET: {"cards": {uid: etag}} so Kartei can diff. POST: apply cards/delete/credentials (idempotent)."""
    if not _token_ok(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    if request.method == "GET":
        return JsonResponse({"cards": {str(u): e for u, e in Card.objects.filter(deleted=False).values_list("uid", "etag")}})
    if request.method != "POST":
        return JsonResponse({"error": "method"}, status=405)
    if request.content_type != "application/json":
        return JsonResponse({"error": "json_only"}, status=415)
    try:
        body = json.loads(request.body)
    except RequestDataTooBig:  # DATA_UPLOAD_MAX_MEMORY_SIZE
        return JsonResponse({"error": "too_large"}, status=413)
    except ValueError:
        return _bad("invalid_json")
    if not isinstance(body, dict) or not set(body) <= {"cards", "delete", "credentials"}:
        return _bad("unknown_keys")
    cards = [_card(c) for c in body.get("cards") or []] if isinstance(body.get("cards", []), list) else [None]
    delete = [_uid(u) for u in body.get("delete") or []] if isinstance(body.get("delete", []), list) else [None]
    if None in cards or None in delete:
        return _bad("invalid_card")
    cred = body.get("credentials")
    if cred is not None:
        if not (isinstance(cred, dict) and set(cred) == {"username", "password_hash"}
                and isinstance(cred["username"], str) and 0 < len(cred["username"]) <= 150
                and isinstance(cred["password_hash"], str) and len(cred["password_hash"]) <= 255):
            return _bad("invalid_credentials")
        if cred["password_hash"]:
            try:
                identify_hasher(cred["password_hash"])
            except ValueError:
                return _bad("invalid_credentials")

    with transaction.atomic():
        book = Book.objects.select_for_update().get_or_create(pk=1)[0]
        live = Card.objects.filter(deleted=False)
        have = {str(u): e for u, e in live.filter(uid__in=[c[0] for c in cards]).values_list("uid", "etag")}
        changed = [c for c in cards if have.get(c[0]) != c[1]]
        for uid, etag, ios, android in changed:
            Card.objects.update_or_create(uid=uid, defaults={"etag": etag, "ios": ios, "android": android, "deleted": False})
        # deleted cards become tombstones (without their content) so phones can sync the removal
        now = timezone.now()
        deleted = live.filter(uid__in=delete).update(deleted=True, ios="", android="", changed_at=now) if delete else 0
        old = now - timedelta(days=TOMBSTONE_DAYS)
        if Card.objects.filter(deleted=True, changed_at__lt=old).delete()[0]:
            book.tombstones_since = old
        if changed or deleted:
            book.ctag = uuid.uuid4().hex
        if cred is not None:
            book.username, book.password_hash = cred["username"], cred["password_hash"]
        book.pushed_at = timezone.now()
        book.save()
    return JsonResponse({"ok": True, "updated": len(changed), "deleted": deleted, "total": live.count()})


def not_found(request, exception=None):
    return HttpResponse(status=404)


def server_error(request):
    return HttpResponse(status=500)
