import re

from django.conf import settings
from django.http import FileResponse, HttpResponse, HttpResponseNotFound, HttpResponsePermanentRedirect
from django.views.decorators.cache import never_cache

from .api import rank_of, totp_due, visible_fields
from .models import Record, Settings, ref_names
from .vcard import flavour_for, render


@never_cache
def spa(request, *args, **kwargs):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse("Frontend not built. Run `npm run build` in frontend/ or use the Vite dev server.",
                            status=503, content_type="text/plain")
    return FileResponse(open(index, "rb"), content_type="text/html")


def legacy_redirect(request, rest=""):
    """/crm/... (old name) -> /... on this site. Leading slashes and backslashes go: "/crm//evil.example" would
    otherwise redirect to //evil.example, another host."""
    qs = request.META.get("QUERY_STRING", "")
    return HttpResponsePermanentRedirect("/" + (rest or "").lstrip("/\\") + (f"?{qs}" if qs else ""))


@never_cache
def service_worker(request):
    """Served from the site root (not /static/) so its scope covers the whole app."""
    sw = settings.FRONTEND_DIST / "sw.js"
    if not sw.exists():
        return HttpResponseNotFound()
    return FileResponse(open(sw, "rb"), content_type="text/javascript")


def vcf(request, kind, uid):
    """The SOURCE: link in every vCard. Session login required; fields filtered by the user's role.
    ?qr=1: without photo and shown inline (the share dialog turns it into a QR code); ?flavour=ios|android picks the
    phone flavour instead of the browser's."""
    if not request.user.is_authenticated:
        return spa(request)  # SPA shows login, then reloads this URL
    if not request.user.is_active or totp_due(request.user, request):  # like every API call: 2FA set up first
        return spa(request)
    r = Record.objects.filter(uid=uid, kind=kind, deleted_at__isnull=True).select_related("company").first()
    if not r:
        return HttpResponseNotFound()
    flavour = request.GET.get("flavour")
    if flavour not in ("ios", "android"):
        flavour = flavour_for(request.META.get("HTTP_USER_AGENT"))
    qr = request.GET.get("qr") == "1"
    body = render(r, visible_fields(rank_of(request.user)), flavour, Settings.get().base_url, ref_names(), photo=not qr)
    if qr:  # a scanning phone needs neither Kartei's UID nor the source link: a smaller, easier to scan code
        body = re.sub(r"(?m)^(UID|SOURCE):.*\r\n(?: .*\r\n)*", "", body)
    resp = HttpResponse(body, content_type="text/vcard; charset=utf-8")
    if not qr:
        resp["Content-Disposition"] = f'attachment; filename="{r.display_name or r.uid}.vcf"'.encode("ascii", "replace").decode()
    return resp
