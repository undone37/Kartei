"""Dashboard and list tools: recently viewed, favorites, saved filters, recent changes, list export, bulk edit."""
import uuid
from datetime import date

from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpResponse, JsonResponse

from . import audit, exports, reviews
from .api import (MAINT, READ, _add_new_options, _soft_delete, delete_with_persons, err, needs, profile_of, record_kinds,
                  ser_audit, ser_record, snapshot, visible_fields)
from .models import (AuditEntry, FieldDef, Kind, Profile, Record, Role, SavedFilter, Settings, default_csv_options,
                     default_xlsx_options, ref_names, user_label)
from .validation import EMPTY, merge_data

RECENT_MAX, FAVORITES_MAX = 20, 200


def _uid(v):
    try:
        return str(uuid.UUID(str(v)))
    except ValueError:
        return None


def _uids(v):
    return list(dict.fromkeys(u for u in map(_uid, v) if u)) if isinstance(v, list) else []


def share_of(f):
    """Who a filter is shared with, as the UI's values: "all", "role:<role>", "user:<username>"."""
    return (["all"] if f.shared else []) + [f"role:{r}" for r in f.share_roles] + \
        [f"user:{u.username}" for u in f.share_users.all()]


def ser_filter(f, user):
    share = share_of(f)
    return {"id": f.id, "name": f.name, "state": f.state, "shared": bool(share), "owner": f.owner.username,
            "mine": f.owner_id == user.id, **({"share": share} if f.owner_id == user.id else {})}


def visible_filters(user, role):
    """Own filters and those shared with everyone, the user's role or the user."""
    # ponytail: filtered in Python (JSON "contains" isn't available on SQLite); fine for hundreds of saved filters
    fs = SavedFilter.objects.select_related("owner").prefetch_related("share_users").order_by("name")
    return [f for f in fs if f.owner_id == user.id or f.shared or role in f.share_roles
            or any(u.id == user.id for u in f.share_users.all())]


def prefs(request):
    """Part of bootstrap/changes (small, so always sent): recently viewed, favorites, own + shared saved filters.
    Those who may share also get the active users to share with."""
    p = profile_of(request.user)
    role = "admin" if request.user.is_superuser else p.role
    out = {"recent": p.recent, "favorites": p.favorites,
           "filters": [ser_filter(f, request.user) for f in visible_filters(request.user, role)]}
    if request.rank >= MAINT:
        out["share_users"] = [{"username": u.username, "name": user_label(u)} for u in
                              User.objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("first_name", "last_name", "username")]
    return out


# ---------------------------------------------------------------- recently viewed & favorites

def _update_list(user, attr, fn):
    with transaction.atomic():
        p = Profile.objects.select_for_update().get(user=user)
        setattr(p, attr, fn(getattr(p, attr)))
        p.save(update_fields=[attr])
    return getattr(p, attr)


def _live(uid):
    return uid and Record.objects.filter(uid=uid, deleted_at__isnull=True).exists()


@needs(READ)
def viewed(request):
    uid = _uid(request.json.get("uid"))
    if not _live(uid):
        return err("not_found", 404)
    return JsonResponse({"recent": _update_list(request.user, "recent",
                                                lambda xs: [uid, *[x for x in xs if x != uid]][:RECENT_MAX])})


@needs(READ)
def favorite(request):
    uid, on = _uid(request.json.get("uid")), bool(request.json.get("on"))
    if on and not _live(uid):
        return err("not_found", 404)
    return JsonResponse({"favorites": _update_list(request.user, "favorites",
                                                   lambda xs: ([uid] if on else []) + [x for x in xs if x != uid][:FAVORITES_MAX])})


# ---------------------------------------------------------------- saved filters

ADV_MODES, ADV_DEPTH, ADV_ITEMS = ("all", "any", "none"), 5, 50


def _clean_adv(g, depth=0):
    """The advanced filter (frontend lib/advanced.ts): {mode, items}, items are groups or {field, op, value}.
    Only the shape is checked; unknown fields/operators are ignored by the client."""
    if (depth >= ADV_DEPTH or not isinstance(g, dict) or g.get("mode") not in ADV_MODES
            or not isinstance(g.get("items"), list) or len(g["items"]) > ADV_ITEMS):
        raise ValueError
    items = []
    for x in g["items"]:
        if not isinstance(x, dict):
            raise ValueError
        if "items" in x:
            items.append(_clean_adv(x, depth + 1))
            continue
        c = {"field": str(x.get("field") or "")[:64], "op": str(x.get("op") or "")[:20]}
        v = x.get("value")
        if isinstance(v, list):
            c["value"] = [str(y)[:200] for y in v][:200]
        elif isinstance(v, (str, int, float)) and not isinstance(v, bool):
            c["value"] = str(v)[:200]
        items.append(c)
    return {"mode": g["mode"], "items": items}


def _clean_state(st):
    if not isinstance(st, dict) or not isinstance(st.get("filters") or {}, dict):
        return None
    filters = st.get("filters") or {}
    if not all(isinstance(v, list) for v in filters.values()):
        return None
    out = {"q": str(st.get("q") or "")[:500], "scope": str(st.get("scope") or "all")[:20],
           "kind": str(st.get("kind") or "all")[:10],
           "filters": {str(k)[:64]: [str(x)[:200] for x in v][:200] for k, v in filters.items() if v}}
    if st.get("adv"):  # optional, older saved filters have none
        try:
            out["adv"] = _clean_adv(st["adv"])
        except ValueError:
            return None
    return out


def _filter_from_body(f, b, rank):
    errors = {}
    if "name" in b:
        f.name = " ".join(str(b["name"] or "").split())[:100]
    if not f.name:
        errors["name"] = "required"
    if "state" in b:
        st = _clean_state(b["state"])
        if st is None:
            errors["state"] = "invalid"
        else:
            f.state = st
    f._users = None  # set after saving (many-to-many needs the id)
    if "shared" in b and "share" not in b:  # older clients: everyone or nobody
        b = {**b, "share": ["all"] if b["shared"] else []}
    if "share" in b:
        share = b["share"] if isinstance(b["share"], list) else None
        roles = [str(x)[5:] for x in share or [] if str(x).startswith("role:")]
        names = [str(x)[5:] for x in share or [] if str(x).startswith("user:")]
        users = list(User.objects.filter(username__in=names, is_active=True))
        if share is None or any(not (x == "all" or str(x).startswith(("role:", "user:"))) for x in share) \
                or any(r not in Role.values for r in roles) or len(users) != len(set(names)):
            errors["share"] = "invalid"
        elif share and rank < MAINT:
            errors["share"] = "forbidden"
        else:
            f.shared, f.share_roles, f._users = "all" in share, sorted(set(roles)), users
    return errors


@needs(READ)
def filter_create(request):
    f = SavedFilter(owner=request.user, name="", state=_clean_state({}))
    if errors := _filter_from_body(f, request.json, request.rank):
        return err("validation", fields=errors)
    f.save()
    if f._users is not None:
        f.share_users.set(f._users)
    return JsonResponse(ser_filter(f, request.user), status=201)


@needs(READ)
def filter_update(request, pk):
    """Rename/reshare (PATCH) or delete (DELETE) one of your own filters."""
    f = SavedFilter.objects.filter(pk=pk, owner=request.user).first()
    if not f:
        return err("not_found", 404)
    if request.method == "DELETE":
        f.delete()
        return JsonResponse({"ok": True})
    if errors := _filter_from_body(f, request.json, request.rank):
        return err("validation", fields=errors)
    f.save()
    if f._users is not None:
        f.share_users.set(f._users)
    return JsonResponse(ser_filter(f, request.user))


# ---------------------------------------------------------------- recent changes

@needs(MAINT)
def recent_changes(request):
    """The last record changes for the dashboard; like a record's history, hidden fields are filtered out."""
    entries = list(AuditEntry.objects.filter(target_type="record")[:20])
    kinds = record_kinds(entries)
    return JsonResponse({"entries": [ser_audit(e, request.rank, kinds) for e in entries]})


# ---------------------------------------------------------------- export of the current list

HEADERS = {"de": ["Art", "Nachname", "Vorname", "Firma", "Person", "Firma"],
           "en": ["Type", "Last name", "First name", "Company", "Person", "Company"]}
MIME = {"csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def list_columns(rank, lang):
    """Core columns plus every field the user may see, as export column specs."""
    h = HEADERS[lang]
    cols = [{"header": h[0], "person": f"const:{h[4]}", "company": f"const:{h[5]}"},
            {"header": h[1], "person": "core:last_name", "company": ""},
            {"header": h[2], "person": "core:first_name", "company": ""},
            {"header": h[3], "person": "calc:company_name", "company": "core:name"}]
    fields = visible_fields(rank)
    cols += [{"header": getattr(f, f"label_{lang}") or f.label_de, "person": f"field:{f.key}",
              "company": f"field:{f.key}"} for f in fields]
    return cols, {f.key: f for f in fields}


@needs(READ)
def export_list(request):
    """Exactly the records the user sees in the list (uids in list order), as CSV or XLSX."""
    fmt, uids = request.json.get("format"), _uids(request.json.get("uids"))
    if fmt not in MIME:
        return err("validation", fields={"format": "invalid"})
    if not uids:
        return err("validation", fields={"uids": "required"})
    lang = profile_of(request.user).language or Settings.get().default_language
    cols, fields = list_columns(request.rank, lang)
    names = ref_names()
    recs = {str(r.uid): r for r in Record.objects.filter(uid__in=uids, deleted_at__isnull=True)
            .select_related("company").defer("image")}
    rows = [[exports._typed(exports.resolve(r, c[r.kind], fields), c[r.kind], fields, names) for c in cols]
            for r in (recs.get(u) for u in uids) if r]
    header = [c["header"] for c in cols]
    data = (exports.render_csv(header, rows, default_csv_options()) if fmt == "csv"
            else exports.render_xlsx(header, rows, default_xlsx_options()))
    name = f"kartei-{date.today().isoformat()}.{fmt}"
    audit.log(request.user, "export", "export", "-", name, {"rows": [None, len(rows)], "format": [None, fmt]})
    resp = HttpResponse(data, content_type=MIME[fmt])
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


# ---------------------------------------------------------------- bulk edit

BULK_OPS = ("set", "clear", "add", "remove", "delete")


def _new_value(op, old, value):
    if op == "set":
        return value
    if op == "clear":
        return None
    old = old if isinstance(old, list) else []
    if op == "add":
        return list(dict.fromkeys([*old, *value]))
    return [x for x in old if x not in value]


@needs(MAINT)
def bulk(request):
    """Apply one field operation (or a move to the recycle bin) to many records. Each record is validated, versioned
    and audited on its own (marked `bulk`); failures are reported per record and don't stop the others."""
    b = request.json if isinstance(request.json, dict) else {}
    op, key, value, uids = b.get("op"), b.get("key"), b.get("value"), _uids(b.get("uids"))
    if op not in BULK_OPS or not uids:
        return err("invalid")
    fields = list(FieldDef.objects.all())
    if op != "delete":
        f = next((x for x in fields if x.key == key and not x.archived and x.visible(request.rank)), None)
        if not f:
            return err("validation", fields={"key": "unknown_field"})
        if not f.editable(request.rank):
            return err("validation", fields={"key": "forbidden"})
        multi = f.type in ("multiselect", "users")
        if op in ("add", "remove") and not multi:
            return err("validation", fields={"key": "invalid"})
        if op in ("add", "remove") and (not isinstance(value, list) or not value) or op == "set" and value in EMPTY:
            return err("validation", fields={"value": "required"})
    with_persons = op == "delete" and b.get("with_persons") is True  # companies take their persons along
    vis = visible_fields(request.rank)
    records, deleted, errors, gone = [], [], [], set()
    # ponytail: one request, one transaction per record; fine for a few thousand records, chunk client-side beyond
    for uid in uids:
        if uid in gone:  # a selected person already went with its selected company
            continue
        with transaction.atomic():
            r = (Record.objects.select_for_update(of=("self",)).select_related("company")
                 .filter(uid=uid, deleted_at__isnull=True).first())
            if not r:
                errors.append({"uid": uid, "name": "", "fields": {"record": "not_found"}})
                continue
            if op == "delete":
                if with_persons and r.kind == Kind.COMPANY:
                    done = delete_with_persons(request.user, r, {"bulk": [None, True]})
                else:
                    _soft_delete(request.user, r, {"bulk": [None, True]})
                    done = [uid]
                deleted += done
                gone.update(done)
                continue
            if not f.applies(r.kind):
                errors.append({"uid": uid, "name": r.display_name, "fields": {key: "not_applicable"}})
                continue
            before = snapshot(r)
            data, errs = merge_data(r.kind, r.data, {key: _new_value(op, r.data.get(key), value)}, fields, request.rank)
            if errs:
                errors.append({"uid": uid, "name": r.display_name, "fields": errs})
                continue
            r.data = data
            if change := audit.diff(before, snapshot(r)):
                r.version += 1
                r.updated_by = request.user
                r.save()
                audit.log(request.user, "update", "record", r.uid, r.display_name, change | {"bulk": [None, True]})
                _add_new_options(request.user, fields, r)
                reviews.reassign(r)
            records.append(ser_record(r, vis))
    return JsonResponse({"records": records, "deleted": deleted, "errors": errors})
