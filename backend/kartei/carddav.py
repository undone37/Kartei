"""Built-in read-only CardDAV server: the protocol (dav.py) on cards rendered live from the Kartei database.

With the DMZ relay (relaypush.py) phones use the relay instead; this endpoint then usually stays off (404).
"""
import hashlib

from django.db.models import Count, Max
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from . import dav as proto
from .models import FieldDef, Record, Settings, ref_names
from .vcard import render


def _fields():
    return [f for f in FieldDef.objects.filter(archived=False, visible_to="read")]


def _schema_hash(fields, s, names):
    # names: renaming a user or a referenced person changes the cards of every contact referencing them
    raw = repr([(f.key, f.applies_to, f.vcard, f.vcard_label, f.label_de) for f in fields] + [s.base_url, sorted(names.items())])
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _records():
    return Record.objects.filter(deleted_at__isnull=True).select_related("company")


def _etag(r, schema):
    company = f".{r.company.version}" if r.company_id and r.company else ""
    return f'"{r.version}{company}-{schema}"'


class Book:
    def __init__(self, s, flavour):
        self.s, self.flavour = s, flavour
        self.fields, self.names = _fields(), ref_names()
        self.schema = _schema_hash(self.fields, s, self.names)

    def ctag(self):
        agg = Record.objects.aggregate(m=Max("updated_at"), n=Count("id"))
        return f'"{agg["m"].timestamp() if agg["m"] else 0}-{agg["n"]}-{self.schema}"'

    def etags(self, uid=None):
        qs = _records().defer("image")
        return [(str(r.uid), _etag(r, self.schema)) for r in (qs if uid is None else qs.filter(uid=uid))]

    def cards(self, uids=None):
        qs = _records() if uids is None else _records().filter(uid__in=uids)
        return [(str(r.uid), _etag(r, self.schema), render(r, self.fields, self.flavour, self.s.base_url, self.names))
                for r in qs]


@csrf_exempt
def well_known(request):
    return proto.well_known(request)


@csrf_exempt
def dav(request, uid=None):
    s = Settings.get()
    if not s.carddav_enabled:
        return HttpResponse(status=404)
    return proto.serve(request, uid, s.carddav_username, s.carddav_password_hash, lambda flavour: Book(s, flavour))

