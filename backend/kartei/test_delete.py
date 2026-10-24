"""Moving a company to the recycle bin together with its persons, undo, bulk delete."""
from .models import AuditEntry, Record
from .tests import ApiTestBase


def audit_of(r, action="delete"):
    return AuditEntry.objects.filter(target_type="record", target_id=str(r.uid), action=action).order_by("-id").first()


class Base(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.company = Record.objects.create(kind="company", name="Beispiel GmbH")
        self.p1 = Record.objects.create(kind="person", last_name="Adler", company=self.company)
        self.p2 = Record.objects.create(kind="person", last_name="Berg", company=self.company)
        self.gone = Record.objects.create(kind="person", last_name="Cramer", company=self.company)
        self.gone.deleted_at = self.company.created_at
        self.gone.save()
        self.other = Record.objects.create(kind="person", last_name="Dorn")
        self.as_("maintainer")

    def live(self, *recs):
        return [Record.objects.get(pk=r.pk).deleted_at is None for r in recs]


class DeleteWithPersonsTests(Base):
    def test_company_alone(self):
        out = self.j("delete", f"/api/records/{self.company.uid}")
        self.assertEqual(out["deleted"], [str(self.company.uid)])
        self.assertEqual(self.live(self.company, self.p1, self.p2), [False, True, True])
        self.assertIsNone(audit_of(self.p1))

    def test_company_with_persons(self):
        out = self.j("delete", f"/api/records/{self.company.uid}?with_persons=1")
        self.assertEqual(out["deleted"], [str(self.company.uid), str(self.p1.uid), str(self.p2.uid)])
        self.assertEqual(self.live(self.company, self.p1, self.p2, self.other), [False, False, False, True])
        e = audit_of(self.p1)
        self.assertEqual(e.changes, {"with_company": [None, "Beispiel GmbH"]})
        self.assertEqual(e.user, self.users["maintainer"])
        self.assertEqual(audit_of(self.company).changes, {})
        # the person already in the recycle bin keeps its own deletion
        self.assertIsNone(audit_of(self.gone))
        # the deletions reach other clients through /api/changes
        self.assertEqual(Record.objects.get(pk=self.p2.pk).version, self.p2.version + 1)

    def test_flag_in_json_body_and_ignored_for_persons(self):
        out = self.j("delete", f"/api/records/{self.company.uid}", {"with_persons": True})
        self.assertEqual(len(out["deleted"]), 3)
        out = self.j("delete", f"/api/records/{self.other.uid}?with_persons=1")
        self.assertEqual(out["deleted"], [str(self.other.uid)])

    def test_company_without_persons(self):
        empty = Record.objects.create(kind="company", name="Leer AG")
        out = self.j("delete", f"/api/records/{empty.uid}?with_persons=1")
        self.assertEqual(out["deleted"], [str(empty.uid)])

    def test_read_only_cannot_delete(self):
        self.as_("read")
        self.j("delete", f"/api/records/{self.company.uid}?with_persons=1", status=403)
        self.assertEqual(self.live(self.company, self.p1), [True, True])

    def test_undo_restores_all(self):
        out = self.j("delete", f"/api/records/{self.company.uid}?with_persons=1")
        persons = out["deleted"][1:]
        back = self.j("post", f"/api/records/{self.company.uid}/restore",
                      {"persons": [*persons, str(self.other.uid), "nope", 3]})
        self.assertEqual(back["uid"], str(self.company.uid))
        self.assertEqual(sorted(p["uid"] for p in back["persons"]), sorted(persons))
        # only the listed persons of this company; the one deleted earlier stays in the recycle bin
        self.assertEqual(self.live(self.company, self.p1, self.p2, self.gone), [True, True, True, False])
        self.assertEqual(audit_of(self.p1, "restore").user, self.users["maintainer"])

    def test_restore_without_persons_keeps_old_shape(self):
        self.j("delete", f"/api/records/{self.company.uid}?with_persons=1")
        back = self.j("post", f"/api/records/{self.company.uid}/restore")
        self.assertNotIn("persons", back)
        self.assertEqual(self.live(self.company, self.p1, self.p2), [True, False, False])

    def test_restore_ignores_persons_of_other_companies(self):
        rival = Record.objects.create(kind="company", name="Andere KG")
        stranger = Record.objects.create(kind="person", last_name="Engel", company=rival)
        self.j("delete", f"/api/records/{stranger.uid}")
        self.j("delete", f"/api/records/{self.company.uid}?with_persons=1")
        back = self.j("post", f"/api/records/{self.company.uid}/restore", {"persons": [str(stranger.uid)]})
        self.assertNotIn("persons", back)
        self.assertEqual(self.live(stranger), [False])


class BulkDeleteWithPersonsTests(Base):
    def bulk(self, uids, **extra):
        return self.j("post", "/api/records/bulk", {"op": "delete", "uids": [str(u) for u in uids], **extra})

    def test_bulk_without_flag_leaves_persons(self):
        out = self.bulk([self.company.uid, self.other.uid])
        self.assertEqual(out["deleted"], [str(self.company.uid), str(self.other.uid)])
        self.assertEqual(self.live(self.p1, self.p2), [True, True])

    def test_bulk_with_persons(self):
        # p1 is selected after its company: it goes with the company and is not reported as an error
        out = self.bulk([self.company.uid, self.p1.uid, self.other.uid], with_persons=True)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["deleted"], [str(self.company.uid), str(self.p1.uid), str(self.p2.uid), str(self.other.uid)])
        self.assertEqual(self.live(self.company, self.p1, self.p2, self.other), [False, False, False, False])
        self.assertEqual(audit_of(self.p2).changes, {"bulk": [None, True], "with_company": [None, "Beispiel GmbH"]})
        self.assertEqual(audit_of(self.company).changes, {"bulk": [None, True]})
        self.assertEqual(audit_of(self.other).changes, {"bulk": [None, True]})

    def test_bulk_person_before_company(self):
        out = self.bulk([self.p1.uid, self.company.uid], with_persons=True)
        self.assertEqual(out["deleted"], [str(self.p1.uid), str(self.company.uid), str(self.p2.uid)])
        self.assertEqual(audit_of(self.p1).changes, {"bulk": [None, True]})  # deleted on its own
