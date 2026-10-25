"""JSON API for the SPA. Session auth + CSRF. Errors are {"error": code, "fields": {key: code}}."""
import json
import re
import secrets
import uuid
from datetime import timedelta
from functools import wraps

from django.conf import settings as dj
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie

from . import adsync, audit, batch, exports, graph, importer, ldapusers, oidc, relaypush, reviews
from .msg import msg
from .net import client_ip
from .models import (ROLE_RANK, USER_TYPES, AuditEntry, ExportProfile, FieldDef, FieldSection, FieldType, Kind, Profile,
                     Proposal, Record, Review, Role, Settings, user_options)
from .validation import REGEX_TYPES, clean_core, merge_data
from .vcard import TARGETS as VCARD_TARGETS

READ, MAINT, ADMIN = 0, 1, 2
MAX_IMAGE = 512 * 1024


# ---------------------------------------------------------------- plumbing

def err(code, status=400, **extra):
    return JsonResponse({"error": code, **extra}, status=status)


def profile_of(user):
    return Profile.objects.get_or_create(user=user, defaults={
        "role": Role.ADMIN if user.is_superuser else Role.READ})[0]


def rank_of(user):
    return 2 if user.is_superuser else ROLE_RANK[profile_of(user).role]


def needs(min_rank):
    def deco(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return err("unauthenticated", 401)
            request.rank = rank_of(request.user)
            if request.rank < min_rank:
                return err("forbidden", 403)
            request.json = {}
            if request.body and request.content_type == "application/json":
                try:
                    request.json = json.loads(request.body)
                except ValueError:
                    return err("invalid_json")
                if not isinstance(request.json, (dict, list)):
                    return err("invalid_json")
            return fn(request, *args, **kwargs)
        return wrapper
    return deco


def methods(**handlers):
    def view(request, *args, **kwargs):
        h = handlers.get(request.method)
        return h(request, *args, **kwargs) if h else err("method_not_allowed", 405)
    return view


# ---------------------------------------------------------------- serializers

def ser_field(f, users=None):
    """users: user_options(), filled in as the options of user fields so the SPA treats them like selects."""
    return {
        "id": f.id, "key": f.key, "label": {"de": f.label_de, "en": f.label_en}, "applies_to": f.applies_to,
        "type": f.type, "options": users if f.type in USER_TYPES and users is not None else f.options,
        "open_options": f.open_options, "quick_filter": f.quick_filter,
        "required": f.required,
        "min": None if f.min_value is None else str(f.min_value),
        "max": None if f.max_value is None else str(f.max_value), "decimals": f.decimals,
        "section": f.section_id, "order": f.order,
        "visible_to": f.visible_to, "editable_by": f.editable_by, "searchable": f.searchable,
        "regex": f.regex, "help": {"de": f.help_de, "en": f.help_en},
        "vcard": f.vcard, "vcard_label": f.vcard_label, "copy_from": f.copy_from_id, "archived": f.archived,
        "import_aliases": f.import_aliases,
    }


def ser_section(s):
    return {"id": s.id, "key": s.key, "label": {"de": s.label_de, "en": s.label_en}, "order": s.order}


def sections_list():
    return [ser_section(s) for s in FieldSection.objects.all()]


RECORD_COLUMNS = ("uid", "kind", "legacy_id", "first_name", "last_name", "name", "company__uid", "image_type", "data", "version",
                  "created_at", "updated_at", "updated_by__username", "deleted_at", "reviewed_at", "reviewed_by__username")


def _ser_row(v, keys):
    iso = lambda d: d.isoformat() if d else None
    return {
        "uid": str(v["uid"]), "kind": v["kind"], "legacy_id": v["legacy_id"],
        "first_name": v["first_name"], "last_name": v["last_name"], "name": v["name"],
        "company": str(v["company__uid"]) if v["company__uid"] else None,
        "image": v["version"] if v["image_type"] else None,
        "data": {k: x for k, x in v["data"].items() if k in keys[v["kind"]]},
        "version": v["version"], "created_at": iso(v["created_at"]), "updated_at": iso(v["updated_at"]),
        "updated_by": v["updated_by__username"] or "", "deleted_at": iso(v["deleted_at"]),
        "reviewed_at": iso(v["reviewed_at"]), "reviewed_by": v["reviewed_by__username"] or "",
    }


def _keys(fields):
    return {kind: {f.key for f in fields if f.applies(kind)} for kind in Kind.values}


def ser_records(qs, fields):
    """Many records at once: plain column values instead of model instances (bootstrap of 10k+ contacts)."""
    keys = _keys(fields)
    return [_ser_row(v, keys) for v in qs.values(*RECORD_COLUMNS)]


def ser_record(r, fields):
    rel = lambda o: o.username if o else None
    return _ser_row({c: getattr(r, c) for c in RECORD_COLUMNS if "__" not in c} | {
        "company__uid": r.company.uid if r.company_id and r.company else None,
        "updated_by__username": rel(r.updated_by if r.updated_by_id else None),
        "reviewed_by__username": rel(r.reviewed_by if r.reviewed_by_id else None)}, _keys(fields))


def ser_user(u):
    p = profile_of(u)
    return {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name,
            "email": u.email, "role": Role.ADMIN if u.is_superuser else p.role, "language": p.language,
            "source": p.source, "is_active": u.is_active, "is_superuser": u.is_superuser,
            "last_login": u.last_login.isoformat() if u.last_login else None}


def visible_fields(rank):
    return [f for f in FieldDef.objects.filter(archived=False) if f.visible(rank)]


def records_qs():
    return Record.objects.select_related("company", "updated_by", "reviewed_by").defer("image")


def snapshot(r):
    """Flat view of a record for audit diffs."""
    return {"first_name": r.first_name, "last_name": r.last_name, "name": r.name,
            "company": r.company.display_name if r.company_id and r.company else None, **r.data}


# ---------------------------------------------------------------- session

@ensure_csrf_cookie
def session(request):
    s = Settings.get()
    out = {"default_language": s.default_language, "authenticated": request.user.is_authenticated, "sso": oidc.configured(s)}
    if request.user.is_authenticated:
        out |= {"user": ser_user(request.user), "version": dj.KARTEI_VERSION, "source": dj.KARTEI_SOURCE_URL}
    return JsonResponse(out)


def login_view(request):
    if request.method != "POST":
        return err("method_not_allowed", 405)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return err("invalid_json")
    username, password = str(body.get("username", "")).strip(), str(body.get("password", ""))
    # ponytail: per-process cache counter; use a shared cache (DB/redis) if brute force across workers matters
    key = f"login-fail:{client_ip(request)}:{username.lower()}"
    if cache.get(key, 0) >= 10:
        return err("too_many_attempts", 429)
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        cache.set(key, cache.get(key, 0) + 1, 15 * 60)
        return err("invalid_credentials", 401)
    cache.delete(key)
    login(request, user)
    profile_of(user)
    return JsonResponse({"user": ser_user(user)})


def oidc_start(request):
    """Top-level navigation from the login page to Microsoft."""
    s = Settings.get()
    if not oidc.configured(s):
        return err("not_found", 404)
    return HttpResponseRedirect(oidc.start(request.session, s))


def oidc_callback(request):
    """Microsoft sends the browser back here; on success the user is signed in, else the login page shows why."""
    s = Settings.get()
    if not oidc.configured(s):
        return err("not_found", 404)
    if request.GET.get("error"):  # cancelled or refused at Microsoft
        return HttpResponseRedirect("/?login_error=sso_cancelled")
    try:
        user = oidc.finish(request.session, s, request.GET.get("code", ""), request.GET.get("state", ""))
    except oidc.SignInError as e:
        return HttpResponseRedirect(f"/?login_error={e}")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    profile_of(user)
    audit.log(user, "login", "user", user.id, user.username, {"sso": [None, "microsoft"]})
    return HttpResponseRedirect("/")


def logout_view(request):
    if request.method != "POST":
        return err("method_not_allowed", 405)
    logout(request)
    return JsonResponse({"ok": True})


@needs(READ)
def bootstrap(request):
    now = timezone.now()
    fields = visible_fields(request.rank)
    records = ser_records(Record.objects.filter(deleted_at__isnull=True), fields)
    s, users = Settings.get(), user_options()
    return JsonResponse({"cursor": now.isoformat(), "user": ser_user(request.user),
                         "default_language": s.default_language,
                         "fields": [ser_field(f, users) for f in fields], "sections": sections_list(),
                         "records": records, **workflow(request),
                         **dashboard_prefs(request)})


@needs(READ)
def changes(request):
    since = parse_datetime(request.GET.get("since", "") or "")
    now = timezone.now()
    s = Settings.get()
    if since is None or (s.trash_days and since < now - timedelta(days=s.trash_days)):
        return JsonResponse({"reset": True})
    fields, users = visible_fields(request.rank), user_options()
    # ponytail: 5 s overlap covers transactions committing with an older updated_at; client dedupes by version
    cut = since - timedelta(seconds=5)
    changed = ser_records(Record.objects.filter(Q(updated_at__gte=cut) | Q(reviewed_at__gte=cut)), fields)
    return JsonResponse({
        "cursor": now.isoformat(), "user": ser_user(request.user), "default_language": s.default_language,
        "fields": [ser_field(f, users) for f in fields], "sections": sections_list(),
        "records": [r for r in changed if not r["deleted_at"]],
        "deleted": [r["uid"] for r in changed if r["deleted_at"]],
        **workflow(request), **dashboard_prefs(request),
    })


# ---------------------------------------------------------------- records

def _resolve_company(value):
    if not value:
        return None, None
    try:
        c = Record.objects.filter(uid=value, kind=Kind.COMPANY, deleted_at__isnull=True).first()
    except ValidationError:  # not a UUID
        c = None
    return (c, None) if c else (None, "invalid_company")


def _apply(rank, r, body, fields):
    core, errors = clean_core(r.kind, body)
    for k, v in core.items():
        setattr(r, k, v)
    if r.kind == Kind.PERSON:
        if "company" in body:
            r.company, e = _resolve_company(body["company"])
            if e:
                errors["company"] = e
        if not (r.first_name or r.last_name):
            errors["last_name"] = "required"
    elif not r.name:
        errors["name"] = "required"
    data = body.get("data", {})
    if not isinstance(data, dict):
        return {"data": "invalid"}
    r.data, ferrors = merge_data(r.kind, r.data, data, fields, rank)
    errors.update(ferrors)
    return errors


def _add_new_options(user, fields, r, username=None):
    """Values typed into open select fields become options of the field (audited like an admin edit)."""
    for f in fields:
        v = r.data.get(f.key)
        if not f.open_options or f.type not in ("select", "multiselect") or v is None:
            continue
        vals = v if isinstance(v, list) else [v]
        if not set(vals) - {o["value"] for o in f.options}:
            continue
        with transaction.atomic():
            f = FieldDef.objects.select_for_update().get(pk=f.pk)
            before = list(f.options)
            known = {o["value"] for o in before}
            f.options = before + [{"value": x, "de": x, "en": x} for x in dict.fromkeys(vals) if x not in known]
            if len(f.options) > len(before):
                f.save(update_fields=["options"])
                audit.log(user, "update", "field", f.id, f.label_de, {"options": [before, f.options]}, username)


@needs(MAINT)
def create_record(request):
    body = request.json
    if body.get("kind") not in Kind.values:
        return err("invalid_kind")
    fields = list(FieldDef.objects.all())
    r = Record(kind=body["kind"], updated_by=request.user)
    if errors := _apply(request.rank, r, body, fields):
        return err("validation", fields=errors)
    r.save()
    audit.log(request.user, "create", "record", r.uid, r.display_name, audit.diff({}, snapshot(r)))
    _add_new_options(request.user, fields, r)
    return JsonResponse(ser_record(r, visible_fields(request.rank)), status=201)


@needs(READ)
def get_record(request, uid):
    r = records_qs().filter(uid=uid).first()
    target = r
    for _ in range(10):  # merged away (maybe repeatedly): the SPA follows to the record it lives on in
        if not (target and target.deleted_at and target.merged_into_id):
            break
        target = records_qs().filter(pk=target.merged_into_id).first()
    if target is not r and target and not target.deleted_at:
        return err("merged", 410, uid=str(target.uid), kind=target.kind)
    if not r or (r.deleted_at and request.rank < MAINT):
        return err("not_found", 404)
    return JsonResponse(ser_record(r, visible_fields(request.rank)))


@needs(MAINT)
def update_record(request, uid):
    body = request.json
    fields = list(FieldDef.objects.all())
    with transaction.atomic():
        r = Record.objects.select_for_update().filter(uid=uid, deleted_at__isnull=True).first()
        if not r:
            return err("not_found", 404)
        if body.get("version") != r.version:
            return err("version_conflict", 409, record=ser_record(r, visible_fields(request.rank)))
        before = snapshot(r)
        if errors := _apply(request.rank, r, body, fields):
            return err("validation", fields=errors)
        change = audit.diff(before, snapshot(r))
        if change:
            r.version += 1
            r.updated_by = request.user
            r.save()
            audit.log(request.user, "update", "record", r.uid, r.display_name, change)
            _add_new_options(request.user, fields, r)
            # editing answers a review that was yours before the edit; then open ones follow a new responsible
            reviews.finish(r.reviews.filter(assignee=request.user), "edited", request.user)
            reviews.reassign(r)
    return JsonResponse(ser_record(r, visible_fields(request.rank)))


def _flag(request, name):
    """A yes/no option given as query parameter (?name=1) or JSON body key."""
    v = request.GET.get(name)
    if v is None and isinstance(getattr(request, "json", None), dict):
        v = request.json.get(name)
    return v in (True, 1, "1", "true", "yes")


@needs(MAINT)
def delete_record(request, uid):
    """Move a record to the recycle bin; ?with_persons=1 on a company takes its live persons along."""
    with transaction.atomic():
        r = Record.objects.select_for_update().filter(uid=uid, deleted_at__isnull=True).first()
        if not r:
            return err("not_found", 404)
        deleted = delete_tree(request.user, r, _flag(request, "with_persons"))
    return JsonResponse({"ok": True, "deleted": deleted})


def delete_with_persons(user, company, changes=None, username=None):
    """Soft-delete a company and all its live persons in one transaction. Each person is audited like a normal
    delete, marked {"with_company": [None, <company name>]}. Returns the deleted uids, the company first."""
    with transaction.atomic():
        persons = list(Record.objects.select_for_update().filter(company=company, kind=Kind.PERSON,
                                                                 deleted_at__isnull=True).order_by("pk"))
        marker = {"with_company": [None, company.display_name]}
        for p in persons:
            _soft_delete(user, p, (changes or {}) | marker, username)
        _soft_delete(user, company, changes, username)
    return [str(company.uid), *(str(p.uid) for p in persons)]


def _soft_delete(user, r, changes=None, username=None):
    r.deleted_at, r.updated_by = timezone.now(), user
    r.version += 1
    r.save()
    reviews.finish(r.reviews.all(), "cancelled")
    audit.log(user, "delete", "record", r.uid, r.display_name, changes, username)


def delete_tree(user, r, with_persons=False, username=None):
    """Move a locked record to the recycle bin; a company with_persons takes its live persons along
    (UI, bulk edit and the REST API share this). Returns the uids moved, the record first."""
    if with_persons and r.kind == Kind.COMPANY:
        return delete_with_persons(user, r, username=username)
    _soft_delete(user, r, None, username)
    return [str(r.uid)]


@needs(MAINT)
def restore_record(request, uid):
    """Restore a record from the recycle bin. A company also takes back the persons listed in {"persons": [uid, …]}
    (the undo of a delete with persons); others in the list are ignored. They are returned in "persons"."""
    with transaction.atomic():
        r = Record.objects.select_for_update().filter(uid=uid, deleted_at__isnull=False).first()
        if not r:
            return err("not_found", 404)
        persons = []
        wanted = request.json.get("persons") if isinstance(request.json, dict) else None
        if r.kind == Kind.COMPANY and isinstance(wanted, list):
            uids = [u for u in wanted if isinstance(u, str) and _is_uuid(u)]
            persons = list(Record.objects.select_for_update().filter(uid__in=uids, company=r, kind=Kind.PERSON,
                                                                     deleted_at__isnull=False))
        for p in persons:
            _restore(request.user, p)
        _restore(request.user, r)
    fields = visible_fields(request.rank)
    if persons:
        return JsonResponse({**ser_record(r, fields), "persons": [ser_record(p, fields) for p in persons]})
    return JsonResponse(ser_record(r, fields))


def _is_uuid(v):
    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False


def _restore(user, r):
    if r.merged_into_id:  # back as its own contact: the importer updates it again via its legacy id
        t = Record.objects.select_for_update().get(pk=r.merged_into_id)
        if r.legacy_id in t.merged_legacy_ids:
            t.merged_legacy_ids.remove(r.legacy_id)
            t.save(update_fields=["merged_legacy_ids"])
        r.merged_into = None
    r.deleted_at, r.updated_by = None, user
    r.version += 1
    r.save()
    audit.log(user, "restore", "record", r.uid, r.display_name)


@needs(MAINT)
def trash(request):
    fields = visible_fields(request.rank)
    return JsonResponse({"records": ser_records(Record.objects.filter(deleted_at__isnull=False).order_by("-deleted_at"), fields)})


@needs(ADMIN)
def purge_record(request, uid):
    r = Record.objects.filter(uid=uid, deleted_at__isnull=False).first()
    if not r:
        return err("not_found", 404)
    audit.log(request.user, "purge", "record", r.uid, r.display_name, audit.diff(snapshot(r), {}))
    r.delete()
    return JsonResponse({"ok": True})


@needs(READ)
def history(request, uid):
    entries = AuditEntry.objects.filter(target_type="record", target_id=str(uid))[:200]
    return JsonResponse({"entries": [ser_audit(e, request.rank) for e in entries]})


def ser_audit(e, rank, kinds=None):
    """kinds: {record uid: person/company} so the UI can name and link the object."""
    changes = e.changes
    if rank < ADMIN:  # hide values of fields the user may not see
        hidden = {f.key for f in FieldDef.objects.all() if not f.visible(rank)}
        changes = {k: v for k, v in changes.items() if k not in hidden}
    return {"id": e.id, "at": e.at.isoformat(), "user": e.username, "action": e.action,
            "target_type": e.target_type, "target_id": e.target_id, "target_label": e.target_label,
            "kind": (kinds or {}).get(e.target_id), "changes": changes}


def record_kinds(entries):
    uids = []
    for e in entries:
        if e.target_type == "record":
            try:
                uids.append(uuid.UUID(e.target_id))
            except ValueError:
                pass
    return {str(u): k for u, k in Record.objects.filter(uid__in=uids).values_list("uid", "kind")}


# ---------------------------------------------------------------- images

def _sniff(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


@needs(READ)
def get_image(request, uid):
    r = Record.objects.filter(uid=uid).only("image", "image_type").first()
    if not r or not r.image_type:
        return HttpResponse(status=404)
    resp = HttpResponse(bytes(r.image), content_type=f"image/{r.image_type}")
    resp["Cache-Control"] = "private, max-age=31536000, immutable"  # URL carries ?v=<version>
    return resp


@needs(MAINT)
def put_image(request, uid):
    data = request.body
    if len(data) > MAX_IMAGE:
        return err("image_too_large", 413)
    typ = _sniff(data)
    if not typ:
        return err("invalid_image")
    with transaction.atomic():
        r = Record.objects.select_for_update().filter(uid=uid, deleted_at__isnull=True).first()
        if not r:
            return err("not_found", 404)
        r.image, r.image_type, r.updated_by = data, typ, request.user
        r.version += 1
        r.save()
        audit.log(request.user, "update", "record", r.uid, r.display_name, {"image": [None, f"{typ}, {len(data)} B"]})
    return JsonResponse(ser_record(r, visible_fields(request.rank)))


@needs(MAINT)
def delete_image(request, uid):
    with transaction.atomic():
        r = Record.objects.select_for_update().filter(uid=uid, deleted_at__isnull=True).first()
        if not r:
            return err("not_found", 404)
        r.image, r.image_type, r.updated_by = None, "", request.user
        r.version += 1
        r.save()
        audit.log(request.user, "update", "record", r.uid, r.display_name, {"image": ["image", None]})
    return JsonResponse(ser_record(r, visible_fields(request.rank)))


# ---------------------------------------------------------------- me

@needs(READ)
def update_me(request):
    body, p, u = request.json, profile_of(request.user), request.user
    if "language" in body:
        if body["language"] not in ("", "de", "en"):
            return err("validation", fields={"language": "invalid"})
        p.language = body["language"]
        p.save()
    if "password" in body:
        if p.source != "local":
            return err("forbidden", 403)
        if not u.check_password(body.get("old_password", "")):
            return err("validation", fields={"old_password": "invalid"})
        if len(body["password"]) < 10:
            return err("validation", fields={"password": "too_short"})
        u.set_password(body["password"])
        u.save()
        login(request, u, backend="django.contrib.auth.backends.ModelBackend")
        audit.log(u, "password", "user", u.id, u.username)
    return JsonResponse({"user": ser_user(u)})


@needs(MAINT)
def propagate(request, uid):
    """Carry company changes over to its persons: without `selected` a preview, with it the update."""
    b = request.json
    company = Record.objects.filter(uid=uid, kind=Kind.COMPANY, deleted_at__isnull=True).first()
    if not company:
        return err("not_found", 404)
    changes = b.get("changes") if isinstance(b.get("changes"), dict) else {}
    if "selected" not in b:
        return JsonResponse({"items": batch.plan(company, changes)})
    with transaction.atomic():
        updated, errors = batch.apply(company, changes, b["selected"] or [], request.user, request.rank)
    return JsonResponse({"updated": updated, "errors": errors})


# ---------------------------------------------------------------- reviews & proposals

def ser_proposal(p):
    return {"id": p.id, "record": str(p.record.uid) if p.record_id else None,
            "record_kind": p.record.kind if p.record_id else p.record_kind, "label": p.label,
            "kind": p.kind, "changes": p.changes, "base": p.base,
            "comment": p.comment, "reason": p.reason, "proposer": p.proposer_name,
            "created_at": p.created_at.isoformat(), "status": p.status}


def workflow(request):
    """Part of bootstrap/changes: my open reviews; pending proposals (maintainers: all, others: their own)."""
    mine = reviews.open_reviews().filter(assignee=request.user, record__deleted_at__isnull=True).select_related("record")
    props = Proposal.objects.filter(Q(record__isnull=True) | Q(record__deleted_at__isnull=True), status="pending") \
        .select_related("record")
    if request.rank < MAINT:
        props = props.filter(proposer=request.user)
    return {"reviews": [{"id": rv.id, "record": str(rv.record.uid), "created_at": rv.created_at.isoformat(),
                         "reason": rv.reason} for rv in mine],
            "proposals": [ser_proposal(p) for p in props.order_by("created_at")]}


def dashboard_prefs(request):
    from .dashboard import prefs  # dashboard builds on this module
    return prefs(request)


def _core(r):
    return {"first_name": r.first_name, "last_name": r.last_name, "name": r.name,
            "company": str(r.company.uid) if r.company_id and r.company else None}


@needs(READ)
def propose(request, uid):
    """Anyone may propose; changes are validated as if a maintainer made them, but only on fields they can see."""
    b = request.json
    r = records_qs().filter(uid=uid, deleted_at__isnull=True).first()
    if not r:
        return err("not_found", 404)
    p = Proposal(record=r, kind=b.get("kind"), proposer=request.user, proposer_name=request.user.username)
    logged, error = _fill_proposal(request, r, p, b)
    if error:
        return error
    target = p.record  # "company gone" is proposed on the company, also when started from a person
    with transaction.atomic():
        if p.reason == "company_gone":
            same = Proposal.objects.filter(record=target, kind="delete", reason="company_gone", status="pending").first()
            if same:  # someone already reported it
                reviews.finish(_company_reviews(target, request.user), "proposed", request.user)
                return JsonResponse({"proposal": ser_proposal(same), "existing": True})
        p.save()
        audit.log(request.user, "propose", "record", target.uid, target.display_name, logged)
        reviews.finish(r.reviews.filter(assignee=request.user), "proposed", request.user)
        if p.reason == "company_gone":
            reviews.finish(_company_reviews(target, request.user), "proposed", request.user)
    return JsonResponse({"proposal": ser_proposal(p)}, status=201)


@needs(READ)
def propose_new(request):
    """A new person or company for a maintainer to create. Body like POST /api/records, plus `comment`."""
    b = request.json
    if b.get("kind") not in Kind.values:
        return err("invalid_kind")
    p = Proposal(kind="create", record_kind=b["kind"], proposer=request.user, proposer_name=request.user.username)
    logged, error = _fill_proposal(request, None, p, b)
    if error:
        return error
    p.save()
    audit.log(request.user, "propose", "proposal", p.id, p.label, logged)
    return JsonResponse({"proposal": ser_proposal(p)}, status=201)


def _company_reviews(company, user):
    return Review.objects.filter(Q(record=company) | Q(record__company=company), assignee=user)


DELETE_REASONS = {"person": ("left", "company_gone", "other"), "company": ("company_gone", "other")}


def _fill_proposal(request, r, p, b):
    """Set comment, changes and base of `p` from a form body. Returns (audit changes, error response or None)."""
    p.comment = str(b.get("comment") or "").strip()[:5000]
    if p.kind == "change":
        fields = [f for f in FieldDef.objects.all() if f.visible(request.rank)]
        probe = Record(kind=r.kind, first_name=r.first_name, last_name=r.last_name, name=r.name,
                       company_id=r.company_id, data=dict(r.data))
        if errors := _apply(max(request.rank, MAINT), probe, b, fields):
            return None, err("validation", fields=errors)
        old_core, new_core = _core(r), _core(probe)
        core = [k for k in old_core if old_core[k] != new_core[k]]
        data = [k for k in dict.fromkeys([*r.data, *probe.data]) if r.data.get(k) != probe.data.get(k)]
        if not core and not data:
            return None, err("no_changes")
        p.changes = {"core": {k: new_core[k] for k in core}, "data": {k: probe.data.get(k) for k in data}}
        p.base = {"core": {k: old_core[k] for k in core}, "data": {k: r.data.get(k) for k in data}}
        logged = {k: [p.base[s][k], p.changes[s][k]] for s in ("core", "data") for k in p.changes[s]}
        if "company" in logged:  # history shows names, like record snapshots do
            logged["company"] = [Record.objects.filter(uid=v).values_list("name", flat=True).first() if v else None
                                 for v in logged["company"]]
    elif p.kind == "create":  # a new contact: validated like a maintainer creating it, on the fields the proposer sees
        fields = [f for f in FieldDef.objects.all() if f.visible(request.rank)]
        probe = Record(kind=p.record_kind)
        if errors := _apply(max(request.rank, MAINT), probe, b, fields):
            return None, err("validation", fields=errors)
        core = {k: v for k, v in _core(probe).items() if v}
        p.changes, p.base = {"core": core, "data": probe.data}, {}
        logged = {"kind": [None, p.record_kind]} | {k: [None, v] for k, v in (core | probe.data).items()}
        if "company" in logged:
            logged["company"] = [None, probe.company.name]
    elif p.kind == "delete":
        p.reason = str(b.get("reason") or "other")
        if p.reason not in DELETE_REASONS[r.kind]:
            return None, err("validation", fields={"reason": "invalid"})
        if p.reason == "other" and not p.comment:
            return None, err("validation", fields={"comment": "required"})
        if p.reason == "company_gone" and r.kind == Kind.PERSON:
            if not (r.company_id and r.company and not r.company.deleted_at):
                return None, err("validation", fields={"reason": "invalid"})
            p.record = r.company
        logged = {"delete": [None, True], "reason": [None, p.reason]}
    else:
        return None, err("invalid_kind")
    if p.comment:
        logged["comment"] = [None, p.comment]
    return logged, None


@needs(READ)
def own_proposal(request, pk):
    """The proposer edits (PATCH, same body as proposing) or withdraws (DELETE) a pending proposal."""
    with transaction.atomic():
        p = Proposal.objects.select_for_update().filter(pk=pk, status="pending", proposer=request.user).first()
        if not p:
            return err("not_found", 404)
        r = records_qs().get(pk=p.record_id) if p.record_id else None  # create: no record yet
        target = ("record", r.uid) if r else ("proposal", p.id)
        if request.method == "DELETE":
            p.status, p.decided_at = "withdrawn", timezone.now()
            p.save()
            audit.log(request.user, "withdraw", *target, p.label, {"kind": [None, p.kind]})
            return JsonResponse({"ok": True})
        logged, error = _fill_proposal(request, r, p, request.json)
        if error:
            return error
        p.save()
        audit.log(request.user, "propose", *target, p.label, logged)
    return JsonResponse({"proposal": ser_proposal(p)})


@needs(MAINT)
def decide_proposal(request, pk, action):
    note = str(request.json.get("note") or "").strip()[:5000]
    with transaction.atomic():
        p = Proposal.objects.select_for_update().filter(pk=pk, status="pending").first()
        if not p:
            return err("not_found", 404)
        extra = {"proposed_by": [None, p.proposer_name]} | ({"note": [None, note]} if note else {})
        if p.kind == "create":
            r = None
            if action == "accept":
                body = {**p.changes.get("core", {}), "data": p.changes.get("data", {})}
                if isinstance(request.json.get("override"), dict):  # the reviewer adjusted the proposal
                    body = request.json["override"]
                    extra["adjusted"] = [None, True]
                fields = list(FieldDef.objects.all())
                r = Record(kind=p.record_kind, updated_by=request.user)
                if errors := _apply(request.rank, r, body, fields):
                    return err("validation", fields=errors)
                r.save()
                audit.log(request.user, "create", "record", r.uid, r.display_name, audit.diff({}, snapshot(r)) | extra)
                _add_new_options(request.user, fields, r)
                p.record = r
            else:
                audit.log(request.user, "reject", "proposal", p.id, p.label, extra)
            p.status = "accepted" if action == "accept" else "rejected"
            p.decided_by, p.decided_at, p.decision_note = request.user, timezone.now(), note
            p.save()
            return JsonResponse({"proposal": ser_proposal(p),
                                 "record": ser_record(records_qs().get(pk=r.pk), visible_fields(request.rank)) if r else None})
        # of=self: Postgres can't lock the nullable side of the company join
        r = Record.objects.select_for_update(of=("self",)).select_related("company").get(pk=p.record_id)
        if action == "accept":
            if r.deleted_at:
                return err("not_found", 404)
            if p.kind == "delete":
                extra["reason"] = [None, p.reason]
                if p.reason == "company_gone":  # the company and everyone working there
                    for person in Record.objects.select_for_update().filter(company=r, deleted_at__isnull=True):
                        _soft_delete(request.user, person, extra)
                _soft_delete(request.user, r, extra)
            else:
                fields = list(FieldDef.objects.all())
                before = snapshot(r)
                body = {**p.changes.get("core", {}), "data": p.changes.get("data", {})}
                if isinstance(request.json.get("override"), dict):  # the reviewer adjusted the proposal
                    body = request.json["override"]
                    extra["adjusted"] = [None, True]
                if errors := _apply(request.rank, r, body, fields):
                    return err("validation", fields=errors)
                if change := audit.diff(before, snapshot(r)):
                    r.version += 1
                    r.updated_by = request.user
                    r.save()
                    audit.log(request.user, "update", "record", r.uid, r.display_name, change | extra)
                    _add_new_options(request.user, fields, r)
                    reviews.reassign(r)
        else:
            audit.log(request.user, "reject", "record", r.uid, r.display_name, extra)
        p.status = "accepted" if action == "accept" else "rejected"
        p.decided_by, p.decided_at, p.decision_note = request.user, timezone.now(), note
        p.save()
    return JsonResponse({"proposal": ser_proposal(p), "record": ser_record(records_qs().get(pk=r.pk),
                                                                           visible_fields(request.rank))})


@needs(READ)
def review_confirm(request, uid):
    r = records_qs().filter(uid=uid, deleted_at__isnull=True).first()
    if not r:
        return err("not_found", 404)
    if request.rank < MAINT and not r.reviews.filter(assignee=request.user, done_at__isnull=True).exists():
        return err("forbidden", 403)
    reviews.confirm(r, request.user)
    return JsonResponse(ser_record(records_qs().get(pk=r.pk), visible_fields(request.rank)))


@needs(ADMIN)
def review_request(request, uid):
    r = Record.objects.filter(uid=uid, deleted_at__isnull=True).first()
    if not r:
        return err("not_found", 404)
    return JsonResponse(reviews.start([r], "manual", request.user))


@needs(ADMIN)
def reviews_admin(request):
    if request.method == "POST":
        scope = request.json.get("scope")
        if scope == "due":
            recs = reviews.due(max(Settings.get().review_interval_months, 1))
        elif scope == "all":
            recs = reviews.live()
        else:
            return err("invalid")
        return JsonResponse(reviews.start(recs, "manual", request.user))
    return JsonResponse(reviews.stats())


@needs(ADMIN)
def mail_test(request):
    from django.core.mail import EmailMessage
    s = Settings.get()
    to = str(request.json.get("to") or request.user.email or "").strip()
    if not reviews.mail_ready(s):
        return JsonResponse({"error": msg("mail_not_configured")})
    if not to:
        return JsonResponse({"error": msg("mail_no_recipient")})
    try:
        with reviews.mail_connection(s) as conn:
            EmailMessage("Kartei test", "This is a test message from Kartei.", reviews.mail_from(s), [to],
                         connection=conn).send()
    except Exception as e:  # report anything the mail server or Microsoft 365 says
        return JsonResponse({"error": str(e) or e.__class__.__name__})
    return JsonResponse({"ok": True, "to": to})


# ---------------------------------------------------------------- admin: fields

FIELD_ATTRS = ["label_de", "label_en", "help_de", "help_en", "regex", "applies_to", "type", "options", "open_options",
               "required",
               "min_value", "max_value",
               "decimals", "visible_to", "editable_by", "searchable", "vcard",
               "vcard_label", "import_aliases", "quick_filter"]
COMPATIBLE = {("text", "longtext"), ("longtext", "text"), ("select", "multiselect"), ("phone", "text"),
              ("email", "text"), ("url", "text"), ("integer", "decimal"), ("user", "users"),
              ("text", "contact")}
TO_LIST = {("select", "multiselect"), ("user", "users")}  # stored values are wrapped into lists


def _field_from_body(f, body):
    """Flatten the SPA's {label: {de,en}} shape and copy attributes. Returns errors."""
    b = dict(body)
    for nested in ("label", "help"):
        if isinstance(b.get(nested), dict):
            b[f"{nested}_de"], b[f"{nested}_en"] = b[nested].get("de", ""), b[nested].get("en", "")
    if "min" in b:
        b["min_value"] = b["min"] if b["min"] not in ("", None) else None
    if "max" in b:
        b["max_value"] = b["max"] if b["max"] not in ("", None) else None
    old_type = f.type if f.pk else None
    for a in FIELD_ATTRS:
        if a in b:
            setattr(f, a, b[a])
    errors = {}
    if not (f.label_de or "").strip() or not (f.label_en or "").strip():
        errors["label"] = "required"
    if f.type not in FieldType.values:
        errors["type"] = "invalid"
    if f.applies_to not in ("person", "company", "both"):
        errors["applies_to"] = "invalid"
    if f.visible_to not in Role.values or f.editable_by not in (Role.MAINTAINER, Role.ADMIN):
        errors["visible_to"] = "invalid"
    f.regex = (f.regex or "").strip()
    if f.regex:
        if f.type not in REGEX_TYPES:
            f.regex = ""
        else:
            try:
                re.compile(f.regex)
            except re.error:
                errors["regex"] = "invalid_regex"
    if f.type in ("select", "multiselect"):
        opts = f.options if isinstance(f.options, list) else []
        values = [str(o.get("value", "")).strip() for o in opts if isinstance(o, dict)]
        if len(values) != len(opts) or "" in values or len(set(values)) != len(values):
            errors["options"] = "invalid"
        else:
            f.options = [{"value": v, "de": o.get("de") or v, "en": o.get("en") or v} for v, o in zip(values, opts)]
    else:
        f.options = []
    aliases = f.import_aliases.split(",") if isinstance(f.import_aliases, str) else f.import_aliases
    if isinstance(aliases, list) and all(isinstance(a, str) for a in aliases):
        f.import_aliases = list(dict.fromkeys(a.strip() for a in aliases if a.strip()))
    else:
        errors["import_aliases"] = "invalid"
    if (old_type, f.type) == ("text", "contact"):
        f.open_options = True  # existing text values stay valid as free text
    if old_type and old_type != f.type and (old_type, f.type) not in COMPATIBLE \
            and Record.objects.filter(data__has_key=f.key).exists():
        errors["type"] = "incompatible_type"
    if "section" in b:  # section id, None = "Other"
        sec = FieldSection.objects.filter(pk=b["section"]).first() if isinstance(b["section"], int) else None
        if b["section"] not in (None, "") and not sec:
            errors["section"] = "invalid"
        f.section = sec
    if "copy_from" in b:
        src = FieldDef.objects.filter(pk=b["copy_from"]).first() if b["copy_from"] else None
        if b["copy_from"] and (not src or not src.applies("company")):
            errors["copy_from"] = "invalid"
        f.copy_from = src
    try:
        if f.min_value is not None and f.max_value is not None and float(f.min_value) > float(f.max_value):
            errors["min"] = "invalid"
    except (TypeError, ValueError):
        errors["min"] = "invalid_number"
    return errors


def _field_snapshot(f):
    return {**{a: getattr(f, a) for a in FIELD_ATTRS}, "copy_from": f.copy_from_id, "section": f.section_id,
            "archived": f.archived,
            "min_value": str(f.min_value) if f.min_value is not None else None,
            "max_value": str(f.max_value) if f.max_value is not None else None}


@needs(ADMIN)
def fields_list(request):
    return JsonResponse({"fields": [ser_field(f) for f in FieldDef.objects.all()], "sections": sections_list(),
                         "vcard_targets": VCARD_TARGETS})


@needs(ADMIN)
def field_create(request):
    f = FieldDef(applies_to="person", label_de="", label_en="")
    if errors := _field_from_body(f, request.json):
        return err("validation", fields=errors)
    base = slugify(request.json.get("key") or f.label_en or f.label_de).replace("-", "_")[:50] or "field"
    key, i = base, 2
    while FieldDef.objects.filter(key=key).exists():
        key, i = f"{base}_{i}", i + 1
    f.key = key
    f.order = (FieldDef.objects.order_by("-order").values_list("order", flat=True).first() or 0) + 10
    f.save()
    audit.log(request.user, "create", "field", f.id, f.label_de, audit.diff({}, _field_snapshot(f)))
    return JsonResponse(ser_field(f), status=201)


def _wrap_lists(user, f, old_type):
    if (old_type, f.type) in TO_LIST:
        for r in Record.objects.filter(data__has_key=f.key):
            old = r.data[f.key]
            if not isinstance(old, list):
                r.data[f.key] = [old]
                r.version += 1
                r.save()
                audit.log(user, "update", "record", r.uid, r.display_name, {f.key: [old, [old]]})


@needs(ADMIN)
def field_update(request, pk):
    f = FieldDef.objects.filter(pk=pk).first()
    if not f:
        return err("not_found", 404)
    before = _field_snapshot(f)
    if "archived" in request.json:
        f.archived = bool(request.json["archived"])
    if errors := _field_from_body(f, request.json):
        return err("validation", fields=errors)
    with transaction.atomic():
        f.save()
        if change := audit.diff(before, _field_snapshot(f)):
            audit.log(request.user, "update", "field", f.id, f.label_de, change)
        _wrap_lists(request.user, f, before["type"])
    return JsonResponse(ser_field(f, user_options() if f.type in USER_TYPES else None))


@needs(ADMIN)
def field_delete(request, pk):
    f = FieldDef.objects.filter(pk=pk).first()
    if not f:
        return err("not_found", 404)
    if Record.objects.filter(data__has_key=f.key).exists():
        return err("field_has_data", 409)  # archive instead
    audit.log(request.user, "delete", "field", f.id, f.label_de, audit.diff(_field_snapshot(f), {}))
    f.delete()
    return JsonResponse({"ok": True})


@needs(ADMIN)
def fields_reorder(request):
    """{ids: [field ids in the new order], moves: {field id: section id or null}} (drag & drop between sections)."""
    b = request.json if isinstance(request.json, dict) else {}
    ids, moves = b.get("ids", []), b.get("moves") or {}
    if not isinstance(moves, dict):
        return err("validation", fields={"moves": "invalid"})
    with transaction.atomic():
        for pk, sid in moves.items():
            f = FieldDef.objects.filter(pk=pk).first()
            if not f:
                continue
            if sid is not None and not (isinstance(sid, int) and FieldSection.objects.filter(pk=sid).exists()):
                transaction.set_rollback(True)
                return err("validation", fields={"section": "invalid"})
            if f.section_id != sid:
                audit.log(request.user, "update", "field", f.id, f.label_de, {"section": [f.section_id, sid]})
                f.section_id = sid
                f.save(update_fields=["section"])
        for i, pk in enumerate(ids):
            FieldDef.objects.filter(pk=pk).update(order=(i + 1) * 10)
    audit.log(request.user, "reorder", "field", "-", "", {"order": [None, ids]})
    return fields_list(request)


# ---------------------------------------------------------------- admin: field sections

def _section_from_body(s, body):
    """{label: {de, en}}; one language is enough, the other one gets the same text. Returns errors."""
    label = body.get("label") if isinstance(body.get("label"), dict) else {}
    de, en = str(label.get("de") or "").strip()[:100], str(label.get("en") or "").strip()[:100]
    if "label" in body:
        if not (de or en):
            return {"label": "required"}
        s.label_de, s.label_en = de or en, en or de
    return {}


def _new_section_key(label):
    base = slugify(label).replace("-", "_")[:50] or "section"
    key, i = base, 2
    while FieldSection.objects.filter(key=key).exists():
        key, i = f"{base}_{i}", i + 1
    return key


def _next_section_order():
    return (FieldSection.objects.order_by("-order").values_list("order", flat=True).first() or 0) + 10


def _section_snapshot(s):
    return {"key": s.key, "label_de": s.label_de, "label_en": s.label_en, "order": s.order}


@needs(ADMIN)
def sections_get(request):
    return JsonResponse({"sections": sections_list()})


@needs(ADMIN)
def section_create(request):
    s = FieldSection(label_de="", label_en="")
    if errors := _section_from_body(s, {"label": None, **(request.json if isinstance(request.json, dict) else {})}):
        return err("validation", fields=errors)
    s.key = _new_section_key(s.label_en or s.label_de)
    s.order = _next_section_order()
    s.save()
    audit.log(request.user, "create", "section", s.id, s.label_de, audit.diff({}, _section_snapshot(s)))
    return JsonResponse(ser_section(s), status=201)


@needs(ADMIN)
def section_update(request, pk):
    s = FieldSection.objects.filter(pk=pk).first()
    if not s:
        return err("not_found", 404)
    before = _section_snapshot(s)
    if errors := _section_from_body(s, request.json if isinstance(request.json, dict) else {}):
        return err("validation", fields=errors)
    s.save()
    if change := audit.diff(before, _section_snapshot(s)):
        audit.log(request.user, "update", "section", s.id, s.label_de, change)
    return JsonResponse(ser_section(s))


@needs(ADMIN)
def section_delete(request, pk):
    """Only when no active field uses it (409 section_in_use), unless ?move_to=<section id>|other moves its fields."""
    s = FieldSection.objects.filter(pk=pk).first()
    if not s:
        return err("not_found", 404)
    move_to = request.GET.get("move_to", "")
    target = None
    if move_to and move_to != "other":
        target = FieldSection.objects.filter(pk=int(move_to) if move_to.isdigit() else 0).exclude(pk=s.pk).first()
        if not target:
            return err("validation", fields={"move_to": "invalid"})
    in_use = s.fields.filter(archived=False).count()
    if in_use and not move_to:
        return err("section_in_use", 409, count=in_use)
    with transaction.atomic():
        for f in s.fields.all():  # archived ones too; without move_to they fall back to "Other"
            new = target.id if target else None
            audit.log(request.user, "update", "field", f.id, f.label_de, {"section": [s.id, new]})
            f.section_id = new
            f.save(update_fields=["section"])
        audit.log(request.user, "delete", "section", s.id, s.label_de, audit.diff(_section_snapshot(s), {}))
        s.delete()
    return JsonResponse({"ok": True})


@needs(ADMIN)
def sections_reorder(request):
    ids = request.json.get("ids", []) if isinstance(request.json, dict) else []
    with transaction.atomic():
        for i, pk in enumerate(ids):
            FieldSection.objects.filter(pk=pk).update(order=(i + 1) * 10)
    audit.log(request.user, "reorder", "section", "-", "", {"order": [None, ids]})
    return sections_get(request)


FIELDS_FORMAT = "kartei-fields"
FIELDS_VERSION = 2
KEY_RE = re.compile(r"^[a-z0-9_]{1,64}$")


def fields_document():
    """All sections and field definitions (archived too) as a versioned file. List order = order; fields refer to
    their section and copy_from source by key."""
    sections = list(FieldSection.objects.all())
    skeys = {s.id: s.key for s in sections}
    fields = list(FieldDef.objects.all())
    keys = {f.id: f.key for f in fields}
    out = []
    for f in fields:
        d = ser_field(f)
        del d["id"], d["order"]
        d["section"] = skeys.get(f.section_id)
        d["copy_from"] = keys.get(f.copy_from_id)
        out.append(d)
    return {"format": FIELDS_FORMAT, "version": FIELDS_VERSION,
            "sections": [{"key": s.key, "label": {"de": s.label_de, "en": s.label_en}} for s in sections],
            "fields": out}


def _import_sections(items, user):
    """v2 sections, matched by key: new ones are appended in file order, existing ones get the file's labels
    (their order stays). Returns ({key: section}, results)."""
    out, by_key, order = [], {}, _next_section_order()
    for item in items:
        item = item if isinstance(item, dict) else {}
        key = item.get("key")
        res = {"key": str(key or ""), "label": item.get("label"), "errors": {}}
        out.append(res)
        if not isinstance(key, str) or not KEY_RE.match(key) or key in by_key:
            res.update(status="invalid", errors={"key": "invalid"})
            continue
        s = FieldSection.objects.filter(key=key).first() or FieldSection(key=key, label_de="", label_en="")
        before = _section_snapshot(s) if s.pk else {}
        if errors := _section_from_body(s, {"label": item.get("label")}):
            res.update(status="invalid", errors=errors)
            continue
        if not s.pk:
            s.order, order = order, order + 10
        s.save()
        by_key[key] = s
        change = audit.diff(before, _section_snapshot(s))
        res["status"] = "new" if not before else "changed" if change else "unchanged"
        if change:
            audit.log(user, "update" if before else "create", "section", s.id, s.label_de, change)
    return by_key, out


def _v1_section(label, user, results):
    """v1 files carry {de, en} per field: find the section by its German or English label, or create it."""
    if not isinstance(label, dict):
        return None
    de, en = str(label.get("de") or "").strip()[:100], str(label.get("en") or "").strip()[:100]
    if not (de or en):
        return None
    s = (FieldSection.objects.filter(label_de__iexact=de).first() if de else None) \
        or (FieldSection.objects.filter(label_en__iexact=en).first() if en else None)
    if not s:
        s = FieldSection(key=_new_section_key(en or de), label_de=de or en, label_en=en or de, order=_next_section_order())
        s.save()
        audit.log(user, "create", "section", s.id, s.label_de, audit.diff({}, _section_snapshot(s)))
        results.append({"key": s.key, "label": {"de": s.label_de, "en": s.label_en}, "status": "new", "errors": {}})
    return s.id


def import_fields(doc, user=None, apply=False):
    """Preview (apply=False, rolled back) or apply a field file (v1 or v2), matched by key. Sections and fields not in
    the file stay untouched. Returns {"sections": [...], "fields": [...]}, each [{key, label, status:
    new|changed|unchanged|invalid, errors}] in file order; fields also list the changed attributes."""
    ok = isinstance(doc, dict) and doc.get("format") == FIELDS_FORMAT and doc.get("version", 1) in (1, 2)
    items = doc.get("fields") if ok else None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("invalid_format")
    v2 = doc.get("version") == 2
    if v2 and not isinstance(doc.get("sections", []), list):
        raise ValueError("invalid_format")
    out, saved, seen = [], [], set()
    company_keys = set(FieldDef.objects.filter(applies_to__in=["company", "both"]).values_list("key", flat=True))
    company_keys |= {i.get("key") for i in items if i.get("applies_to") in ("company", "both")}
    with transaction.atomic():
        sections, section_out = _import_sections(doc.get("sections", []), user) if v2 else ({}, [])
        order = (FieldDef.objects.order_by("-order").values_list("order", flat=True).first() or 0) + 10
        for item in items:
            key = item.get("key")
            res = {"key": str(key or ""), "label": item.get("label"), "changes": [], "errors": {}}
            out.append(res)
            if not isinstance(key, str) or not KEY_RE.match(key) or key in seen:
                res.update(status="invalid", errors={"key": "invalid"})
                continue
            seen.add(key)
            f = FieldDef.objects.filter(key=key).first() or FieldDef(key=key, applies_to="person", label_de="", label_en="")
            before = _field_snapshot(f) if f.pk else {}
            body = {k: v for k, v in item.items() if k not in ("id", "key", "order", "copy_from", "section")}
            unknown_section = False
            if "section" in item:
                if not v2:
                    body["section"] = _v1_section(item["section"], user, section_out)
                elif item["section"] in (None, ""):
                    body["section"] = None
                else:
                    sec = sections.get(item["section"]) or FieldSection.objects.filter(key=str(item["section"])).first()
                    body["section"], unknown_section = (sec.id if sec else None), not sec
            errors = _field_from_body(f, body)
            if unknown_section:
                errors["section"] = "invalid"
            if item.get("copy_from") and item["copy_from"] not in company_keys:
                errors["copy_from"] = "invalid"
            if errors:
                res.update(status="invalid", errors=errors)
                continue
            if "archived" in item:
                f.archived = bool(item["archived"])
            if not f.pk:
                f.order, order = order, order + 10
            f.save()
            saved.append((res, f, item, before))
        for res, f, item, before in saved:  # copy_from once every field of the file exists
            if "copy_from" in item:
                f.copy_from = FieldDef.objects.filter(key=item["copy_from"]).first() if item["copy_from"] else None
                f.save(update_fields=["copy_from"])
            f.refresh_from_db()
            change = audit.diff(before, _field_snapshot(f))
            res["status"] = "new" if not before else "changed" if change else "unchanged"
            if before:
                res["changes"] = sorted(change)
            if change:
                audit.log(user, "update" if before else "create", "field", f.id, f.label_de, change)
            if before:
                _wrap_lists(user, f, before["type"])
        if not apply:
            transaction.set_rollback(True)
    return {"sections": section_out, "fields": out}


@needs(ADMIN)
def fields_export(request):
    return JsonResponse(fields_document())


@needs(ADMIN)
def fields_import(request):
    b = request.json if isinstance(request.json, dict) else {}
    try:
        result = import_fields(b.get("document"), request.user, apply=bool(b.get("apply")))
    except ValueError as e:
        return err(str(e))
    return JsonResponse({"applied": bool(b.get("apply")), **result})


# ---------------------------------------------------------------- admin: users

def _user_snapshot(u):
    d = ser_user(u)
    d.pop("last_login")
    return d


def _admins_left(excluding):
    return (User.objects.filter(is_active=True).exclude(pk=excluding.pk)
            .filter(profile__role=Role.ADMIN).exists()
            or User.objects.filter(is_active=True, is_superuser=True).exclude(pk=excluding.pk).exists())


@needs(ADMIN)
def users_list(request):
    return JsonResponse({"users": [ser_user(u) for u in User.objects.order_by("username")]})


@needs(ADMIN)
def user_create(request):
    b = request.json
    username = str(b.get("username", "")).strip()
    errors = {}
    if not username:
        errors["username"] = "required"
    elif User.objects.filter(username__iexact=username).exists():
        errors["username"] = "taken"
    if len(str(b.get("password", ""))) < 10:
        errors["password"] = "too_short"
    if b.get("role") not in Role.values:
        errors["role"] = "invalid"
    if errors:
        return err("validation", fields=errors)
    u = User.objects.create_user(username, b.get("email", ""), b["password"],
                                 first_name=b.get("first_name", ""), last_name=b.get("last_name", ""))
    Profile.objects.update_or_create(user=u, defaults={"role": b["role"], "source": "local",
                                                       "language": b.get("language", "")})
    audit.log(request.user, "create", "user", u.id, u.username, audit.diff({}, _user_snapshot(u)))
    return JsonResponse(ser_user(u), status=201)


@needs(ADMIN)
def user_update(request, pk):
    u = User.objects.filter(pk=pk).first()
    if not u:
        return err("not_found", 404)
    b, p = request.json, profile_of(u)
    before = _user_snapshot(u)
    demoting = ("role" in b and b["role"] != Role.ADMIN) or b.get("is_active") is False
    if demoting and rank_of(u) == ADMIN and not _admins_left(u):
        return err("last_admin", 409)
    if "role" in b:
        if b["role"] not in Role.values:
            return err("validation", fields={"role": "invalid"})
        if p.source == "ldap":
            return err("validation", fields={"role": "ldap_managed"})
        p.role = b["role"]
    if "language" in b and b["language"] in ("", "de", "en"):
        p.language = b["language"]
    for a in ("first_name", "last_name", "email"):
        if a in b and p.source == "local":
            setattr(u, a, str(b[a]))
    if "is_active" in b and bool(b["is_active"]) != u.is_active:
        if p.source == "ldap":  # AD role groups decide, see ldapusers
            return err("validation", fields={"is_active": "ldap_managed"})
        u.is_active = bool(b["is_active"])
    if b.get("password"):
        if p.source != "local":
            return err("validation", fields={"password": "ldap_managed"})
        if len(b["password"]) < 10:
            return err("validation", fields={"password": "too_short"})
        u.set_password(b["password"])
    u.save()
    p.save()
    change = audit.diff(before, _user_snapshot(u))
    if b.get("password"):
        change["password"] = ["***", "***"]
    if change:
        audit.log(request.user, "update", "user", u.id, u.username, change)
    return JsonResponse(ser_user(u))


@needs(ADMIN)
def user_delete(request, pk):
    u = User.objects.filter(pk=pk).first()
    if not u:
        return err("not_found", 404)
    if u == request.user:
        return err("cannot_delete_self", 409)
    if rank_of(u) == ADMIN and not _admins_left(u):
        return err("last_admin", 409)
    audit.log(request.user, "delete", "user", u.id, u.username, audit.diff(_user_snapshot(u), {}))
    u.delete()
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------- admin: settings

SETTINGS_ATTRS = ["default_language", "base_url", "trash_days", "export_interval_minutes", "oidc_enabled", "ldap_uri",
                  "ldap_start_tls", "ldap_ca_cert", "ldap_bind_dn", "ldap_user_base", "ldap_user_filter",
                  "ldap_group_admin", "ldap_group_maintainer", "ldap_group_read", "carddav_enabled",
                  "carddav_username", "graph_enabled", "graph_tenant_id", "graph_client_id", "graph_group_id",
                  "graph_folder", "review_mode", "review_interval_months", "review_campaign_month",
                  "review_campaign_day", "smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_from",
                  "review_remind_days", "proposal_notify", "proposal_notify_to",
                  "ad_enabled", "ad_ou", "ad_bind_dn", "ad_kinds", "ad_columns", "ad_max_shrink_percent"]
SETTINGS_ATTRS += ["phone_normalize", "phone_country_code"]  # quality
SETTINGS_ATTRS += ["mail_templates", "mail_transport", "mail_graph_sender"]
SETTINGS_ATTRS += ["carddav_relay_enabled", "carddav_relay_url", "carddav_relay_tls_verify", "carddav_relay_ca_cert",
                   "carddav_relay_max_delete_percent"]


def ser_settings(s):
    return {**{a: getattr(s, a) for a in SETTINGS_ATTRS},
            "ldap_bind_password_set": bool(s.ldap_bind_password_enc),
            "carddav_password_set": bool(s.carddav_password_hash), "export_root": exports.EXPORT_ROOT,
            "graph_client_secret_set": bool(s.graph_client_secret_enc), "graph_status": s.graph_status,
            "smtp_password_set": bool(s.smtp_password_enc), "mail_template_defaults": reviews.DEFAULT_TEMPLATES,
            "graph_sync_requested": s.graph_sync_requested, "ldap_users_status": s.ldap_users_status,
            "ad_bind_password_set": bool(s.ad_bind_password_enc), "ad_status": s.ad_status,
            "ad_sync_requested": s.ad_sync_requested, **relaypush.ser(s)}


def _settings_snapshot(s):
    return {**{a: getattr(s, a) for a in SETTINGS_ATTRS}, "ldap_bind_password_enc": s.ldap_bind_password_enc,
            "graph_client_secret_enc": s.graph_client_secret_enc, "smtp_password_enc": s.smtp_password_enc,
            "ad_bind_password_enc": s.ad_bind_password_enc}


@needs(ADMIN)
def settings_get(request):
    return JsonResponse(ser_settings(Settings.get()))


@needs(ADMIN)
def settings_put(request):
    s, b = Settings.get(), request.json
    before = _settings_snapshot(s)
    errors = {}
    for a in SETTINGS_ATTRS:
        if a in b:
            setattr(s, a, b[a])
    if "ldap_bind_password" in b:
        s.ldap_bind_password = str(b["ldap_bind_password"] or "")
    if "graph_client_secret" in b:
        s.graph_client_secret = str(b["graph_client_secret"] or "")
    if "smtp_password" in b:
        s.smtp_password = str(b["smtp_password"] or "")
    if "ad_bind_password" in b:
        s.ad_bind_password = str(b["ad_bind_password"] or "")
    errors |= adsync.validate(s) | relaypush.validate(s)
    if s.review_mode not in ("off", "rolling", "campaign"):
        errors["review_mode"] = "invalid"
    for a, lo, hi in [("review_interval_months", 1, 120), ("review_campaign_month", 1, 12), ("review_campaign_day", 1, 31),
                      ("smtp_port", 1, 65535), ("review_remind_days", 0, 365)]:
        if not isinstance(getattr(s, a), int) or not lo <= getattr(s, a) <= hi:
            errors[a] = "invalid_number"
    s.proposal_notify, s.proposal_notify_to = bool(s.proposal_notify), str(s.proposal_notify_to or "").strip()[:500]
    try:
        for a in filter(None, map(str.strip, s.proposal_notify_to.split(","))):
            validate_email(a)
    except ValidationError:
        errors["proposal_notify_to"] = "invalid_email"
    if s.smtp_security not in ("starttls", "ssl", "none"):
        errors["smtp_security"] = "invalid"
    if s.mail_transport not in ("smtp", "graph"):
        errors["mail_transport"] = "invalid"
    if bad := reviews.check_templates(s.mail_templates):
        errors["mail_templates"] = bad
    if s.default_language not in ("de", "en"):
        errors["default_language"] = "invalid"
    for a in ("trash_days", "export_interval_minutes"):
        if not isinstance(getattr(s, a), int) or getattr(s, a) < 0:
            errors[a] = "invalid_number"
    if not re.fullmatch(r"\+[1-9]\d{0,3}", str(s.phone_country_code)):
        errors["phone_country_code"] = "invalid"
    if s.export_interval_minutes == 0:
        errors["export_interval_minutes"] = "too_small"
    if s.ldap_user_filter and "%(user)s" not in s.ldap_user_filter:
        errors["ldap_user_filter"] = "missing_user_placeholder"
    if not str(s.graph_folder).strip():
        errors["graph_folder"] = "required"
    if s.graph_enabled and not (s.graph_tenant_id and s.graph_client_id and s.graph_group_id
                                and s.graph_client_secret_enc):
        errors["graph_enabled"] = "graph_incomplete"
    if s.oidc_enabled and not (s.graph_tenant_id and s.graph_client_id and s.graph_client_secret_enc and s.base_url):
        errors["oidc_enabled"] = "oidc_incomplete"  # app registration (Outlook tab) and public URL are needed
    if errors:
        return err("validation", fields=errors)
    s.save()
    if change := audit.diff(before, _settings_snapshot(s)):
        audit.log(request.user, "update", "settings", 1, "settings", change)
    return JsonResponse(ser_settings(s))


@needs(ADMIN)
def carddav_password(request):
    s = Settings.get()
    pw = secrets.token_urlsafe(18)
    s.carddav_password_hash = make_password(pw)
    s.save()
    audit.log(request.user, "update", "settings", 1, "settings", {"carddav_password_hash": ["***", "***"]})
    return JsonResponse({"password": pw})  # shown once


@needs(ADMIN)
def ldap_test(request):
    import ldap
    from .auth import ldap_settings, role_of
    s, b = Settings.get(), request.json
    conf = ldap_settings(s)
    out = {"bind": False, "user": None}
    try:
        conn = ldap.initialize(conf.SERVER_URI)
        for k, v in conf.CONNECTION_OPTIONS.items():
            conn.set_option(k, v)
        if conf.START_TLS:
            conn.start_tls_s()
        conn.simple_bind_s(conf.BIND_DN, conf.BIND_PASSWORD)
        out["bind"] = True
        if b.get("username"):
            res = conf.USER_SEARCH.execute(conn, {"user": b["username"]})
            if res:
                dn, attrs = res[0]
                groups = attrs.get("memberOf", attrs.get("memberof", []))
                # same rule as sign-in and the user import, nested groups included
                out["user"] = {"dn": dn, "groups": groups, "role": role_of(conn, s, dn, groups)}
    except ldap.LDAPError as e:
        out["error"] = str(e.args[0].get("desc", e) if e.args and isinstance(e.args[0], dict) else e)
    return JsonResponse(out)


@needs(ADMIN)
def graph_sync(request):
    if not Settings.objects.filter(pk=1, graph_enabled=True).update(graph_sync_requested=timezone.now()):
        return err("graph_disabled", 409)
    audit.log(request.user, "sync", "settings", 1, "outlook")
    return JsonResponse(ser_settings(Settings.get()))


@needs(ADMIN)
def graph_test(request):
    return JsonResponse(graph.test(Settings.get()))


@needs(ADMIN)
def relay_token(request):
    """New push token for the CardDAV relay. Only its SHA-256 is shown: that is what the relay host needs."""
    s = Settings.get()
    s.carddav_relay_token = secrets.token_urlsafe(32)
    s.save()
    audit.log(request.user, "update", "settings", 1, "settings", {"carddav_relay_token": ["***", "***"]})
    return JsonResponse(ser_settings(s))


@needs(ADMIN)
def relay_test(request):
    return JsonResponse(relaypush.test(Settings.get()))


@needs(ADMIN)
def relay_sync(request):
    if not Settings.objects.filter(pk=1, carddav_relay_enabled=True).update(carddav_relay_requested=timezone.now()):
        return err("relay_disabled", 409)
    audit.log(request.user, "sync", "settings", 1, "carddav_relay")
    return JsonResponse(ser_settings(Settings.get()))


@needs(ADMIN)
def ldap_import_users(request):
    return JsonResponse(ldapusers.run(request.user))


@needs(ADMIN)
def ad_dry_run(request):
    return JsonResponse(adsync.dry_run(Settings.get()))


@needs(ADMIN)
def ad_sync(request):
    if not Settings.objects.filter(pk=1, ad_enabled=True).update(ad_sync_requested=timezone.now()):
        return err("ad_disabled", 409)
    audit.log(request.user, "sync", "settings", 1, "ad")
    return JsonResponse(ser_settings(Settings.get()))


# ---------------------------------------------------------------- admin: exports

EXPORT_ATTRS = ["name", "enabled", "format", "path", "schedule", "kinds", "filter_values", "columns", "options",
                "max_shrink_percent"]


def ser_export(p):
    return {"id": p.id, **{a: getattr(p, a) for a in EXPORT_ATTRS}, "filter_field": p.filter_field_id,
            "effective_options": p.effective_options(),
            "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None, "last_status": p.last_status,
            "last_message": p.last_message, "last_rows": p.last_rows}


def _export_snapshot(p):
    return {**{a: getattr(p, a) for a in EXPORT_ATTRS}, "filter_field": p.filter_field_id}


def _export_from_body(p, b):
    for a in EXPORT_ATTRS:
        if a in b:
            setattr(p, a, b[a])
    if "filter_field" in b:
        p.filter_field = FieldDef.objects.filter(pk=b["filter_field"]).first() if b["filter_field"] else None
    return exports.validate_profile(p)


@needs(ADMIN)
def exports_list(request):
    return JsonResponse({"exports": [ser_export(p) for p in ExportProfile.objects.order_by("name")],
                         "sources": exports.available_sources(), "export_root": exports.EXPORT_ROOT})


@needs(ADMIN)
def export_create(request):
    p = ExportProfile(name="", path="")
    if errors := _export_from_body(p, request.json):
        return err("validation", fields=errors)
    p.save()
    audit.log(request.user, "create", "export", p.id, p.name, audit.diff({}, _export_snapshot(p)))
    return JsonResponse(ser_export(p), status=201)


@needs(ADMIN)
def export_update(request, pk):
    p = ExportProfile.objects.filter(pk=pk).first()
    if not p:
        return err("not_found", 404)
    before = _export_snapshot(p)
    if errors := _export_from_body(p, request.json):
        return err("validation", fields=errors)
    p.save()
    if change := audit.diff(before, _export_snapshot(p)):
        audit.log(request.user, "update", "export", p.id, p.name, change)
    return JsonResponse(ser_export(p))


@needs(ADMIN)
def export_delete(request, pk):
    p = ExportProfile.objects.filter(pk=pk).first()
    if not p:
        return err("not_found", 404)
    audit.log(request.user, "delete", "export", p.id, p.name, audit.diff(_export_snapshot(p), {}))
    p.delete()
    return JsonResponse({"ok": True})


@needs(ADMIN)
def export_preview(request):
    """Preview an unsaved profile from the editor."""
    p = ExportProfile(name="preview", path=exports.EXPORT_ROOT + "/preview")
    for a in EXPORT_ATTRS:
        if a in request.json and a not in ("name", "path"):
            setattr(p, a, request.json[a])
    if request.json.get("filter_field"):
        p.filter_field = FieldDef.objects.filter(pk=request.json["filter_field"]).first()
    errors = exports.validate_profile(p, check_path=False)
    if errors:
        return err("validation", fields=errors)
    header, rows = exports.build_rows(p)
    return JsonResponse({"header": header, "rows": rows[:20], "total": len(rows)})


@needs(ADMIN)
def export_run(request, pk):
    p = ExportProfile.objects.filter(pk=pk).first()
    if not p:
        return err("not_found", 404)
    exports.run(p, force=bool(request.json.get("force")), user=request.user)
    return JsonResponse(ser_export(p))


# ---------------------------------------------------------------- admin: audit & import

@needs(ADMIN)
def audit_list(request):
    qs = AuditEntry.objects.all()
    if t := request.GET.get("target_type"):
        qs = qs.filter(target_type=t)
    if q := request.GET.get("q"):
        qs = qs.filter(target_label__icontains=q) | qs.filter(username__icontains=q)
    if before := request.GET.get("before"):
        qs = qs.filter(id__lt=before)
    entries = list(qs[:100])
    kinds = record_kinds(entries)
    return JsonResponse({"entries": [ser_audit(e, ADMIN, kinds) for e in entries],
                         "more": len(entries) == 100})


@needs(ADMIN)
def import_preview(request):
    f = request.FILES.get("file")
    if not f:
        return err("validation", fields={"file": "required"})
    fields = list(FieldDef.objects.all())
    try:
        result = importer.preview(f.read(), fields)
    except importer.ImportError_ as e:
        return err("import_failed", detail=str(e))
    return JsonResponse({**result, "fields": [{"key": x.key, "label": {"de": x.label_de, "en": x.label_en},
                                               "applies_to": x.applies_to} for x in fields if not x.archived]})


@needs(ADMIN)
def import_csv(request):
    f = request.FILES.get("file")
    if not f:
        return err("validation", fields={"file": "required"})
    dry = request.POST.get("dry_run", "1") == "1"
    try:
        mapping = json.loads(request.POST.get("mapping") or "null")
    except ValueError:
        return err("invalid_json")
    try:
        result = importer.import_csv(f.read(), mapping=mapping, user=request.user, dry_run=dry)
    except importer.ImportError_ as e:
        return err("import_failed", detail=str(e))
    return JsonResponse(result)
