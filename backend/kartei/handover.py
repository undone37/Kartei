"""Handover when someone leaves (or changes jobs): wherever a contact names them in a user field (the person
responsible, internal contacts), the successor takes their place; open reviews follow the new responsible."""
from collections import Counter

from django.db import transaction

from . import audit, reviews
from .models import FieldDef, Record, Review

USER_FIELDS = ("user", "users")


def _fields():
    return list(FieldDef.objects.filter(type__in=USER_FIELDS))


def _live():
    return Record.objects.filter(deleted_at__isnull=True).only("id", "data")


def refs(fields=None):
    """{username: number of contacts naming them} over all user fields, in one pass."""
    fields = fields or _fields()
    out = Counter()
    for r in _live():
        out.update({n for f in fields for n in _names(r.data.get(f.key))})
    return out


def plan(old):
    """What a handover of `old` would change: contacts per field, open reviews."""
    fields, per_field, records = _fields(), Counter(), 0
    for r in _live():
        hit = [f for f in fields if old.username in _names(r.data.get(f.key))]
        per_field.update(f.key for f in hit)
        records += bool(hit)
    return {"records": records, "fields": dict(per_field),
            "reviews": reviews.open_reviews().filter(assignee=old).count()}


def _names(v):
    return v if isinstance(v, list) else [v] if v else []


@transaction.atomic
def apply(old, new, actor):
    """Replace `old` by `new` in every live contact's user fields. Returns the number of contacts changed."""
    fields, n = _fields(), 0
    for r in Record.objects.select_for_update().filter(deleted_at__isnull=True):
        change = {}
        for f in fields:
            v = r.data.get(f.key)
            if old.username not in _names(v):
                continue
            if f.type == "user":
                r.data[f.key] = new.username
            else:  # keep the order, no duplicates if the successor was already listed
                r.data[f.key] = list(dict.fromkeys(new.username if x == old.username else x for x in v))
            change[f.key] = [v, r.data[f.key]]
        if change:
            r.version += 1
            r.updated_by = actor
            r.save()
            audit.log(actor, "update", "record", r.uid, r.display_name, change | {"handover": [old.username, new.username]})
            reviews.reassign(r)
            n += 1
    for rv in Review.objects.filter(pk__in=reviews.open_reviews().filter(assignee=old)).select_related("record"):
        reviews.reassign(rv.record)  # reviews of contacts whose responsible was already someone else
    audit.log(actor, "handover", "user", old.id, old.username, {"handover_to": [None, new.username], "records": [None, n]})
    return n
