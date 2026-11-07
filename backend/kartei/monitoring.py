"""Health and status for monitoring systems (Checkmk, Zabbix, PRTG, Uptime Kuma).

/healthz   process alive (no database)                                open
/readyz    database reachable and migrated                            open, ok/fail only
/api/monitoring/status   checks + metrics as JSON (?format=prtg)      bearer token AND an allowed client address
"""
import hashlib
import hmac
import ipaddress
import secrets
import shutil
import time
from datetime import datetime, timedelta

from django.conf import settings as dj
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone

from .models import AuditEntry, ExportProfile, Profile, Proposal, QualitySnapshot, Record, Review, Settings, Webhook
from .net import client_ip

LEVEL = {"ok": 0, "warn": 1, "crit": 2}


# ---------------------------------------------------------------- open probes

def healthz(request):
    return JsonResponse({"status": "ok"})


def _pending_migrations():
    # ponytail: cached a minute per process; a deploy restarts the processes anyway
    pending = cache.get("monitoring:pending")
    if pending is None:
        executor = MigrationExecutor(connection)
        pending = len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
        cache.set("monitoring:pending", pending, 60)
    return pending


def readyz(request):
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        ok = _pending_migrations() == 0
    except Exception:
        ok = False
    return JsonResponse({"status": "ok" if ok else "fail"}, status=200 if ok else 503)


# ---------------------------------------------------------------- access

def new_token():
    """A fresh token; only its sha256 is stored."""
    token = "kmon_" + secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def allowed(ip, allowlist):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if addr in ipaddress.ip_network(str(entry).strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def valid_allowlist(entries):
    """The entries that are no IP address or network (for the settings form)."""
    bad = []
    for e in entries:
        try:
            ipaddress.ip_network(str(e).strip(), strict=False)
        except ValueError:
            bad.append(e)
    return bad


def status_view(request):
    """Token and address must both match; the answer doesn't say which one failed."""
    s = Settings.get()
    header = request.META.get("HTTP_AUTHORIZATION", "")
    token = header[7:].strip() if header.startswith("Bearer ") else ""
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not (token and s.monitoring_token_hash and hmac.compare_digest(digest, s.monitoring_token_hash)):
        resp = JsonResponse({"error": "unauthenticated"}, status=401)
        resp["WWW-Authenticate"] = 'Bearer realm="Kartei monitoring"'
        return resp
    if not allowed(client_ip(request), s.monitoring_allowlist):
        return JsonResponse({"error": "forbidden"}, status=403)
    data = collect(s)
    return JsonResponse(prtg(data) if request.GET.get("format") == "prtg" else data)


# ---------------------------------------------------------------- checks

def _age(at):
    """Seconds since an ISO timestamp or datetime; None if unknown."""
    if not at:
        return None
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at)
        except ValueError:
            return None
    return int((timezone.now() - at).total_seconds())


def _job(name, status, every_s):
    """A background job's last run: crit on an error, warn when it hasn't run for three intervals."""
    status = status or {}
    age = _age(status.get("at"))
    if status.get("error"):
        return {"name": name, "status": "crit", "detail": str(status["error"])[:300], "age_s": age}
    if age is None:
        return {"name": name, "status": "warn", "detail": "never run", "age_s": None}
    if age > 3 * every_s:
        return {"name": name, "status": "warn", "detail": "last run too long ago", "age_s": age}
    return {"name": name, "status": "ok", "detail": "", "age_s": age}


def checks(s):
    interval = max(s.export_interval_minutes, 1) * 60
    out = []
    try:
        pending = _pending_migrations()
        out.append({"name": "database", "status": "ok" if not pending else "crit",
                    "detail": f"{pending} migrations pending" if pending else "", "age_s": None})
    except Exception as e:
        out.append({"name": "database", "status": "crit", "detail": str(e)[:300], "age_s": None})
    beat = _age(s.exporter_seen_at)
    out.append({"name": "exporter", "age_s": beat,
                "status": "crit" if beat is None or beat > 3 * interval else "warn" if beat > 2 * interval else "ok",
                "detail": "no heartbeat" if beat is None else ""})
    for p in ExportProfile.objects.filter(enabled=True, schedule="auto"):
        age = _age(p.last_run_at)
        state = "crit" if p.last_status == "error" else "warn" if age is None or age > 3 * interval else "ok"
        out.append({"name": f"export:{p.name}", "status": state, "age_s": age,
                    "detail": p.last_message[:300] if state != "ok" else ""})
    if s.graph_enabled:
        out.append(_job("outlook", s.graph_status, interval))
    if s.ad_enabled:
        out.append(_job("active_directory", s.ad_status, interval))
    if s.carddav_relay_enabled:
        out.append(_job("carddav_relay", s.carddav_relay_status, interval))
    if s.ldap_uri and s.ldap_users_status:
        out.append(_job("ldap_users", s.ldap_users_status, 24 * 3600))
    for w in Webhook.objects.filter(enabled=True).exclude(last_status={}):
        if w.last_status.get("ok") is False:
            out.append({"name": f"webhook:{w.name}", "status": "warn", "age_s": _age(w.last_status.get("at")),
                        "detail": str(w.last_status.get("error") or w.last_status.get("code") or "")[:300]})
    if s.backup_enabled:
        st = s.backup_status or {}
        age = _age(st.get("at"))
        state = "crit" if st.get("error") or age is None or age > 50 * 3600 else "warn" if age > 26 * 3600 else "ok"
        out.append({"name": "backup", "status": state, "age_s": age,
                    "detail": st.get("error") or ("never run" if age is None else "last backup too old" if state != "ok" else "")})
    if (rt := s.restore_test_status or {}).get("error"):
        out.append({"name": "restore_test", "status": "warn", "age_s": _age(rt.get("at")), "detail": rt["error"][:300]})
    if s.syslog_enabled:
        st = s.syslog_status or {}
        failing = st.get("error") and (_age(st.get("error_at")) or 0) < 3600
        out.append({"name": "syslog", "status": "crit" if failing else "ok", "age_s": _age(st.get("at")),
                    "detail": st.get("error", "") if failing else ""})
    try:
        from .exports import EXPORT_ROOT
        du = shutil.disk_usage(EXPORT_ROOT)
        free = du.free / du.total * 100
        out.append({"name": "export_disk", "status": "crit" if free < 5 else "warn" if free < 10 else "ok",
                    "detail": f"{free:.0f}% free", "age_s": None})
    except OSError:
        pass  # no export directory (yet): nothing to watch
    return out


def metrics(s):
    now = timezone.now()
    kinds = dict(Record.objects.filter(deleted_at__isnull=True).values_list("kind").annotate(n=Count("id")))
    roles = dict(Profile.objects.filter(user__is_active=True).values_list("role").annotate(n=Count("id")))
    signins = AuditEntry.objects.filter(target_type="session")
    count = lambda action, hours: signins.filter(action=action, at__gte=now - timedelta(hours=hours)).count()
    st = s.syslog_status or {}
    return {
        "persons": kinds.get("person", 0), "companies": kinds.get("company", 0),
        "recycle_bin": Record.objects.filter(deleted_at__isnull=False).count(),
        "users_active": User.objects.filter(is_active=True).count(),
        **{f"users_{r}": n for r, n in roles.items()},
        "reviews_open": Review.objects.filter(done_at__isnull=True).count(),
        "proposals_pending": Proposal.objects.filter(status="pending").count(),
        "logins_1h": count("login", 1), "logins_24h": count("login", 24),
        "login_failures_1h": count("login_failed", 1), "login_failures_24h": count("login_failed", 24),
        "auth_failures_24h": count("auth_failed", 24),
        "audit_entries_24h": AuditEntry.objects.filter(at__gte=now - timedelta(hours=24)).count(),
        "syslog_sent": st.get("sent", 0), "syslog_dropped": st.get("dropped", 0),
        **_quality(),
    }


def _quality():
    """From the daily snapshot: the full quality report is too heavy for every monitoring poll."""
    q = QualitySnapshot.objects.order_by("-day").first()
    if not q or not q.counts.get("total"):
        return {}
    c = q.counts
    return {"reviewed_ok_percent": round(100 * c.get("reviewed_ok", 0) / c["total"], 1),
            **({"retention_due": c["retention_due"]} if "retention_due" in c else {})}


def collect(s=None):
    s = s or Settings.get()
    started = time.monotonic()
    cs = checks(s)
    worst = max((LEVEL[c["status"]] for c in cs), default=0)
    return {"status": ["ok", "warn", "crit"][worst], "version": dj.KARTEI_VERSION, "at": timezone.now().isoformat(),
            "checks": cs, "metrics": metrics(s), "seconds": round(time.monotonic() - started, 3)}


def prtg(data):
    """PRTG "HTTP Data Advanced": one channel per check (0 ok, 1 warn, 2 crit) and per metric."""
    result = [{"channel": "status", "value": LEVEL[data["status"]], "limitmaxwarning": 0, "limitmaxerror": 1,
               "limitmode": 1}]
    result += [{"channel": c["name"], "value": LEVEL[c["status"]], "limitmaxwarning": 0, "limitmaxerror": 1,
                "limitmode": 1} for c in data["checks"]]
    result += [{"channel": k, "value": v} for k, v in data["metrics"].items()]
    text = "; ".join(f"{c['name']}: {c['detail'] or c['status']}" for c in data["checks"] if c["status"] != "ok")
    return {"prtg": {"result": result, "text": text or "ok"}}
