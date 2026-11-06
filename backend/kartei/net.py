"""Client address for rate limits and the audit log. Behind the reverse proxy every request comes from the proxy's address."""
import ipaddress
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
