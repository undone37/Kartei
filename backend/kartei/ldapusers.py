"""Import the members of the three AD role groups as Kartei users, so they can be assigned before their first login.

Nested groups are resolved by AD itself (LDAP_MATCHING_RULE_IN_CHAIN). Local users are never touched; LDAP users that
left all role groups are deactivated, not deleted, so their assignments still display.
"""
import re
import time
from datetime import datetime, timedelta

import ldap
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from ldap.controls import SimplePagedResultsControl
from ldap.filter import escape_filter_chars

from . import audit
from .auth import ldap_settings, role_groups
from .msg import msg
from .models import Profile, Settings

IN_CHAIN = "1.2.840.113556.1.4.1941"
ENABLED = "(!(userAccountControl:1.2.840.113556.1.4.803:=2))"  # disabled accounts can't sign in either


class LdapError(Exception):
    pass


def error_text(e):
    """Readable text of a python-ldap exception (shown as-is in the UI)."""
    d = e.args[0] if e.args and isinstance(e.args[0], dict) else {}
    return " – ".join(x for x in (d.get("desc"), d.get("info")) if x) or str(e)


def connect(s, bind_dn=None, password=None):
    """Bound connection with the TLS/CA options of the login backend."""
    conf = ldap_settings(s)
    conn = ldap.initialize(conf.SERVER_URI)
    for k, v in conf.CONNECTION_OPTIONS.items():
        conn.set_option(k, v)
    if conf.START_TLS:
        conn.start_tls_s()
    conn.simple_bind_s(bind_dn or conf.BIND_DN, password if bind_dn else conf.BIND_PASSWORD)
    return conn


def search(conn, base, flt, attrs, scope=ldap.SCOPE_SUBTREE):
    """Paged search (AD returns at most 1000 entries per page). -> [(dn, attrs)] without referrals."""
    ctrl = SimplePagedResultsControl(True, size=500, cookie="")
    out = []
    while True:
        _, data, _, sctrls = conn.result3(conn.search_ext(base, scope, flt, attrs, serverctrls=[ctrl]))
        out += [(dn, a) for dn, a in data if dn]
        ctrl.cookie = next((c.cookie for c in sctrls if c.controlType == SimplePagedResultsControl.controlType), b"")
        if not ctrl.cookie:
            return out


def first(attrs, name):
    """First value of an attribute as str (attribute names are case-insensitive in LDAP)."""
    for k, v in attrs.items():
        if k.lower() == name.lower() and v:
            return v[0].decode() if isinstance(v[0], bytes) else v[0]
    return ""


def username_attr(s):
    m = re.search(r"\(\s*([\w-]+)\s*=\s*%\(user\)s\s*\)", s.ldap_user_filter or "")
    return m.group(1) if m else "sAMAccountName"


def members(conn, s):
    """{username: (role, attrs)} of all enabled users in the role groups; the highest role wins."""
    attr = username_attr(s)
    out = {}
    for role, group in role_groups(s):
        flt = f"(&(objectCategory=person)(objectClass=user){ENABLED}(memberOf:{IN_CHAIN}:={escape_filter_chars(group)}))"
        for _, a in search(conn, s.ldap_user_base, flt, [attr, "givenName", "sn", "mail"]):
            if name := first(a, attr).lower():  # django-auth-ldap stores usernames lower-case too
                out.setdefault(name, (role, a))
    return out


def _snapshot(u, p):
    return {"username": u.username, "first_name": u.first_name, "last_name": u.last_name, "email": u.email,
            "role": p.role if p else None, "source": p.source if p else None, "is_active": u.is_active}


@transaction.atomic
def apply(found, actor=None):
    """Create/update/deactivate users from members(). -> counts."""
    counts = {"created": 0, "updated": 0, "deactivated": 0, "skipped_local": 0}
    users = {u.username.lower(): u for u in User.objects.select_related("profile")}
    for name, (role, a) in found.items():
        u = users.get(name)
        p = getattr(u, "profile", None) if u else None
        if u and (not p or p.source != "ldap"):  # local (or superuser without profile): never touch
            counts["skipped_local"] += 1
            continue
        before = _snapshot(u, p) if u else {}
        if not u:
            u = User(username=name)
            u.set_unusable_password()  # signs in via LDAP only
        u.first_name, u.last_name, u.email = first(a, "givenName")[:150], first(a, "sn")[:150], first(a, "mail")[:254]
        u.is_active = True
        if not before or before != _snapshot(u, p) or p.role != role:
            u.save()
            p, _ = Profile.objects.update_or_create(user=u, defaults={"role": role, "source": "ldap"})
            counts["updated" if before else "created"] += 1
            audit.log(actor, "update" if before else "create", "user", u.id, u.username,
                      audit.diff(before, _snapshot(u, p)))
    for name, u in users.items():
        p = getattr(u, "profile", None)
        if p and p.source == "ldap" and u.is_active and name not in found:
            u.is_active = False
            u.save(update_fields=["is_active"])
            counts["deactivated"] += 1
            audit.log(actor, "update", "user", u.id, u.username, {"is_active": [True, False]})
    return counts


def run(actor=None):
    """Import now and store the status on Settings. Never raises."""
    s = Settings.get()
    started = time.monotonic()
    try:
        if not s.ldap_uri or not s.ldap_user_base or not role_groups(s):
            raise LdapError(msg("ldap_users_not_configured"))
        try:
            found = members(connect(s), s)
        except ldap.LDAPError as e:
            raise LdapError(error_text(e))
        if not found:  # a wrong search base must not deactivate everybody
            raise LdapError(msg("ldap_users_none"))
        status = apply(found, actor)
    except LdapError as e:
        status = {"error": str(e)}
    status |= {"at": timezone.now().isoformat(), "seconds": round(time.monotonic() - started, 1)}
    Settings.objects.filter(pk=1).update(ldap_users_status=status)
    return status


def due(s, hours=24):
    """Exporter tick: once a day when LDAP is set up."""
    at = (s.ldap_users_status or {}).get("at")
    return bool(s.ldap_uri and role_groups(s)) and (
        not at or timezone.now() - datetime.fromisoformat(at) >= timedelta(hours=hours))
