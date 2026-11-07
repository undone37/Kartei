import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest import mock

from django.test import TransactionTestCase
from django.utils import timezone

from . import backup, monitoring
from .models import Settings
from .tests import ApiTestBase, load_fields


class TempBackupDir:
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.object(backup, "BACKUP_ROOT", Path(self.dir.name))
        patcher.start()
        self.addCleanup(patcher.stop)


class BackupFileTests(TempBackupDir, TransactionTestCase):
    """Real backups need a database without an open transaction (SQLite's backup waits for it), like the exporter."""
    def setUp(self):
        super().setUp()
        Settings.get()
        load_fields()

    def test_backup_restore_test_and_retention(self):
        if backup._postgres() and not shutil.which("pg_dump"):
            self.skipTest("pg_dump not installed")
        st = backup.run()
        self.assertTrue(st.get("ok"), st)
        self.assertTrue(st["file"].startswith("kartei-") and st["file"].endswith(".dump" if backup._postgres() else ".sqlite3"))
        self.assertEqual([f["name"] for f in st["files"]], [st["file"]])
        self.assertEqual(Settings.get().backup_status["file"], st["file"])
        rt = backup.restore_test()
        self.assertTrue(rt.get("ok"), rt)
        self.assertEqual(rt["tables"]["kartei_fielddef"][0], rt["tables"]["kartei_fielddef"][1])  # restored = live
        # retention: older files go, the newest always stays
        old = Path(self.dir.name) / f"kartei-20200101-023000{Path(st['file']).suffix}"
        old.write_bytes(b"x")
        os.utime(old, (time.time() - 30 * 86400,) * 2)
        backup.prune(14)
        self.assertFalse(old.exists())
        newest = Path(self.dir.name) / st["file"]
        os.utime(newest, (time.time() - 30 * 86400,) * 2)
        backup.prune(14)
        self.assertTrue(newest.exists())



class BackupTests(TempBackupDir, ApiTestBase):
    def test_errors_are_reported(self):
        with mock.patch.object(backup, "BACKUP_ROOT", Path("/proc/kartei-not-writable")):
            st = backup.run()
        self.assertIn("error", st)
        self.assertEqual({c["name"]: c["status"] for c in monitoring.checks(Settings.get())}["backup"], "crit")
        Settings.objects.update(backup_status={})
        rt = backup.restore_test()  # nothing to restore yet
        self.assertEqual(rt["error"], "no backup yet")

    def test_schedule(self):
        s = Settings.get()
        s.backup_time = "02:30"
        tz = timezone.get_current_timezone()
        at = lambda h, m: datetime(2026, 11, 7, h, m, tzinfo=tz)
        self.assertFalse(backup.due(s, at(2, 0)))  # not yet
        self.assertTrue(backup.due(s, at(2, 31)))
        s.backup_status = {"at": at(2, 31).isoformat()}
        self.assertFalse(backup.due(s, at(9, 0)))  # done today
        s.backup_status = {"at": datetime(2026, 11, 6, 2, 31, tzinfo=tz).isoformat()}
        self.assertTrue(backup.due(s, at(9, 0)))  # yesterday's
        s.backup_enabled = False
        self.assertFalse(backup.due(s, at(9, 0)))

    def test_settings_and_requests(self):
        self.as_("admin")
        r = self.j("put", "/api/admin/settings", {"backup_time": "25:00", "backup_keep_days": 0}, status=400)
        self.assertEqual(r["fields"], {"backup_time": "invalid", "backup_keep_days": "invalid_number"})
        s = self.j("put", "/api/admin/settings", {"backup_time": "03:15", "backup_keep_days": 30})
        self.assertEqual((s["backup_time"], s["backup_keep_days"]), ("03:15", 30))
        self.assertTrue(self.j("post", "/api/admin/backup/run")["backup_requested"])
        self.assertTrue(self.j("post", "/api/admin/backup/restore-test")["restore_test_requested"])
        self.as_("maintainer")
        self.j("post", "/api/admin/backup/run", status=403)
