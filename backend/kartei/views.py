from django.conf import settings
from django.http import FileResponse, HttpResponse, HttpResponseNotFound, HttpResponsePermanentRedirect
from django.views.decorators.cache import never_cache

from .api import rank_of, visible_fields
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
    """/crm/... (old name) -> /..."""
    qs = request.META.get("QUERY_STRING", "")
    return HttpResponsePermanentRedirect("/" + (rest or "") + (f"?{qs}" if qs else ""))


@never_cache
def service_worker(request):
    """Served from the site root (not /static/) so its scope covers the whole app."""
    sw = settings.FRONTEND_DIST / "sw.js"
    if not sw.exists():
        return HttpResponseNotFound()
    return FileResponse(open(sw, "rb"), content_type="text/javascript")


def vcf(request, kind, uid):
    """The SOURCE: link in every vCard. Session login required; fields filtered by the user's role."""
    if not request.user.is_authenticated:
        return spa(request)  # SPA shows login, then reloads this URL
    r = Record.objects.filter(uid=uid, kind=kind, deleted_at__isnull=True).select_related("company").first()
    if not r:
        return HttpResponseNotFound()
    body = render(r, visible_fields(rank_of(request.user)), flavour_for(request.META.get("HTTP_USER_AGENT")),
                  Settings.get().base_url, ref_names())
    resp = HttpResponse(body, content_type="text/vcard; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{r.display_name or r.uid}.vcf"'.encode("ascii", "replace").decode()
    return resp
