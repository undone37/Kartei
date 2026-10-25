"""SCIM 2.0 (RFC 7643/7644) for the identity provider: it creates, updates and deactivates users and pushes groups
before anyone signs in. `Authorization: Bearer <SCIM token>` (Settings → Single sign-on, shown once).

Only users created here (source "scim") are visible and changeable through SCIM; local and LDAP users are never
touched. A SCIM user is active when the provider says so and one of its groups is mapped to a role (highest role
wins). Users are never deleted, only deactivated, so the history keeps its names. Every change is audited as "SCIM".
"""
import hmac
import json
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import audit
from .api import _admins_left
from .models import ApiToken, Profile, Role, ScimGroup, Settings
from .net import client_ip

USER = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
CTYPE = "application/scim+json"


class ScimError(Exception):
    def __init__(self, status, detail, scim_type=None):
        super().__init__(detail)
        self.status, self.detail, self.scim_type = status, detail, scim_type


def out(data, status=200):
    return JsonResponse(data, status=status, content_type=CTYPE)


def error(status, detail, scim_type=None):
    return out({"schemas": [ERROR], "status": str(status), "detail": detail} | ({"scimType": scim_type} if scim_type else {}),
               status)


# ---------------------------------------------------------------- roles

def role_of(u, s):
    """Highest role whose mapped group contains u, or None."""
    ids = {str(i) for i in u.scim_groups.values_list("id", flat=True)}
    return next((role for role, gid in ((Role.ADMIN, s.scim_group_admin), (Role.MAINTAINER, s.scim_group_maintainer),
                                        (Role.READ, s.scim_group_read)) if gid and gid in ids), None)


def _snap(u):
    p = u.profile
    return {"username": u.username, "first_name": u.first_name, "last_name": u.last_name, "email": u.email,
            "external_id": p.external_id, "scim_active": p.scim_active, "role": p.role, "is_active": u.is_active}


def sync(u, s):
    """is_active and role from the provider's "active" and the groups. The last admin is never taken away."""
    p = u.profile
    role = role_of(u, s)
    active = p.scim_active and role is not None
    was_admin = u.is_active and p.role == Role.ADMIN
    if was_admin and (not active or role != Role.ADMIN) and not _admins_left(u):
        return
    if role:
        p.role = role
    u.is_active = active
    p.save(update_fields=["role"])
    u.save(update_fields=["is_active"])


def sync_all(s=None):
    s = s or Settings.get()
    for u in User.objects.filter(profile__source="scim").select_related("profile"):
        before = _snap(u)
        sync(u, s)
        if change := audit.diff(before, _snap(u)):
            audit.log(None, "update", "user", u.id, u.username, change, username="SCIM")


# ---------------------------------------------------------------- auth and dispatch

def scim(request, path):
    """/scim/v2/<path>: bearer auth, then one handler per resource."""
    key = f"scim-fail:{client_ip(request)}"
    if cache.get(key, 0) >= 20:
        return error(429, "Too many failed attempts")
    header = request.META.get("HTTP_AUTHORIZATION", "")
    token = header[7:].strip() if header.startswith("Bearer ") else ""
    expected = Settings.get().scim_token_hash
    if not (token and expected and hmac.compare_digest(ApiToken.digest(token), expected)):
        cache.set(key, cache.get(key, 0) + 1, 15 * 60)
        resp = error(401, "Invalid or missing bearer token")
        resp["WWW-Authenticate"] = 'Bearer realm="Kartei SCIM"'
        return resp
    # at most one write a minute; update(), so it can't overwrite settings saved in the meantime
    Settings.objects.filter(pk=1).exclude(scim_seen_at__gt=timezone.now() - timedelta(minutes=1)).update(scim_seen_at=timezone.now())
    parts = path.strip("/").split("/")
    try:
        body = json.loads(request.body) if request.body else {}
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return error(400, "Body is not a JSON object", "invalidSyntax")
    try:
        with transaction.atomic():
            if parts[0] in STATIC and len(parts) == 1 and request.method == "GET":
                return out(STATIC[parts[0]])
            if parts[0] in ("Users", "Groups") and len(parts) <= 2:
                kind = USERS if parts[0] == "Users" else GROUPS
                if len(parts) == 1:
                    if request.method == "GET":
                        return listing(request, kind)
                    if request.method == "POST":
                        return kind["write"](request, None, body, "POST")
                    return error(405, "Method not allowed")
                obj = kind["get"](parts[1])
                if request.method == "GET":
                    return out(kind["ser"](request, obj))
                if request.method in ("PUT", "PATCH", "DELETE"):
                    return kind["write"](request, obj, body, request.method)
                return error(405, "Method not allowed")
            return error(404, "Unknown endpoint")
    except ScimError as e:
        return error(e.status, e.detail, e.scim_type)


scim = csrf_exempt(scim)


def _filter(request, attrs):
    """`<attr> eq "<value>"` → (model field, value); attrs: {scim name (lower): field}."""
    f = request.GET.get("filter", "").strip()
    if not f:
        return None
    m = re.fullmatch(r'(\w+)\s+eq\s+"((?:[^"\\]|\\.)*)"', f, re.I)
    if not m or m.group(1).lower() not in attrs:
        raise ScimError(400, "Only `<attribute> eq \"value\"` on " + ", ".join(attrs.values()) + " is supported", "invalidFilter")
    return attrs[m.group(1).lower()], json.loads(f'"{m.group(2)}"')


def listing(request, kind):
    qs = kind["qs"]()
    if f := _filter(request, kind["filters"]):
        qs = qs.filter(**{f[0]: f[1]})
    try:
        start, count = max(int(request.GET.get("startIndex", 1)), 1), min(max(int(request.GET.get("count", 100)), 0), 200)
    except ValueError:
        raise ScimError(400, "startIndex and count must be numbers", "invalidValue")
    page = list(qs[start - 1:start - 1 + count])
    return out({"schemas": [LIST], "totalResults": qs.count(), "startIndex": start, "itemsPerPage": len(page),
                "Resources": [kind["ser"](request, o) for o in page]})


def _meta(request, kind, pk):
    return {"resourceType": kind, "location": request.build_absolute_uri(f"/scim/v2/{kind}s/{pk}")}


def _bool(v):
    return v.strip().lower() == "true" if isinstance(v, str) else bool(v)


# ---------------------------------------------------------------- users

def users_qs():
    return User.objects.filter(profile__source="scim").select_related("profile").order_by("id")


def get_user(pk):
    u = users_qs().filter(pk=pk).first() if pk.isdigit() else None
    if not u:
        raise ScimError(404, "User not found")
    return u


def ser_user(request, u):
    p = u.profile
    return {"schemas": [USER], "id": str(u.id), "externalId": p.external_id or None, "userName": u.username,
            "name": {"givenName": u.first_name, "familyName": u.last_name},
            "displayName": f"{u.first_name} {u.last_name}".strip() or u.username,
            "emails": [{"value": u.email, "type": "work", "primary": True}] if u.email else [],
            "active": p.scim_active,
            "groups": [{"value": str(g.id), "display": g.display_name} for g in u.scim_groups.all()],
            "meta": _meta(request, "User", u.id)}


def _user_attr(state, path, value, remove=False):
    """Apply one attribute (Entra/Okta style paths) to state; unknown attributes are ignored."""
    key = path.strip()
    if key.lower().startswith(USER.lower() + ":"):
        key = key[len(USER) + 1:]
    k = key.lower()
    if k == "name" and isinstance(value, dict):
        for sub, v in value.items():
            _user_attr(state, "name." + sub, v, remove)
    elif k == "emails":
        items = value if isinstance(value, list) else []
        pick = next((e for e in items if isinstance(e, dict) and e.get("primary")), items[0] if items else {})
        state["email"] = "" if remove else str(pick.get("value", "") if isinstance(pick, dict) else "")
    elif re.fullmatch(r"emails\[.*\]\.value", k):
        state["email"] = "" if remove else str(value or "")
    elif k in ("username", "externalid", "name.givenname", "name.familyname"):
        state[{"username": "userName", "externalid": "externalId", "name.givenname": "givenName",
               "name.familyname": "familyName"}[k]] = "" if remove else str(value or "")
    elif k == "active" and not remove:
        state["active"] = _bool(value)


def write_user(request, u, body, method):
    s = Settings.get()
    if method == "DELETE":  # never deleted: the history keeps the name
        state = None
    elif method == "PATCH":
        state = _user_state(u)
        for op in _ops(body):
            if op["path"]:
                _user_attr(state, op["path"], op["value"], op["op"] == "remove")
            elif isinstance(op["value"], dict):
                for k, v in op["value"].items():
                    _user_attr(state, k, v)
    else:  # POST, PUT: the whole resource
        state = {"userName": "", "externalId": "", "givenName": "", "familyName": "", "email": "", "active": True}
        for k, v in body.items():
            if k not in ("schemas", "id", "meta", "groups"):
                _user_attr(state, k, v)
    if state is not None:
        name = state["userName"].strip()
        if not name or len(name) > 150:
            raise ScimError(400, "userName is required (at most 150 characters)", "invalidValue")
        clash = User.objects.filter(username__iexact=name).exclude(pk=u.pk if u else None)
        if clash.exists():
            raise ScimError(409, "userName is taken", "uniqueness")
    before = _snap(u) if u else {}
    if u is None:
        u = User.objects.create_user(name)  # no password: sign-in only through single sign-on
        Profile.objects.update_or_create(user=u, defaults={"source": "scim", "role": Role.READ})
        u.refresh_from_db()
    p = u.profile
    if state is None:
        p.scim_active = False
    else:
        u.username, u.first_name, u.last_name = name, state["givenName"][:150], state["familyName"][:150]
        u.email, p.external_id, p.scim_active = state["email"][:254], state["externalId"][:255], state["active"]
        u.save()
    p.save()
    sync(u, s)
    if change := audit.diff(before, _snap(u)):
        audit.log(None, "create" if not before else "update", "user", u.id, u.username, change, username="SCIM")
    if method == "DELETE":
        return HttpResponse(status=204)
    return out(ser_user(request, u), 201 if method == "POST" else 200)


def _user_state(u):
    return {"userName": u.username, "externalId": u.profile.external_id, "givenName": u.first_name,
            "familyName": u.last_name, "email": u.email, "active": u.profile.scim_active}


def _ops(body):
    raw = body.get("Operations")
    if not isinstance(raw, list):
        raise ScimError(400, "Operations missing", "invalidSyntax")
    ops = []
    for op in raw:
        if not isinstance(op, dict) or str(op.get("op", "")).lower() not in ("add", "remove", "replace"):
            raise ScimError(400, "Unknown operation", "invalidSyntax")
        ops.append({"op": op["op"].lower(), "path": str(op.get("path") or ""), "value": op.get("value")})
    return ops


# ---------------------------------------------------------------- groups

def groups_qs():
    return ScimGroup.objects.prefetch_related("members").order_by("id")


def get_group(pk):
    g = groups_qs().filter(pk=pk).first() if pk.isdigit() else None
    if not g:
        raise ScimError(404, "Group not found")
    return g


def ser_group(request, g):
    d = {"schemas": [GROUP], "id": str(g.id), "displayName": g.display_name, "externalId": g.external_id or None,
         "meta": _meta(request, "Group", g.id)}
    if "members" not in request.GET.get("excludedAttributes", ""):
        d["members"] = [{"value": str(u.id), "display": u.username} for u in g.members.all()]
    return d


def _member_ids(value):
    items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    ids = [str(m.get("value", "")) for m in items if isinstance(m, dict)]
    return set(users_qs().filter(pk__in=[i for i in ids if i.isdigit()]).values_list("id", flat=True))


def write_group(request, g, body, method):
    s = Settings.get()
    before_members = set(g.members.values_list("id", flat=True)) if g else set()
    before = {"display_name": g.display_name, "members": sorted(before_members)} if g else {}
    if method == "DELETE":
        affected = before_members
        audit.log(None, "delete", "group", g.id, g.display_name, audit.diff(before, {}), username="SCIM")
        g.delete()
        for u in users_qs().filter(pk__in=affected):
            _resync(u, s)
        return HttpResponse(status=204)
    members = set(before_members)
    if method == "PATCH":
        name, ext = g.display_name, g.external_id
        for op in _ops(body):
            path, value = op["path"], op["value"]
            if not path and isinstance(value, dict):  # Entra: {"displayName": …} or {"members": […]}
                for k, v in value.items():
                    if k == "members":
                        members = _member_ids(v) if op["op"] == "replace" else members | _member_ids(v)
                    elif k == "displayName":
                        name = str(v or name)
                    elif k == "externalId":
                        ext = str(v or "")
            elif m := re.fullmatch(r'members\[value eq "([^"]*)"\]', path, re.I):
                if op["op"] == "remove":
                    members.discard(int(m.group(1)) if m.group(1).isdigit() else None)
            elif path.lower() == "members":
                if op["op"] == "add":
                    members |= _member_ids(value)
                elif op["op"] == "replace":
                    members = _member_ids(value)
                else:
                    members = members - _member_ids(value) if value else set()
            elif path.lower() == "displayname" and op["op"] != "remove":
                name = str(value or name)
            elif path.lower() == "externalid":
                ext = "" if op["op"] == "remove" else str(value or "")
    else:  # POST, PUT
        name, ext, members = str(body.get("displayName") or "").strip(), str(body.get("externalId") or ""), _member_ids(body.get("members"))
    if not name:
        raise ScimError(400, "displayName is required", "invalidValue")
    if g is None:
        g = ScimGroup.objects.create(display_name=name[:255], external_id=ext[:255])
    else:
        g.display_name, g.external_id = name[:255], ext[:255]
        g.save()
    g.members.set(members)
    if change := audit.diff(before, {"display_name": g.display_name, "members": sorted(members)}):
        audit.log(None, "create" if method == "POST" else "update", "group", g.id, g.display_name, change, username="SCIM")
    for u in users_qs().filter(pk__in=members ^ before_members):
        _resync(u, s)
    return out(ser_group(request, groups_qs().get(pk=g.pk)), 201 if method == "POST" else 200)


def _resync(u, s):
    before = _snap(u)
    sync(u, s)
    if change := audit.diff(before, _snap(u)):
        audit.log(None, "update", "user", u.id, u.username, change, username="SCIM")


USERS = {"qs": users_qs, "get": get_user, "ser": ser_user, "write": write_user,
         "filters": {"username": "username__iexact", "externalid": "profile__external_id"}}
GROUPS = {"qs": groups_qs, "get": get_group, "ser": ser_group, "write": write_group,
          "filters": {"displayname": "display_name__iexact", "externalid": "external_id"}}

STATIC = {
    "ServiceProviderConfig": {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200}, "changePassword": {"supported": False},
        "sort": {"supported": False}, "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token", "primary": True,
                                   "description": "Token from Kartei → Settings → Single sign-on"}]},
    "ResourceTypes": {"schemas": [LIST], "totalResults": 2, "Resources": [
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": "User", "name": "User",
         "endpoint": "/Users", "schema": USER},
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": "Group", "name": "Group",
         "endpoint": "/Groups", "schema": GROUP}]},
    "Schemas": {"schemas": [LIST], "totalResults": 2, "Resources": [
        {"id": USER, "name": "User", "attributes": [{"name": n, "type": "string"} for n in
                                                     ("userName", "externalId", "name", "emails", "active")]},
        {"id": GROUP, "name": "Group", "attributes": [{"name": n, "type": "string"} for n in
                                                       ("displayName", "externalId", "members")]}]},
}
