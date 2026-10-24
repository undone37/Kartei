"""Write the contacts as AD contact objects into one OU.

For phone systems and address books that read contacts from AD. Kartei owns only objects carrying
adminDescription "kartei:<uid>"; everything else in the OU is left alone. Runs in the exporter tick.
"""
import re
import time

import ldap
from django.utils import timezone
from ldap.dn import escape_dn_chars

from . import exports
from .ldapusers import connect, error_text, first, search
from .msg import msg
from .models import FieldDef, Record, Settings, ref_names

MARK = "kartei:"
RESERVED = {"cn", "name", "displayname", "objectclass", "admindescription", "distinguishedname"}
ATTR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
CN_MAX = 64  # AD rangeUpper of cn
SAMPLE = 20


class SyncError(Exception):
    pass


def validate(s):
    """Settings errors for the ad_* attributes ({key: code})."""
    errors = {}
    if s.ad_kinds not in ("person", "company", "both"):
        errors["ad_kinds"] = "invalid"
    if not isinstance(s.ad_max_shrink_percent, int) or not 0 <= s.ad_max_shrink_percent <= 100:
        errors["ad_max_shrink_percent"] = "invalid_number"
    seen = set()
    if not isinstance(s.ad_columns, list):
        errors["ad_columns"] = "invalid"
    else:
        for c in s.ad_columns:
            attr = str(c.get("attr", "")).strip() if isinstance(c, dict) else ""
            if not ATTR_RE.match(attr) or attr.lower() in RESERVED or attr.lower() in seen:
                errors["ad_columns"] = f"invalid_attr:{attr}"
                break
            seen.add(attr.lower())
            for side in ("person", "company"):
                kind, _, arg = (c.get(side) or "").partition(":")
                if c.get(side) and not ((kind == "core" and arg in exports.CORE) or (kind == "calc" and arg in exports.CALC)
                                        or kind in ("field", "const")):
                    errors["ad_columns"] = f"invalid_source:{c[side]}"
    if s.ad_enabled and not (s.ldap_uri and s.ad_ou.strip()):
        errors["ad_enabled"] = "ad_incomplete"
    return errors


def _value(r, src, fields, names):
    v = exports._typed(exports.resolve(r, src, fields), src, fields, names)
    if isinstance(v, list):
        v = ", ".join(map(str, v))
    v = "" if v is None else str(v).strip()
    return [v.encode()] if v else []


def wanted(s):
    """{uid: (display name, {attr: [bytes]})} for the configured records."""
    fields = {f.key: f for f in FieldDef.objects.all()}
    names = ref_names()
    qs = Record.objects.filter(deleted_at__isnull=True).select_related("company").defer("image")
    if s.ad_kinds != "both":
        qs = qs.filter(kind=s.ad_kinds)
    out = {}
    for r in qs:
        name = " ".join(r.display_name.split()) or "?"
        attrs = {c["attr"]: _value(r, c.get(r.kind) or "", fields, names) for c in s.ad_columns}
        out[str(r.uid)] = (name, {**attrs, "displayName": [name.encode()]})
    return out


def _unique_cn(name, taken):
    n = 1
    while True:
        suffix = f" ({n})" if n > 1 else ""
        cn = name[:CN_MAX - len(suffix)].rstrip() + suffix
        if cn.lower() not in taken:
            taken.add(cn.lower())
            return cn
        n += 1


def _fits(cn, name):
    """cn is name, or name (shortened) with a " (n)" suffix from an earlier collision: no rename needed."""
    suffix = re.fullmatch(r".*?( \(\d+\))?", cn).group(1) or ""
    return cn == name[:CN_MAX].rstrip() or bool(suffix) and cn == name[:CN_MAX - len(suffix)].rstrip() + suffix


def plan(s, existing, want):
    """existing: [(dn, attrs)] one level below the OU. -> {"add", "rename", "modify", "delete", "unchanged"}."""
    ours, taken, delete = {}, set(), []
    for dn, a in existing:
        mark = first(a, "adminDescription")
        uid = mark[len(MARK):] if mark.startswith(MARK) else None
        if uid and uid in want and uid not in ours:
            ours[uid] = (dn, a)
            taken.add(first(a, "cn").lower())  # old names of renamed objects stay taken: no swap collisions
        elif uid:  # record gone (or a duplicate)
            delete.append((dn, first(a, "displayName") or first(a, "cn")))
        else:
            taken.add(first(a, "cn").lower())
    out = {"add": [], "rename": [], "modify": [], "delete": delete, "unchanged": 0}
    for uid, (name, attrs) in sorted(want.items(), key=lambda x: x[1][0].lower()):
        if uid not in ours:
            cn = _unique_cn(name, taken)
            out["add"].append((f"CN={escape_dn_chars(cn)},{s.ad_ou}", name,
                               [("objectClass", [b"contact"]), ("cn", [cn.encode()]),
                                ("adminDescription", [(MARK + uid).encode()])] + [(k, v) for k, v in attrs.items() if v]))
            continue
        dn, a = ours[uid]
        if renamed := not _fits(first(a, "cn"), name):
            cn = _unique_cn(name, taken)
            out["rename"].append((dn, name, f"CN={escape_dn_chars(cn)}"))
            dn = f"CN={escape_dn_chars(cn)},{s.ad_ou}"
        have = {k.lower(): v for k, v in a.items()}
        mods = [(ldap.MOD_REPLACE, k, v) if v else (ldap.MOD_DELETE, k, None)
                for k, v in attrs.items() if have.get(k.lower(), []) != v]
        if mods:
            out["modify"].append((dn, name, mods))
        elif not renamed:
            out["unchanged"] += 1
    return out


def guard(s, p, have):
    """have: number of Kartei-marked objects in the OU before the run."""
    if have and len(p["delete"]) > have * s.ad_max_shrink_percent / 100:
        raise SyncError(msg("ad_too_many_deletes", n=len(p["delete"]), total=have, limit=s.ad_max_shrink_percent))


def _load(s):
    want = wanted(s)
    if not want:  # never wipe the phone book because of an empty database
        raise SyncError(msg("ad_no_records"))
    try:
        conn = connect(s, s.ad_bind_dn, s.ad_bind_password)
        attrs = ["cn", "adminDescription"] + sorted({k for _, a in want.values() for k in a})
        existing = search(conn, s.ad_ou, "(objectClass=*)", attrs, scope=ldap.SCOPE_ONELEVEL)
    except ldap.LDAPError as e:
        raise SyncError(error_text(e))
    have = sum(1 for _, a in existing if first(a, "adminDescription").startswith(MARK))
    return conn, plan(s, existing, want), have


def summary(p):
    return {"created": len(p["add"]), "updated": len(p["modify"]), "renamed": len(p["rename"]),
            "deleted": len(p["delete"]), "unchanged": p["unchanged"]}


def dry_run(s):
    """What a sync would do, without writing. The guard result is reported, not raised."""
    try:
        _, p, have = _load(s)
    except SyncError as e:
        return {"error": str(e)}
    out = summary(p) | {
        "add": [{"name": n, "dn": dn} for dn, n, _ in p["add"][:SAMPLE]],
        "rename": [{"name": n, "dn": dn, "to": to} for dn, n, to in p["rename"][:SAMPLE]],
        "modify": [{"name": n, "dn": dn, "attrs": [m[1] for m in mods]} for dn, n, mods in p["modify"][:SAMPLE]],
        "delete": [{"name": n, "dn": dn} for dn, n in p["delete"][:SAMPLE]]}
    try:
        guard(s, p, have)
    except SyncError as e:
        out["blocked"] = str(e)
    return out


def sync(s):
    conn, p, have = _load(s)
    guard(s, p, have)
    failed = []

    def do(label, fn, *args):
        try:
            fn(*args)
            return True
        except ldap.LDAPError as e:
            failed.append(f"{label}: {error_text(e)}")

    # deletes first so their names are free; a failed rename skips the modify of that object
    deleted = sum(1 for dn, n in p["delete"] if do(n, conn.delete_s, dn))
    bad = {dn for dn, n, to in p["rename"] if not do(n, conn.rename_s, dn, to, None, 1)}
    renamed = len(p["rename"]) - len(bad)
    created = sum(1 for dn, n, mods in p["add"] if do(n, conn.add_s, dn, mods))
    old = {f"{to},{s.ad_ou}": dn for dn, _, to in p["rename"]}
    updated = sum(1 for dn, n, mods in p["modify"] if old.get(dn) not in bad and do(n, conn.modify_s, dn, mods))
    return {"created": created, "updated": updated, "renamed": renamed, "deleted": deleted,
            "unchanged": p["unchanged"], "failed": failed[:20]}


def run():
    """Exporter tick. Returns the status dict, or None when disabled."""
    Settings.objects.filter(pk=1).update(ad_sync_requested=None)
    s = Settings.get()
    if not s.ad_enabled:
        return None
    started = time.monotonic()
    try:
        status = sync(s)
    except SyncError as e:
        status = {"error": str(e)}
    status |= {"at": timezone.now().isoformat(), "seconds": round(time.monotonic() - started, 1)}
    Settings.objects.filter(pk=1).update(ad_status=status)  # not save(): don't clobber concurrent admin edits
    return status
