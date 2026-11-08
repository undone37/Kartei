"""Web Push: new reviews and proposals as notifications on the user's devices (usually the installed app on a phone).

The browser subscribes with the server's VAPID key (made on first use, stored encrypted in Settings) and Kartei keeps
the subscription (PushSubscription). The exporter calls deliver_due() every few seconds: open reviews and pending
proposals it hasn't looked at yet become one notification per kind and device. Messages are encrypted (RFC 8291,
aes128gcm), signed (RFC 8292, VAPID) and carry only a count and a link, no contact data. No dependency: `cryptography`
does the crypto, urllib the sending. Push is best effort: a failed send is logged, not retried (the list stays in the app).
"""
import base64
import json
import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.db.models import F, Q
from django.utils import timezone

from .models import Proposal, PushSubscription, Review, Settings
from .webhooks import urlopen  # no redirects followed

log = logging.getLogger(__name__)
TIMEOUT = 5
MAX_PER_USER = 20  # oldest subscriptions beyond this are dropped
# the browsers' push services; the server POSTs only there (an endpoint is user input)
PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")
KINDS = ("review", "proposals", "decided")  # a user switches each off in their account (Profile.push_off)
TEXT = {
    "de": {"review": "{n} Kontakte zu prüfen", "review1": "1 Kontakt zu prüfen",
           "proposals": "{n} Vorschläge warten auf Entscheidung", "proposals1": "1 Vorschlag wartet auf Entscheidung",
           "decided": "{n} deiner Vorschläge wurden entschieden", "accepted": "Dein Vorschlag wurde angenommen",
           "rejected": "Dein Vorschlag wurde abgelehnt"},
    "en": {"review": "{n} contacts to review", "review1": "1 contact to review",
           "proposals": "{n} proposals awaiting a decision", "proposals1": "1 proposal awaiting a decision",
           "decided": "{n} of your proposals were decided", "accepted": "Your proposal was accepted",
           "rejected": "Your proposal was rejected"},
}


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _point(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def vapid_key():
    s = Settings.get()
    if pem := s.vapid_private:
        return serialization.load_pem_private_key(pem.encode(), None)
    key, old = ec.generate_private_key(ec.SECP256R1()), s.vapid_private_enc
    s.vapid_private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
    # only if nobody else made one meanwhile (web and exporter process); the old value is also replaced when it can't be
    # read any more (SECRET_KEY changed): browsers then subscribe again with the new key (see frontend lib/push.ts)
    Settings.objects.filter(pk=1, vapid_private_enc=old).update(vapid_private_enc=s.vapid_private_enc)
    return serialization.load_pem_private_key(Settings.get().vapid_private.encode(), None)


def public_key():
    return b64u(_point(vapid_key()))


def clean(sub):
    """The browser's PushSubscription.toJSON() → (endpoint, p256dh, auth), or None if it isn't a usable one."""
    try:
        endpoint, keys = str(sub["endpoint"]), sub["keys"]
        p256dh, auth = str(keys["p256dh"]), str(keys["auth"])
        u = urlsplit(endpoint)
        host = (u.hostname or "").lower()
        if (u.scheme != "https" or len(endpoint) > 1000 or u.port not in (None, 443)
                or not any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)):
            return None
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(p256dh))
        if len(unb64u(auth)) != 16 or len(p256dh) > 100:
            return None
        return endpoint, p256dh, auth
    except (KeyError, TypeError, ValueError):
        return None


def encrypt(p256dh, auth, plaintext, as_key=None, salt=None):
    """RFC 8291 aes128gcm body for one subscription (as_key and salt are only given by the test)."""
    ua_public = unb64u(p256dh)
    as_key = as_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _point(as_key)
    shared = as_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = HKDF(hashes.SHA256(), 32, unb64u(auth), b"WebPush: info\0" + ua_public + as_public).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\0").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\0").derive(ikm)
    header = salt + (4096).to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)


def vapid_header(endpoint, key, sub_claim):
    u = urlsplit(endpoint)
    seg = [b64u(json.dumps(x, separators=(",", ":")).encode()) for x in (
        {"typ": "JWT", "alg": "ES256"},
        {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": sub_claim})]
    r, s = decode_dss_signature(key.sign(".".join(seg).encode(), ec.ECDSA(hashes.SHA256())))
    jwt = ".".join(seg + [b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))])
    return f"vapid t={jwt}, k={b64u(_point(key))}"


def _sub_claim(s):
    # Apple rejects a JWT without a reachable-looking contact; the public address does, else the sender address
    base = (s.base_url or "").rstrip("/")
    return base if base.startswith("https://") else f"mailto:{s.smtp_from or 'kartei@example.org'}"


def send(sub, data, key=None, s=None):
    """POST one notification. Returns True if the push service took it; deletes subscriptions that are gone."""
    s, key = s or Settings.get(), key or vapid_key()
    body = encrypt(sub.p256dh, sub.auth, json.dumps(data).encode())
    req = Request(sub.endpoint, data=body, method="POST", headers={
        "Authorization": vapid_header(sub.endpoint, key, _sub_claim(s)), "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream", "TTL": "86400", "Urgency": "normal", "Topic": data["tag"]})
    try:
        with urlopen(req, timeout=TIMEOUT):
            return True
    except HTTPError as e:
        if e.code in (404, 410):  # unsubscribed or expired
            sub.delete()
        else:
            log.warning("push to %s failed: HTTP %s %s", urlsplit(sub.endpoint).hostname, e.code, e.read(300))
    except (URLError, OSError) as e:
        log.warning("push to %s failed: %s", urlsplit(sub.endpoint).hostname, e)
    return False


def _lang(u, s):
    return getattr(getattr(u, "profile", None), "language", "") or s.default_language


def _messages(u, lang, reviews, props, decided):
    """The notifications for one user: [{title, body, tag, url}], without the kinds they switched off."""
    w, out = TEXT.get(lang, TEXT["de"]), []
    off = getattr(getattr(u, "profile", None), "push_off", None) or []
    counts = {"review": sum(1 for _, a in reviews if a == u.id)}
    if u.is_superuser or getattr(getattr(u, "profile", None), "role", "") in ("maintainer", "admin"):
        counts["proposals"] = sum(1 for _, p in props if p != u.id)  # nobody needs news about their own
    for kind, n in counts.items():
        if n and kind not in off:
            out.append({"body": w[kind + "1"] if n == 1 else w[kind].format(n=n), "tag": kind, "url": f"/?list={kind}"})
    mine = [d for d in decided if d[1] == u.id]
    if mine and "decided" not in off:
        _, _, status, kind, uid = mine[0]
        one = len(mine) == 1
        out.append({"body": w[status] if one else w["decided"].format(n=len(mine)), "tag": "decided",
                    "url": f"/{kind}/{uid}" if one and uid else "/"})  # accepted: the contact; a rejected new one has none
    return [{"title": "Kartei"} | m for m in out]


def deliver_due():
    """Push what's new since the last call: open reviews to their assignee, pending proposals (new or edited) to the
    maintainers and admins except the proposer, decisions to the proposer. Returns the number of notifications sent."""
    now = timezone.now()  # taken before reading: whatever arrives while sending is pushed next time
    reviews = list(Review.objects.filter(done_at__isnull=True, pushed_at__isnull=True, record__deleted_at__isnull=True)
                   .values_list("pk", "assignee_id"))
    props = list(Proposal.objects.filter(Q(record__isnull=True) | Q(record__deleted_at__isnull=True), status="pending")
                 .filter(Q(pushed_at__isnull=True) | Q(pushed_at__lt=F("updated_at"))).values_list("pk", "proposer_id"))
    decided = list(Proposal.objects.filter(status__in=("accepted", "rejected"), decided_at__isnull=False)
                   .filter(Q(pushed_at__isnull=True) | Q(pushed_at__lt=F("decided_at")))
                   .exclude(decided_by=F("proposer"))  # decided their own: no news either
                   .values_list("pk", "proposer_id", "status", "record__kind", "record__uid").order_by("decided_at"))
    if not reviews and not props and not decided:
        return 0
    subs = {}
    for sub in PushSubscription.objects.filter(user__is_active=True).select_related("user__profile"):
        subs.setdefault(sub.user, []).append(sub)
    s, sent = Settings.get(), 0
    key = vapid_key() if subs else None
    for u, devices in subs.items():
        for m in _messages(u, _lang(u, s), reviews, props, decided):
            sent += sum(send(d, m, key, s) for d in devices)
    Review.objects.filter(pk__in=[pk for pk, _ in reviews]).update(pushed_at=now)
    Proposal.objects.filter(pk__in=[pk for pk, _ in props] + [d[0] for d in decided]).update(pushed_at=now)
    return sent


def subscribe(user, sub):
    """Keep (or move to this user: shared device) a subscription. Returns False if it isn't a usable one."""
    if not (c := clean(sub)):
        return False
    endpoint, p256dh, auth = c
    PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={"user": user, "p256dh": p256dh, "auth": auth})
    old = PushSubscription.objects.filter(user=user).order_by("-created_at").values_list("pk", flat=True)[MAX_PER_USER:]
    PushSubscription.objects.filter(pk__in=list(old)).delete()
    return True


def unsubscribe(user, endpoint):
    PushSubscription.objects.filter(user=user, endpoint=str(endpoint)).delete()


def send_test(user):
    """Send a test notification to all of the user's devices; returns how many took it."""
    s = Settings.get()
    msg = {"title": "Kartei", "body": "Test", "tag": "test", "url": "/account"}
    return sum(send(d, msg, s=s) for d in PushSubscription.objects.filter(user=user))
