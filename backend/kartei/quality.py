"""Data quality: normalizing stored phone numbers, duplicate candidates and merging them, the quality report."""
import unicodedata
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from . import audit, reviews
from .api import ADMIN, MAINT, _soft_delete, err, needs, records_qs, ser_record, snapshot, visible_fields
from .batch import MIN_PREFIX, national
from .models import FieldDef, NotDuplicate, Proposal, Record, Review, Settings
from .validation import EMPTY, PHONE_RE, clean_value, normalize_phone

GROUP_CAP = 5  # a value shared by more records is a switchboard, an info@ address or a common name, not an identity
LIST_CAP = 200  # items per quality section; the count is always complete
MULTI = ("multiselect", "users")


def live():
    return Record.objects.filter(deleted_at__isnull=True).defer("image")


# ---------------------------------------------------------------- phone numbers

def phone_changes(cc):
    """[(record, {key: [old, new]})] for live records whose phone numbers normalize differently."""
    keys = list(FieldDef.objects.filter(type="phone").values_list("key", flat=True))
    out = []
    for r in live().filter(data__has_any_keys=keys) if keys else []:
        change = {}
        for k in keys:
            v = r.data.get(k)
            if isinstance(v, str) and PHONE_RE.match(v) and (n := normalize_phone(v, cc)) != v:
                change[k] = [v, n]
        if change:
            out.append((r, change))
    return out


def normalize_phones(user=None, dry_run=True):
    """One-time cleanup of numbers saved before normalization. Audited per record plus one summary entry."""
    cc = Settings.get().phone_country_code
    with transaction.atomic():
        items = phone_changes(cc)
        if not dry_run:
            for r, change in items:
                r = Record.objects.select_for_update().get(pk=r.pk)  # fresh data, version and lock
                for k, (old, new) in change.items():
                    if r.data.get(k) == old:
                        r.data[k] = new
                r.version += 1
                r.updated_by = user
                r.save()
                audit.log(user, "update", "record", r.uid, r.display_name, change | {"normalized": [None, True]})
            if items:
                audit.log(user, "normalize", "settings", 1, "phones", {"normalized": [None, len(items)]})
    return {"count": len(items), "dry_run": dry_run,
            "sample": [{"uid": str(r.uid), "kind": r.kind, "name": r.display_name, "key": k, "old": o, "new": n}
                       for r, c in items[:20] for k, (o, n) in c.items()]}


@needs(ADMIN)
def normalize_view(request):
    return JsonResponse(normalize_phones(request.user, dry_run=request.json.get("dry_run", True) is not False))


# ---------------------------------------------------------------- duplicates

def fold(s):
    """Case- and accent-insensitive form: 'Müller  GmbH' -> 'muller gmbh'."""
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).casefold().split())


def candidates(rank=ADMIN, records=None):
    """[(a, b, reasons)] pairs of live records of the same kind (a.id < b.id) sharing an email, a phone number
    (national digits, >= 6) or the name (persons: within the same company). Dismissed pairs are left out."""
    fields = [f for f in FieldDef.objects.filter(archived=False, type__in=("email", "phone")) if f.visible(rank)]
    cc = Settings.get().phone_country_code
    if records is None:
        records = live().only("id", "uid", "kind", "first_name", "last_name", "name", "company_id", "data")

    def contacts(r):
        out = set()
        for f in fields:
            v = r.data.get(f.key)
            if isinstance(v, str) and v:
                if f.type == "email":
                    out.add(("email", v.strip().lower()))
                elif len(d := national(v, cc)[0]) >= MIN_PREFIX:
                    out.add(("phone", d))
        return out

    records = list(records)
    # persons often carry their company's switchboard or info@ address: that doesn't make them the same person
    shared = set().union(*(contacts(r) for r in records if r.kind == "company"))
    groups = defaultdict(list)
    for r in records:
        keys = contacts(r) - shared if r.kind == "person" else contacts(r)
        if r.kind == "company" and (n := fold(r.name)):
            keys.add(("name", n))
        elif r.kind == "person" and (n := fold(f"{r.first_name} {r.last_name}")):
            keys.add(("name", (n, r.company_id)))
        for reason, value in keys:
            groups[(r.kind, reason, value)].append(r)
    pairs = {}
    for (_, reason, _), rs in groups.items():
        if not 2 <= len(rs) <= GROUP_CAP:  # ponytail: bigger groups are noise, fix those with a list filter
            continue
        rs = sorted(rs, key=lambda r: r.id)
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                pairs.setdefault((a.id, b.id), (a, b, set()))[2].add(reason)
    dismissed = set(NotDuplicate.objects.values_list("a_id", "b_id"))
    out = [(a, b, sorted(rs)) for ids, (a, b, rs) in pairs.items() if ids not in dismissed]
    out.sort(key=lambda p: (-len(p[2]), fold(p[0].display_name)))
    return out


@needs(MAINT)
def duplicates_view(request):
    return JsonResponse({"pairs": [{"a": str(a.uid), "b": str(b.uid), "kind": a.kind, "reasons": rs}
                                   for a, b, rs in candidates(request.rank)]})


CORE = {"person": ["first_name", "last_name", "company"], "company": ["name"]}


def _value(r, key, fields):
    if key == "company":
        return r.company_id
    if key == "image":
        return r.image_type or None
    if key in fields:
        return r.data.get(key)
    return getattr(r, key)


def default_pick(a, b, fields):
    """{key: uid of the record whose value wins, or 'union'}: the more recently updated record's non-empty value,
    multi-value fields with two different values combined. fields: {key: FieldDef} the user may edit."""
    new, old = (a, b) if a.updated_at >= b.updated_at else (b, a)
    keys = CORE[a.kind] + ["image"] + [k for k, f in fields.items() if f.applies(a.kind)]
    out = {}
    for k in keys:
        vn, vo = _value(new, k, fields), _value(old, k, fields)
        if vn in EMPTY and vo in EMPTY:
            continue
        if k in fields and fields[k].type in MULTI and vn not in EMPTY and vo not in EMPTY and vn != vo:
            out[k] = "union"
        else:
            out[k] = str((new if vn not in EMPTY else old).uid)
    return out


def _editable(rank):
    return {f.key: f for f in FieldDef.objects.filter(archived=False) if f.visible(rank) and f.editable(rank)}


def _pair(a_uid, b_uid, lock=False):
    qs = Record.objects.filter(uid__in=[a_uid, b_uid], deleted_at__isnull=True)
    recs = {str(r.uid): r for r in (qs.select_for_update() if lock else qs)}
    a, b = recs.get(str(a_uid)), recs.get(str(b_uid))
    if not a or not b or a == b:
        return None, err("not_found", 404)
    if a.kind != b.kind:
        return None, err("invalid_kind")
    return (a, b), None


@needs(MAINT)
def merge_preview(request):
    pair, error = _pair(request.GET.get("a"), request.GET.get("b"))
    if error:
        return error
    fields = visible_fields(request.rank)
    return JsonResponse({"pick": default_pick(*pair, _editable(request.rank)),
                         "records": [ser_record(r, fields) for r in pair]})


def merge(keep, other, pick, user, rank):
    """Merge `other` into `keep` (both locked). pick: {key: uid | 'union'} over default_pick()."""
    fields = _editable(rank)
    picks = default_pick(keep, other, fields) | {k: v for k, v in pick.items() if isinstance(v, str)}
    takes = lambda k: picks.get(k) == str(other.uid)
    before, img = snapshot(keep), keep.image_type
    for k in CORE[keep.kind]:
        if takes(k):
            setattr(keep, "company_id" if k == "company" else k, _value(other, k, fields))
    for k, f in fields.items():
        if not f.applies(keep.kind):
            continue
        if picks.get(k) == "union" and f.type in MULTI:
            as_list = lambda v: v if isinstance(v, list) else [] if v in EMPTY else [v]
            keep.data[k] = list(dict.fromkeys(as_list(keep.data.get(k)) + as_list(other.data.get(k))))
        elif takes(k):
            if other.data.get(k) in EMPTY:
                keep.data.pop(k, None)
            else:
                keep.data[k] = other.data[k]
    if takes("image"):
        keep.image, keep.image_type = other.image, other.image_type
    keep.merged_legacy_ids = list(dict.fromkeys(keep.merged_legacy_ids + ([other.legacy_id] if other.legacy_id else [])
                                                + other.merged_legacy_ids))
    keep.version += 1
    keep.updated_by = user
    keep.save()
    keep.company = Record.objects.filter(pk=keep.company_id).first()  # for the snapshot's company name
    change = audit.diff(before, snapshot(keep))
    if takes("image"):
        change["image"] = [img or None, f"{keep.image_type}, {len(keep.image or b'')} B" if keep.image_type else None]
    audit.log(user, "merge", "record", keep.uid, keep.display_name, change | {"merged_from": [None, other.display_name]})

    def move(r, change):
        r.version += 1
        r.updated_by = user
        r.save()
        audit.log(user, "update", "record", r.uid, r.display_name, change)

    for p in Record.objects.select_for_update().filter(company=other):  # incl. deleted ones, so a restore fits
        p.company = keep
        move(p, {"company": [other.display_name, keep.display_name]})
    ckeys = list(FieldDef.objects.filter(type="contact").values_list("key", flat=True))
    for r in Record.objects.select_for_update().filter(data__has_any_keys=ckeys) if ckeys else []:
        hits = [k for k in ckeys if r.data.get(k) == str(other.uid)]
        for k in hits:
            r.data[k] = str(keep.uid)
        if hits:
            move(r, {k: [other.display_name, keep.display_name] for k in hits})
    if reviews.open_reviews().filter(record=keep).exists():  # at most one open review per record
        reviews.finish(other.reviews.all(), "cancelled")
    else:
        reviews.open_reviews().filter(record=other).update(record=keep)
    Proposal.objects.filter(record=other, status="pending").update(record=keep)
    other.merged_into = keep
    _soft_delete(user, other, {"merged_into": [None, keep.display_name]})
    reviews.reassign(keep)


@needs(MAINT)
def merge_view(request):
    b = request.json
    with transaction.atomic():
        pair, error = _pair(b.get("keep"), b.get("other"), lock=True)
        if error:
            return error
        versions = b.get("versions") if isinstance(b.get("versions"), dict) else {}
        if any(versions.get(str(r.uid)) != r.version for r in pair):
            return err("version_conflict", 409)
        merge(*pair, b.get("pick") if isinstance(b.get("pick"), dict) else {}, request.user, request.rank)
    return JsonResponse(ser_record(records_qs().get(pk=pair[0].pk), visible_fields(request.rank)))


@needs(MAINT)
def dismiss_view(request):
    pair, error = _pair(request.json.get("a"), request.json.get("b"))
    if error:
        return error
    a, b = sorted(pair, key=lambda r: r.id)
    _, created = NotDuplicate.objects.get_or_create(a=a, b=b, defaults={"by": request.user})
    if created:
        for x, y in ((a, b), (b, a)):
            audit.log(request.user, "not_duplicate", "record", x.uid, x.display_name, {"not_duplicate": [None, y.display_name]})
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------- quality report

def report(rank):
    """Counts and (capped) lists of contacts needing attention, in one pass over the live records."""
    s = Settings.get()
    cc = s.phone_country_code if s.phone_normalize else ""
    all_fields = list(FieldDef.objects.filter(archived=False))
    visible = [f for f in all_fields if f.visible(rank)]
    reach = [f.key for f in all_fields if f.type in ("email", "phone") and f.applies("person")]
    keys = reviews.responsible_keys()
    active = set(User.objects.filter(is_active=True).values_list("username", flat=True))
    cutoff = timezone.now() - timedelta(days=round(max(s.review_interval_months, 1) * 30.44))
    recs = list(live().only("id", "uid", "kind", "first_name", "last_name", "name", "company_id", "data",
                            "reviewed_at", "created_at"))
    lists = defaultdict(list)
    employers = {r.company_id for r in recs if r.kind == "person" and r.company_id}
    for r in recs:
        uid = str(r.uid)
        if keys and reviews.responsible(r, keys, active) is None:
            lists["no_responsible"].append(uid)
        for f in visible:
            v = r.data.get(f.key)
            if f.applies(r.kind) and v not in EMPTY:
                try:
                    clean_value(f, v, v, cc)  # old=v: kept users/contacts stay valid, no lookups
                except ValueError as e:
                    lists["invalid"].append({"uid": uid, "key": f.key, "error": str(e)})
        if r.kind == "person":
            if not any(r.data.get(k) not in EMPTY for k in reach):
                lists["no_reach"].append(uid)
            if not r.company_id:
                lists["no_company"].append(uid)
        elif r.id not in employers:
            lists["empty_company"].append(uid)
        if r.reviewed_at is None:
            lists["never_reviewed"].append(uid)
        elif r.reviewed_at < cutoff:
            lists["overdue"].append(uid)
    out = {k: {"count": len(lists[k]), "items": lists[k][:LIST_CAP]}
           for k in ("no_responsible", "invalid", "no_reach", "no_company", "empty_company", "never_reviewed", "overdue")}
    if not keys:
        out.pop("no_responsible")  # no single-user field, nobody can be responsible
    out["duplicates"] = {"count": len(candidates(rank, recs))}
    out["review_interval_months"] = s.review_interval_months
    return out


@needs(MAINT)
def quality_view(request):
    return JsonResponse(report(request.rank))
