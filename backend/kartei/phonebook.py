"""Phonebook for desk phones and number lookup for phone systems.

- /phonebook/yealink.xml, /phonebook/snom.xml, /phonebook/grandstream.xml: the contacts in each brand's remote
  phonebook format; ?q= narrows them down (the phones' remote search sends what was typed).
- /phonebook/swyx.csv: the same for SwyxWare's Global Phonebook import (caller names on all Swyx phones).
- /phonebook/lookup?number=…: who is calling, as "Name · Company" (text) or JSON (?format=json), for the caller
  display of a phone system (3CX, Starface, Asterisk …).

Same contacts and fields as CardDAV (what Read Only users see), only numbers with a phone vCard target, no fax.
Its own Basic login (Settings → Phones), optionally limited to certain addresses."""
import re
import time
import unicodedata
from xml.sax.saxutils import escape, quoteattr

from django.db.models import Count, Max
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import audit, dav, monitoring
from .batch import MIN_PREFIX, national
from .models import FieldDef, Record, Settings
from .net import client_ip

DIAL = ("tel_work", "tel_custom", "tel_cell", "tel_home", "tel_assistant")  # no fax: a phone can't call one
KIND = {"tel_cell": "Cell", "tel_home": "Home"}  # Grandstream's phone types; everything else is Work
_cache = {"stamp": None, "at": 0.0}
FRESH = 60  # seconds a built phonebook is used without checking for changes


def _fold(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def _key(v, cc):
    """Comparable digits: national for the default country code, other countries without their 00/+."""
    d = national(v, cc)[0]
    return d[2:] if d.startswith("00") else d


def entries():
    """All contacts with a dialable number, plus the number index. Rebuilt when a contact or field changed, checked at
    most once a minute: with 50 000 contacts a rebuild takes seconds, a phone system's caller lookup can't wait that
    long on every change. # ponytail: per-process cache, a few MB; one rebuild per minute and worker at most"""
    if _cache["stamp"] is not None and time.monotonic() - _cache["at"] < FRESH:
        return _cache["entries"], _cache["index"]
    s = Settings.get()
    live = Record.objects.filter(deleted_at__isnull=True)
    stamp = (live.aggregate(n=Count("id"), t=Max("updated_at")), FieldDef.objects.aggregate(t=Max("id"), n=Count("id")),
             s.phone_country_code, s.default_language, list(FieldDef.objects.filter(vcard__in=DIAL).values_list(
                 "key", "archived", "visible_to", "label_de", "label_en", "vcard_label", "applies_to")))
    if _cache["stamp"] == stamp:
        _cache["at"] = time.monotonic()
        return _cache["entries"], _cache["index"]
    fields = [f for f in FieldDef.objects.filter(archived=False, visible_to="read", vcard__in=DIAL, type="phone")
              .order_by("order", "id")]
    label = lambda f: f.vcard_label or (f.label_en if s.default_language == "en" else f.label_de) or f.label_de
    out, index = [], {}
    for r in live.select_related("company").order_by("last_name", "first_name", "name", "id"):
        nums = [(label(f), f.vcard, str(r.data[f.key]).strip()) for f in fields
                if f.applies(r.kind) and str(r.data.get(f.key) or "").strip()]
        if not nums:
            continue
        e = {"uid": str(r.uid), "kind": r.kind, "name": r.display_name,
             "first": r.first_name if r.kind == "person" else "", "last": r.last_name if r.kind == "person" else r.name,
             "company": r.company.name if r.kind == "person" and r.company else "", "numbers": nums}
        e["text"] = _fold(f"{e['name']} {e['company']}")
        e["digits"] = [_key(n, s.phone_country_code) for _, _, n in nums]
        out.append(e)
        for d in e["digits"]:
            index.setdefault(d, e)  # the first contact with a number keeps it (sorted by name: stable)
    _cache.update(stamp=stamp, entries=out, index=index, at=time.monotonic())
    return out, index


def find(number):
    """The contact for an incoming number: exactly, or else the longest stored number it starts with (a company's
    switchboard for an unknown extension)."""
    s = Settings.get()
    k = _key(number, s.phone_country_code)
    if len(k) < 3:
        return None
    _, index = entries()
    if k in index:
        return index[k]
    for i in range(len(k) - 1, MIN_PREFIX - 1, -1):
        if k[:i] in index:
            return index[k[:i]]
    return None


def _search(items, q):
    words = _fold(q).split()
    digits = re.sub(r"\D", "", q)
    if not words:
        return items
    if digits and len(digits) >= 3 and len(digits) >= len(q.replace(" ", "")) - 2:  # a number was typed
        return [e for e in items if any(digits in d for d in e["digits"])]
    return [e for e in items if all(w in e["text"] for w in words)]


def _dial(n):
    return re.sub(r"[^\d+*#]", "", n)


def _title(e):
    return f"{e['name']} – {e['company']}" if e["company"] else e["name"]


def yealink(items):
    rows = []
    for e in items:
        tel = "".join(f"<Telephone label={quoteattr(label)}>{escape(_dial(n))}</Telephone>" for label, _, n in e["numbers"])
        rows.append(f"<DirectoryEntry><Name>{escape(_title(e))}</Name>{tel}</DirectoryEntry>")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<YealinkIPPhoneDirectory>{"".join(rows)}</YealinkIPPhoneDirectory>\n'


def snom(items):
    # Snom shows one number per entry: "Name – Company (Mobil)"
    rows = [f"<DirectoryEntry><Name>{escape(_title(e))} ({escape(label)})</Name><Telephone>{escape(_dial(n))}</Telephone>"
            "</DirectoryEntry>" for e in items for label, _, n in e["numbers"]]
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<SnomIPPhoneDirectory><Title>Kartei</Title>{"".join(rows)}'
            "</SnomIPPhoneDirectory>\n")


def grandstream(items):
    rows = []
    for e in items:
        tel = "".join(f'<Phone type="{KIND.get(t, "Work")}"><phonenumber>{escape(_dial(n))}</phonenumber>'
                      "<accountindex>1</accountindex></Phone>" for _, t, n in e["numbers"])
        company = f"<Company>{escape(e['company'])}</Company>" if e["company"] else ""
        rows.append(f"<Contact><LastName>{escape(e['last'])}</LastName><FirstName>{escape(e['first'])}</FirstName>"
                    f"{company}{tel}</Contact>")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<AddressBook>{"".join(rows)}</AddressBook>\n'


def swyx(items):
    """SwyxWare's Global Phonebook import (Swyx Administration → Global Phonebook → Import): one line per number,
    "Name";"Number";"Description", every field quoted. Names must be unique there, so a contact with several numbers
    gets the number's label, and a name that is still taken the company, then a counter."""
    q = lambda v: '"' + str(v).replace('"', "'").replace("\r", " ").replace("\n", " ") + '"'
    taken, lines = set(), []
    for e in items:
        base = f"{e['last']},{e['first']}" if e["first"] else e["last"]  # "Schmidt,Eva" like Swyx's own entries
        for label, _, n in e["numbers"]:
            name = f"{base} ({label})" if len(e["numbers"]) > 1 else base
            if name in taken and e["company"]:
                name = f"{name} – {e['company']}"
            unique, i = name, 2
            while unique in taken:
                unique, i = f"{name} {i}", i + 1
            taken.add(unique)
            lines.append(";".join(q(x) for x in (unique, _dial(n), " · ".join(filter(None, (e["company"], label))))))
    return "\r\n".join(lines) + "\r\n"


FORMATS = {"yealink": yealink, "snom": snom, "grandstream": grandstream, "swyx": swyx}


def _guard(request):
    """None if the request may read the phonebook, else the response refusing it."""
    s = Settings.get()
    if not s.phonebook_enabled or not s.phonebook_password_hash:
        return HttpResponse(status=404)
    if s.phonebook_allowlist and not monitoring.allowed(client_ip(request), s.phonebook_allowlist):
        return HttpResponse(status=403)
    if not dav.authorized(request, s.phonebook_username, s.phonebook_password_hash, on_fail=_auth_failed):
        r = dav.unauthorized()
        r["WWW-Authenticate"] = 'Basic realm="Kartei", charset="UTF-8"'
        return r
    return None


def _auth_failed(user):
    audit.log(None, "auth_failed", "session", "", user[:150], {"channel": [None, "phonebook"]}, username=user[:150] or "?")


@csrf_exempt
def directory(request, brand):
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405)
    if brand not in FORMATS:
        return HttpResponse(status=404)
    if refused := _guard(request):
        return refused
    items, _ = entries()
    body = FORMATS[brand](_search(items, request.GET.get("q", "")[:100]))
    if brand != "swyx":
        return HttpResponse(body, content_type="text/xml; charset=utf-8")
    # a Windows import: UTF-8 with BOM by default, ?charset=windows-1252 for an older SwyxWare that expects ANSI
    if request.GET.get("charset", "").lower() in ("windows-1252", "cp1252", "ansi"):
        data, charset = body.encode("cp1252", "replace"), "windows-1252"
    else:
        data, charset = "\ufeff".encode() + body.encode(), "utf-8"
    r = HttpResponse(data, content_type=f"text/csv; charset={charset}")
    r["Content-Disposition"] = 'attachment; filename="kartei-swyx.csv"'
    return r


@csrf_exempt
def lookup(request):
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405)
    if refused := _guard(request):
        return refused
    number = request.GET.get("number", "")[:40]
    if number.startswith(" "):  # an unencoded "+49…" in the URL arrives as " 49…"
        number = "+" + number.lstrip()
    e = find(number)
    if request.GET.get("format") == "json":
        if not e:
            return JsonResponse({"found": False}, status=404)
        return JsonResponse({"found": True, "name": e["name"], "company": e["company"], "kind": e["kind"], "uid": e["uid"]})
    if not e:
        return HttpResponse("", status=404, content_type="text/plain; charset=utf-8")
    return HttpResponse(" · ".join(filter(None, (e["name"], e["company"]))), content_type="text/plain; charset=utf-8")
