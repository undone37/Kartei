"""DMZ relay: read-only CardDAV for phones (kartei.dav protocol) + the push endpoint Kartei writes to.

The relay never opens a connection itself. Kartei (inside) calls /push with a bearer token whose SHA-256 is set in
RELAY_PUSH_TOKEN_SHA256; the plain token never needs to exist on the DMZ host.
"""
import hashlib
import hmac
import json
import re
import uuid

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


class Cards:
    def __init__(self, flavour, ctag):
        self.flavour, self._ctag = flavour, ctag

    def ctag(self):
        return f'"{self._ctag}"'

    def etags(self, uid=None):
        qs = Card.objects.all() if uid is None else Card.objects.filter(uid=uid)
        return [(str(u), e) for u, e in qs.values_list("uid", "etag")]

    def cards(self, uids=None):
        qs = Card.objects.all() if uids is None else Card.objects.filter(uid__in=uids)
        return [(str(u), e, v) for u, e, v in qs.values_list("uid", "etag", self.flavour)]


def well_known(request):
    return dav.well_known(request)


@csrf_exempt
def carddav(request, uid=None):
    b = Book.get()
    return dav.serve(request, uid, b.username, b.password_hash, lambda flavour: Cards(flavour, b.ctag))


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
        return JsonResponse({"cards": {str(u): e for u, e in Card.objects.values_list("uid", "etag")}})
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
        have = dict(Card.objects.filter(uid__in=[c[0] for c in cards]).values_list("uid", "etag"))
        have = {str(u): e for u, e in have.items()}
        changed = [c for c in cards if have.get(c[0]) != c[1]]
        for uid, etag, ios, android in changed:
            Card.objects.update_or_create(uid=uid, defaults={"etag": etag, "ios": ios, "android": android})
        deleted = Card.objects.filter(uid__in=delete).delete()[0] if delete else 0
        if changed or deleted:
            book.ctag = uuid.uuid4().hex
        if cred is not None:
            book.username, book.password_hash = cred["username"], cred["password_hash"]
        book.pushed_at = timezone.now()
        book.save()
    return JsonResponse({"ok": True, "updated": len(changed), "deleted": deleted, "total": Card.objects.count()})


def not_found(request, exception=None):
    return HttpResponse(status=404)


def server_error(request):
    return HttpResponse(status=500)
