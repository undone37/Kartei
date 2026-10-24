"""API for other systems (phone system, intranet, CRM sync): `Authorization: Bearer <token>`, no session.

Contacts look like they do to Read Only users. Every token reads; tokens with scope "write" also create, update and
delete contacts like a maintainer, but only on fields Read Only users see. Changes are audited as "api:<token name>".
Tokens are managed by admins (/api/admin/tokens) and never grant anything else: the session API ignores them.
"""
import json
import secrets
from datetime import timedelta
from functools import wraps

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from . import audit, reviews
from .api import (ADMIN, MAINT, READ, _add_new_options, _apply, delete_tree, err, needs, records_qs, ser_record,
                  snapshot, visible_fields)
from .net import client_ip
from .models import ApiToken, FieldDef, Kind, Record, Settings


def token_auth(*allowed):
    """Bearer auth for the given methods; anything but GET needs a write token and a JSON object body (if any)."""
    def deco(fn):
        @csrf_exempt  # no cookies are looked at
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in allowed:
                return err("method_not_allowed", 405)
            # ponytail: per-process cache counter like login and CardDAV; use a shared cache if workers multiply
            key = f"api-fail:{client_ip(request)}"
            if cache.get(key, 0) >= 20:
                return err("too_many_attempts", 429)
            header = request.META.get("HTTP_AUTHORIZATION", "")
            token = header[7:].strip() if header.startswith("Bearer ") else ""
            t = ApiToken.objects.filter(token_hash=ApiToken.digest(token)).first() if token else None
            if t is None:
                cache.set(key, cache.get(key, 0) + 1, 15 * 60)
                resp = err("unauthenticated", 401)
                resp["WWW-Authenticate"] = 'Bearer realm="Kartei"'
                return resp
            now = timezone.now()
            if not t.last_used_at or t.last_used_at < now - timedelta(minutes=1):  # one write per minute at most
                ApiToken.objects.filter(pk=t.pk).update(last_used_at=now)
            request.token, request.json = t, {}
            if request.method != "GET":
                if t.scope != "write":
                    return err("forbidden", 403)
                if request.body:
                    try:
                        request.json = json.loads(request.body)
                    except ValueError:
                        return err("invalid_json")
                    if not isinstance(request.json, dict):
                        return err("invalid_json")
            return fn(request, *args, **kwargs)
        return wrapper
    return deco


def ser_contact(r, fields):
    d = ser_record(r, fields)
    return {k: d[k] for k in ("uid", "kind", "legacy_id", "first_name", "last_name", "name", "company")} | {
        "company_name": r.company.name if r.company_id and r.company else None,
        "display_name": r.display_name, "data": d["data"], "version": r.version, "updated_at": d["updated_at"]}


def _contact_response(r, status=200):
    resp = JsonResponse(ser_contact(records_qs().get(pk=r.pk), visible_fields(READ)), status=status)
    resp["ETag"] = f'"{r.version}"'
    return resp


@token_auth("GET", "POST")
def contacts(request):
    """All live contacts, or with ?updated_since=<cursor> only those changed since (plus deleted uids). POST creates."""
    if request.method == "POST":
        return create(request)
    now, fields = timezone.now(), visible_fields(READ)
    out = {"cursor": now.isoformat()}
    if raw := request.GET.get("updated_since"):
        since = parse_datetime(raw.replace(" ", "+"))  # an unencoded "+01:00" arrives as " 01:00"
        if since is None:
            return err("invalid_updated_since")
        if timezone.is_naive(since):
            since = timezone.make_aware(since)
        s = Settings.get()
        if not (s.trash_days and since < now - timedelta(days=s.trash_days)):  # else purged ones are unknown
            # same 5 s overlap as /api/changes; persons also change when their company is renamed
            cut = since - timedelta(seconds=5)
            changed = records_qs().filter(Q(updated_at__gte=cut) | Q(company__updated_at__gte=cut))
            return JsonResponse({**out, "contacts": [ser_contact(r, fields) for r in changed if not r.deleted_at],
                                 "deleted": [str(r.uid) for r in changed if r.deleted_at]})
    live = records_qs().filter(deleted_at__isnull=True)
    return JsonResponse({**out, "full": True, "contacts": [ser_contact(r, fields) for r in live]})


@token_auth("GET", "PATCH", "DELETE")
def contact(request, uid):
    if request.method == "PATCH":
        return update(request, uid)
    if request.method == "DELETE":
        return delete(request, uid)
    r = records_qs().filter(uid=uid, deleted_at__isnull=True).first()
    if not r:
        return err("not_found", 404)
    return _contact_response(r)


# ---------------------------------------------------------------- writing (scope "write")

def _actor(request):
    return f"api:{request.token.name}"


def _write_fields():
    """A write token edits like a maintainer, but only fields Read Only users see; others are unknown to it."""
    return [f for f in FieldDef.objects.all() if f.visible(READ)]


def create(request):
    body = request.json
    if body.get("kind") not in Kind.values:
        return err("validation", fields={"kind": "invalid"})
    fields, actor = _write_fields(), _actor(request)
    r = Record(kind=body["kind"])
    if errors := _apply(MAINT, r, body, fields):
        return err("validation", fields=errors)
    r.save()
    audit.log(None, "create", "record", r.uid, r.display_name, audit.diff({}, snapshot(r)), actor)
    _add_new_options(None, fields, r, actor)
    return _contact_response(r, 201)


def _expected_version(request):
    """`version` from the body, else an If-Match: "<version>" header. Returns (version or None, error)."""
    if "version" in request.json:
        v = request.json["version"]
    elif m := request.META.get("HTTP_IF_MATCH", "").strip():
        v = m.removeprefix("W/").strip('"')
    else:
        return None, None
    try:
        return int(v), None
    except (TypeError, ValueError):
        return None, err("validation", fields={"version": "invalid"})


def update(request, uid):
    body = request.json
    version, error = _expected_version(request)
    if error:
        return error
    fields, actor = _write_fields(), _actor(request)
    with transaction.atomic():
        r = Record.objects.select_for_update().filter(uid=uid, deleted_at__isnull=True).first()
        if not r:
            return err("not_found", 404)
        if version is not None and version != r.version:
            return err("version_conflict", 409, contact=ser_contact(records_qs().get(pk=r.pk), visible_fields(READ)))
        if "kind" in body and body["kind"] != r.kind:
            return err("validation", fields={"kind": "read_only"})
        before = snapshot(r)
        if errors := _apply(MAINT, r, body, fields):
            return err("validation", fields=errors)
        if change := audit.diff(before, snapshot(r)):
            r.version += 1
            r.updated_by = None
            r.save()
            audit.log(None, "update", "record", r.uid, r.display_name, change, actor)
            _add_new_options(None, fields, r, actor)
            reviews.reassign(r)  # open reviews follow a changed responsible
    return _contact_response(r)


def delete(request, uid):
    """To the recycle bin like in the UI; ?with_persons=1 takes a company's persons along."""
    with transaction.atomic():
        r = Record.objects.select_for_update().filter(uid=uid, deleted_at__isnull=True).first()
        if not r:
            return err("not_found", 404)
        gone = delete_tree(None, r, request.GET.get("with_persons") == "1", _actor(request))
    return JsonResponse({"ok": True, "deleted": gone})


# ---------------------------------------------------------------- admin

def ser_token(t):
    return {"id": t.id, "name": t.name, "scope": t.scope, "created_at": t.created_at.isoformat(),
            "created_by": t.created_by.username if t.created_by else "",
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None}


@needs(ADMIN)
def tokens(request):
    if request.method == "POST":
        name = str(request.json.get("name") or "").strip()[:100]
        scope = request.json.get("scope") or "read"
        if not name:
            return err("validation", fields={"name": "required"})
        if scope not in ApiToken.SCOPES:
            return err("validation", fields={"scope": "invalid"})
        token = "kt_" + secrets.token_urlsafe(32)
        t = ApiToken.objects.create(name=name, scope=scope, token_hash=ApiToken.digest(token), created_by=request.user)
        audit.log(request.user, "create", "token", t.id, t.name, {"name": [None, t.name], "scope": [None, t.scope]})
        return JsonResponse({**ser_token(t), "token": token}, status=201)  # shown once
    return JsonResponse({"tokens": [ser_token(t) for t in ApiToken.objects.select_related("created_by").order_by("name")]})


@needs(ADMIN)
def token_delete(request, pk):
    t = ApiToken.objects.filter(pk=pk).first()
    if not t:
        return err("not_found", 404)
    audit.log(request.user, "delete", "token", t.id, t.name, {"name": [t.name, None], "scope": [t.scope, None]})
    t.delete()
    return JsonResponse({"ok": True})
