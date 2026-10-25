"""Data protection: anonymised history on purge (Art. 17) and the data subject access report (Art. 15)."""
from datetime import timedelta

from django.utils import timezone

from .management.commands import export_loop
from .models import AuditEntry, ExportProfile, FieldDef, Record, Settings, Webhook
from .tests import ApiTestBase


class PurgeTests(ApiTestBase):
    def make(self):
        self.as_("maintainer")
        r = self.j("post", "/api/records", {"kind": "person", "first_name": "Petra", "last_name": "Privat",
                                            "data": {"email": "petra@privat.example"}}, status=201)
        self.j("patch", f"/api/records/{r['uid']}", {"version": r["version"], "data": {"mobile": "0170 1234567"}})
        self.j("delete", f"/api/records/{r['uid']}")
        self.as_("admin")
        return r["uid"]

    def test_purge_anonymizes_the_history(self):
        uid = self.make()
        self.j("delete", f"/api/trash/{uid}")
        self.assertFalse(Record.objects.filter(uid=uid).exists())
        entries = AuditEntry.objects.filter(target_type="record", target_id=uid)
        self.assertEqual(list(entries.order_by("at").values_list("action", flat=True)), ["create", "update", "delete", "purge"])
        self.assertEqual({e.target_label for e in entries}, {""})  # no name left
        text = " ".join(str(e.changes) for e in entries)
        for value in ("Privat", "petra@privat.example", "1234567"):
            self.assertNotIn(value, text)
        self.assertEqual(entries.get(action="purge").changes, {"anonymized": [None, True]})
        self.assertEqual(entries.get(action="update").username, "maintainer")  # who and when stay

    def test_purge_without_anonymizing_keeps_values(self):
        Settings.objects.update(purge_anonymize=False)
        uid = self.make()
        self.j("delete", f"/api/trash/{uid}")
        purge = AuditEntry.objects.get(target_id=uid, action="purge")
        self.assertEqual(purge.target_label, "Petra Privat")
        self.assertIn("petra@privat.example", str(purge.changes))

    def test_automatic_emptying_anonymizes_too(self):
        uid = self.make()
        Settings.objects.update(trash_days=30)
        Record.objects.filter(uid=uid).update(deleted_at=timezone.now() - timedelta(days=31))
        export_loop.tick()
        purge = AuditEntry.objects.get(target_id=uid, action="purge")
        self.assertEqual(purge.changes, {"anonymized": [None, True], "reason": [None, "trash_days=30"]})
        self.assertNotIn("Privat", str(list(AuditEntry.objects.filter(target_id=uid).values("target_label", "changes"))))


class ReportTests(ApiTestBase):
    def test_report_has_all_data_history_and_recipients(self):
        f = FieldDef.objects.get(key="description")
        f.visible_to = "admin"  # even admin-only fields belong in the report
        f.save()
        self.as_("maintainer")
        r = self.j("post", "/api/records", {"kind": "person", "last_name": "Auskunft",
                                            "data": {"email": "a@auskunft.example"}}, status=201)
        Record.objects.filter(uid=r["uid"]).update(data={"email": "a@auskunft.example", "description": "intern"})
        self.j("get", f"/api/records/{r['uid']}/report", status=403)
        self.as_("read")
        self.j("get", f"/api/records/{r['uid']}/report", status=403)
        Settings.objects.update(carddav_enabled=True)
        ExportProfile.objects.create(name="Telefonliste", path="/export/t.csv", kinds="person",
                                     columns=[{"header": "Name", "person": "calc:display_name", "company": ""}])
        ExportProfile.objects.create(name="Nur Firmen", path="/export/f.csv", kinds="company", columns=[])
        Webhook.objects.create(name="Intranet", url="https://intranet.example/hook")
        self.as_("admin")
        rep = self.j("get", f"/api/records/{r['uid']}/report")
        self.assertEqual(rep["record"]["data"], {"email": "a@auskunft.example", "description": "intern"})
        self.assertEqual([e["action"] for e in rep["history"]], ["create", "report"])  # the report itself is recorded
        systems = {(x["system"], x.get("name")) for x in rep["recipients"]}
        self.assertEqual(systems, {("carddav", None), ("export", "Telefonliste"), ("webhook", "Intranet")})
        carddav = next(x for x in rep["recipients"] if x["system"] == "carddav")
        self.assertIn({"de": "E-Mail", "en": "Email"}, carddav["fields"])  # shared: visible to everyone, vCard target
        self.assertNotIn("intern", str(carddav))
        self.assertTrue(AuditEntry.objects.filter(target_id=r["uid"], action="report", username="admin").exists())
