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
    if not secret or len(code) != DIGITS or not code.isdigit():
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
    """(codes to show once, their hashes to store)."""
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]
    return codes, [hash_recovery(c) for c in codes]


def hash_recovery(code):
    return hashlib.sha256("".join(str(code).lower().split()).encode()).hexdigest()
