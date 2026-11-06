"""Client address for rate limits and the audit log. Behind the reverse proxy every request comes from the proxy's address."""
import base64
import hashlib
import ipaddress
import re
from contextvars import ContextVar

from django.conf import settings

current_ip = ContextVar("current_ip", default=None)  # set per request, read by audit.log


def client_ip(request):
    # the last X-Forwarded-For entry is the one our proxy appended (clients can only spoof the ones before it)
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "") if settings.PROXY_HEADERS else ""
    return fwd.split(",")[-1].strip() or request.META.get("REMOTE_ADDR", "")


def ip_middleware(get_response):
    """Remembers the client address of the running request, so every audit entry carries it."""
    def middleware(request):
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
        return response
    return middleware
