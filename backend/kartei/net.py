"""Client address for rate limits. Behind the reverse proxy every request comes from the proxy's address."""
from django.conf import settings


def client_ip(request):
    # the last X-Forwarded-For entry is the one our proxy appended (clients can only spoof the ones before it)
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "") if settings.PROXY_HEADERS else ""
    return fwd.split(",")[-1].strip() or request.META.get("REMOTE_ADDR", "")
