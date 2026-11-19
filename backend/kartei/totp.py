"""Time-based one-time passwords (RFC 6238, as used by authenticator apps) and one-time recovery codes.

Standard library only: HMAC-SHA1, 30 s steps, 6 digits. verify() accepts the previous, current and next step
(clock drift) and never the same step twice, so an observed code can't be replayed.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP, DIGITS, WINDOW = 30, 6, 1


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def verify(secret, code, last_counter=None, now=None):
    """The step the code belongs to, or None. Codes of last_counter or earlier are refused (no replay)."""
    code = "".join(str(code or "").split())
    if not secret or len(code) != DIGITS or not (code.isascii() and code.isdigit()):  # "١٢٣٤٥٦" is digits too
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for counter in range(current - WINDOW, current + WINDOW + 1):
        if (last_counter is None or counter > last_counter) and hmac.compare_digest(code_at(secret, counter), code):
            return counter
    return None


def uri(secret, account, issuer="Kartei"):
    """otpauth:// link for the QR code an authenticator app scans."""
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def new_recovery_codes(n=8):
    """(codes to show once, their hashes to store). 80 bits each."""
    codes = [f"{secrets.token_hex(5)}-{secrets.token_hex(5)}" for _ in range(n)]
    return codes, [hash_recovery(c) for c in codes]


def _norm(code):
    return "".join(str(code).lower().split())


def hash_recovery(code):
    """Keyed with the SECRET_KEY (like the encrypted TOTP secret): a copy of the database alone can't be used to
    work out a code offline."""
    from django.conf import settings
    key = hashlib.sha256(("kartei-recovery:" + settings.SECRET_KEY).encode()).digest()
    return "h2:" + hmac.new(key, _norm(code).encode(), hashlib.sha256).hexdigest()


def match_recovery(stored, code):
    """The stored hash `code` matches, or None. Plain SHA-256 hashes from before 0.8.5 still count until the user
    makes new codes (they can't be converted without the codes)."""
    new, old = hash_recovery(code), hashlib.sha256(_norm(code).encode()).hexdigest()
    return next((h for h in stored if hmac.compare_digest(h, new if h.startswith("h2:") else old)), None)


def legacy_recovery(stored):
    return any(not h.startswith("h2:") for h in stored)
