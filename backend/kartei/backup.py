"""Database backups into BACKUP_ROOT (the /backup volume, its own host directory, never the export share).

PostgreSQL: pg_dump in its custom format (compressed; restore with pg_restore). SQLite (development): the online
backup API. The exporter runs a backup daily at the configured time and on request ("back up now"), keeps the files
for the configured number of days (always at least the newest), and checks every file it writes (pg_restore --list).
A restore test, on request, restores the newest file into a scratch database and counts what came back.
"""
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import Settings

BACKUP_ROOT = Path(os.environ.get("BACKUP_ROOT", str(Path(settings.BASE_DIR).parent / "backups")))
PREFIX = "kartei-"
SUFFIXES = (".dump", ".sqlite3")
TABLES = ["kartei_record", "kartei_fielddef", "auth_user", "kartei_auditentry"]  # counted by the restore test
TIMEOUT = 3600


class BackupError(Exception):
    pass


def _db():
    return settings.DATABASES["default"]


def _postgres():
    return "postgresql" in _db()["ENGINE"]


def _pg_env(name=None):
    """libpq environment for pg_dump/pg_restore from Django's connection settings (also sslmode etc.)."""
    db, opts = _db(), _db().get("OPTIONS", {})
    env = {**os.environ, "PGHOST": str(db.get("HOST") or ""), "PGPORT": str(db.get("PORT") or ""),
           "PGUSER": str(db.get("USER") or ""), "PGPASSWORD": str(db.get("PASSWORD") or ""),
           "PGDATABASE": name or db["NAME"]}
    for key, var in (("sslmode", "PGSSLMODE"), ("sslrootcert", "PGSSLROOTCERT"), ("sslcert", "PGSSLCERT"),
                     ("sslkey", "PGSSLKEY")):
        if opts.get(key):
            env[var] = str(opts[key])
    return env


def _run(cmd, env=None):
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BackupError(str(e))
    if r.returncode:
        raise BackupError((r.stderr or r.stdout).strip().splitlines()[-1][:300] if (r.stderr or r.stdout) else f"exit {r.returncode}")
    return r.stdout


def files():
    """Backup files, newest first: [{"name", "size", "at"}]."""
    if not BACKUP_ROOT.is_dir():
        return []
    out = [p for p in BACKUP_ROOT.iterdir() if p.name.startswith(PREFIX) and p.suffix in SUFFIXES and p.is_file()]
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "size": p.stat().st_size,
             "at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.get_current_timezone()).isoformat()} for p in out]


def prune(keep_days):
    """Delete backups older than keep_days; the newest one always stays."""
    limit = time.time() - keep_days * 86400
    for f in files()[1:]:
        p = BACKUP_ROOT / f["name"]
        if p.stat().st_mtime < limit:
            p.unlink()


def due(s, now=None):
    """Exporter tick: once a day at the configured time (local time), unless today's run already happened."""
    if not s.backup_enabled:
        return False
    now = timezone.localtime(now)
    hh, mm = map(int, s.backup_time.split(":"))
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < slot:
        return False
    last = (s.backup_status or {}).get("at")
    return not last or datetime.fromisoformat(last) < slot


def _dump(path):
    tmp = path.with_name(path.name + ".part")
    try:
        if _postgres():
            _run(["pg_dump", "--format=custom", "--no-owner", f"--file={tmp}"], env=_pg_env())
            _run(["pg_restore", "--list", str(tmp)])  # the archive can be read back
        else:
            if connection.in_atomic_block:  # SQLite's backup would wait for this very transaction forever
                raise BackupError("SQLite backup inside an open transaction")
            connection.ensure_connection()  # Django's own connection: also the in-memory test database
            dst = sqlite3.connect(tmp)
            try:
                connection.connection.backup(dst)
            finally:
                dst.close()
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def run():
    """Write one backup now. Returns the status, also stored in Settings.backup_status."""
    Settings.objects.filter(pk=1).update(backup_requested=None)
    s = Settings.get()
    started = time.monotonic()
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_ROOT / f"{PREFIX}{stamp}{'.dump' if _postgres() else '.sqlite3'}"
    status = {"at": timezone.now().isoformat()}
    try:
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        _dump(path)
        prune(s.backup_keep_days)
        status |= {"ok": True, "file": path.name, "size": path.stat().st_size}
    except (BackupError, OSError, sqlite3.Error) as e:
        status |= {"error": str(e)[:300]}
    status |= {"seconds": round(time.monotonic() - started, 1), "files": files()[:30]}
    try:
        status["free"] = round(_free_percent(), 1)
    except OSError:
        pass
    Settings.objects.filter(pk=1).update(backup_status=status)
    return status


def _free_percent():
    import shutil
    du = shutil.disk_usage(BACKUP_ROOT)
    return du.free / du.total * 100


def _count(cursor):
    out = {}
    for t in TABLES:
        cursor.execute(f'SELECT count(*) FROM "{t}"')  # fixed table names, no input
        out[t] = cursor.fetchone()[0]
    return out


def restore_test():
    """Restore the newest backup into a scratch database, count the main tables there and in the live database,
    drop the scratch database. Returns the status, also stored in Settings.restore_test_status."""
    Settings.objects.filter(pk=1).update(restore_test_requested=None)
    status = {"at": timezone.now().isoformat()}
    newest = files()[:1]
    try:
        if not newest:
            raise BackupError("no backup yet")
        path = BACKUP_ROOT / newest[0]["name"]
        status["file"] = path.name
        if path.suffix == ".dump":
            restored = _restore_postgres(path)
        else:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("integrity check failed")
                restored = _count(con.cursor())
            finally:
                con.close()
        with connection.cursor() as c:
            live = _count(c)
        if not sum(restored.values()) and sum(live.values()):
            raise BackupError("the restored database is empty")
        status |= {"ok": True, "tables": {t: [restored[t], live[t]] for t in TABLES}}
    except (BackupError, OSError, sqlite3.Error) as e:
        status |= {"error": str(e)[:300]}
    Settings.objects.filter(pk=1).update(restore_test_status=status)
    return status


def _restore_postgres(path):
    import psycopg
    from psycopg import sql
    name = f"{_db()['NAME']}_restore_test"[:63]
    env = _pg_env()
    admin = dict(host=env["PGHOST"] or None, port=env["PGPORT"] or None, user=env["PGUSER"], password=env["PGPASSWORD"],
                 dbname=_db()["NAME"], autocommit=True, sslmode=env.get("PGSSLMODE"), sslrootcert=env.get("PGSSLROOTCERT"))
    admin = {k: v for k, v in admin.items() if v is not None}
    try:
        with psycopg.connect(**admin) as con:
            con.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
            con.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.Error as e:
        raise BackupError(f"cannot create the scratch database {name}: {str(e).strip()[:200]}")
    try:
        _run(["pg_restore", "--no-owner", "--exit-on-error", f"--dbname={name}", str(path)], env=_pg_env(name))
        with psycopg.connect(**{**admin, "dbname": name}) as con:
            return _count(con.cursor())
    finally:
        with psycopg.connect(**admin) as con:
            con.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
