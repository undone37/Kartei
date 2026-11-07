"""Client address for rate limits and the audit log. Behind the reverse proxy every request comes from the proxy's address."""
import base64
import hashlib
import ipaddress
import re
from contextvars import ContextVar
from functools import lru_cache

from django.conf import settings
from django.core.cache import cache

current_ip = ContextVar("current_ip", default=None)  # set per request, read by audit.log


@lru_cache
def _proxies(spec):
    return [ipaddress.ip_network(n, strict=False) for n in spec]


def from_proxy(request):
    """The request comes from a trusted reverse proxy (settings.TRUSTED_PROXIES), so its X-Forwarded-* count."""
    try:
        addr = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return False
    return settings.PROXY_HEADERS and any(addr in n for n in _proxies(tuple(settings.TRUSTED_PROXIES)))


def client_ip(request):
    # the last X-Forwarded-For entry is the one our proxy appended (clients can only spoof the ones before it);
    # only a trusted proxy's header counts, a client talking to Kartei directly could write anything there
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "") if from_proxy(request) else ""
    return fwd.split(",")[-1].strip() or request.META.get("REMOTE_ADDR", "")


def ip_middleware(get_response):
    """Remembers the client address of the running request, so every audit entry carries it."""
    def middleware(request):
        if not from_proxy(request):  # Django reads X-Forwarded-Proto for is_secure(): not from just anyone
            request.META.pop("HTTP_X_FORWARDED_PROTO", None)
        try:
            ip = str(ipaddress.ip_address(client_ip(request)))
        except ValueError:  # empty or junk: no address rather than a failing audit insert
            ip = None
        token = current_ip.set(ip)
        try:
            return get_response(request)
        finally:
            current_ip.reset(token)
    return middleware


def _csp():
    """Content-Security-Policy for the SPA. index.html has one small inline script (theme before the first paint):
    allowed by its hash, read from the built file at startup, so scripts need no 'unsafe-inline'."""
    try:
        html = (settings.FRONTEND_DIST / "index.html").read_text()
    except (OSError, AttributeError):  # no frontend build (API-only tests) or the relay
        html = ""
    hashes = "".join(f" 'sha256-{base64.b64encode(hashlib.sha256(m.encode()).digest()).decode()}'"
                      for m in re.findall(r"<script>(.*?)</script>", html, re.S))
    # style 'unsafe-inline': Svelte sets style attributes (e.g. avatar colours); scripts stay locked down
    return ("default-src 'self'; script-src 'self'" + hashes + "; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def security_headers(get_response):
    """CSP, Permissions-Policy and Cross-Origin-Resource-Policy on every response, static files included
    (listed before WhiteNoise, which answers static requests itself)."""
    csp = _csp()

    def middleware(request):
        response = get_response(request)
        response.setdefault("Content-Security-Policy", csp)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if request.path.startswith("/api/") and not response.has_header("Cache-Control"):
            response["Cache-Control"] = "no-store"  # contact data must not stay in the browser's disk cache
        return response
    return middleware


def count_failure(key, timeout=15 * 60):
    """One more failed attempt for a rate limit; returns the count within the window. The cache is shared by all
    workers of a container (settings.CACHES), so the limit holds across them."""
    if cache.add(key, 1, timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, timeout)
        return 1


def count_distinct_failure(key, attempt, timeout=15 * 60):
    """Like count_failure, but the same wrong credentials count once per window: a phone or script with an old
    password retries all day and must not lock out everybody else behind the same address (office NAT). Guessing
    needs different attempts, and each of those counts. Returns the count (0: a repeat, not counted)."""
    seen = f"{key}:seen:{hashlib.sha256(attempt.encode()).hexdigest()[:24]}"
    return count_failure(key, timeout) if cache.add(seen, 1, timeout) else 0
