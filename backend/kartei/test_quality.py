from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from . import batch, quality

from .models import AuditEntry, FieldDef, NotDuplicate, Proposal, Record, Review, Settings
from .tests import ApiTestBase, import_test_csv
from .validation import normalize_phone


class PhoneTests(ApiTestBase):
    def test_normalize(self):
        cases = {
            "0511 1000-12": "+49 511 1000-12",
            "(0511) 1000 12": "+49 511 1000 12",
            "0049 511 10000": "+49 511 10000",
            "+49 (0)511 1000": "+49 511 1000",
            "0170/1234567": "+49 170 1234567",
            "0511 - 1000": "+49 511-1000",
            "0049-511-1000-14": "+49 511-1000-14",
            "+495111000": "+49 5111000",
            "+49 0511 1000": "+49 511 1000",
            "+43 1 234567": "+43 1 234567",  # other country codes stay
            "0043 1 234567": "+43 1 234567",
            "+1 (555) 123-4567": "+1 555 123-4567",
            "1000": "1000",  # internal extension
            "12345": "12345",
        }
        for raw, want in cases.items():
            self.assertEqual(normalize_phone(raw, "+49"), want, raw)
        self.assertEqual(normalize_phone("0511 1000", ""), "0511 1000")  # switched off
        self.assertEqual(normalize_phone("01 234567", "+43"), "+43 1 234567")

    def test_saved_normalized_and_switch(self):
        self.as_("maintainer")
        r = self.j("post", "/api/records", {"kind": "person", "last_name": "A", "data": {
            "phone_work": "(0511) 1000-12", "mobile": "220"}}, status=201)
        self.assertEqual((r["data"]["phone_work"], r["data"]["mobile"]), ("+49 511 1000-12", "220"))
        Settings.objects.filter(pk=1).update(phone_normalize=False)
        r = self.j("post", "/api/records", {"kind": "person", "last_name": "B", "data": {"phone_work": "0511 1000"}},
                   status=201)
        self.assertEqual(r["data"]["phone_work"], "0511 1000")

    def test_settings(self):
        self.as_("admin")
        s = self.j("put", "/api/admin/settings", {"phone_country_code": "+43", "phone_normalize": True})
        self.assertEqual(s["phone_country_code"], "+43")
        self.j("put", "/api/admin/settings", {"phone_country_code": "49"}, status=400)
        self.as_("maintainer")
        r = self.j("post", "/api/records", {"kind": "person", "last_name": "A", "data": {"phone_work": "01 234"}},
                   status=201)
        self.assertEqual(r["data"]["phone_work"], "+43 1 234")

    def test_swap_prefix_on_normalized(self):
        self.assertEqual(batch.swap_prefix("+49 511 1000-12", "+49 511 1000", "+49 511 4711"), "+49 511 4711-12")
        self.assertEqual(batch.swap_prefix("+49 511 1000-12", "0511 1000", "0511 4711"), "0511 4711-12")
        self.assertEqual(batch.swap_prefix("0511 1000-12", "+49 511 1000", "+49 511 4711"), "+49 511 4711-12")
        self.assertEqual(batch.swap_prefix("+43 1 2345-6", "+43 1 2345", "+43 1 9999", "+43"), "+43 1 9999-6")
        self.assertEqual(batch.national("+43 1 2345", "+43"), ("012345", 1))

    def test_batch_with_normalized_numbers(self):
        self.as_("maintainer")
        co = self.j("post", "/api/records", {"kind": "company", "name": "C", "data": {"company_phone": "0511 1000"}},
                    status=201)
        p = self.j("post", "/api/records", {"kind": "person", "last_name": "P", "company": co["uid"],
                                            "data": {"phone_work": "0511 1000-12"}}, status=201)
        changed = self.j("patch", f"/api/records/{co['uid']}", {"version": co["version"],
                                                                 "data": {"company_phone": "0511 4711"}})
        changes = {"company_phone": [co["data"]["company_phone"], changed["data"]["company_phone"]]}
        self.assertEqual(changes["company_phone"], ["+49 511 1000", "+49 511 4711"])
        items = self.j("post", f"/api/records/{co['uid']}/propagate", {"changes": changes})["items"]
        self.assertEqual([(i["uid"], i["new"]) for i in items], [(p["uid"], "+49 511 4711-12")])

    def test_normalize_existing(self):
        r = Record.objects.create(kind="person", last_name="Alt", data={"phone_work": "0511 1000", "mobile": "+49 170 1"})
        Record.objects.create(kind="person", last_name="Gut", data={"phone_work": "+49 511 1"})
        self.as_("maintainer")
        self.j("post", "/api/admin/phones/normalize", {"dry_run": True}, status=403)
        self.as_("admin")
        dry = self.j("post", "/api/admin/phones/normalize", {"dry_run": True})
        self.assertEqual((dry["count"], dry["sample"][0]["new"]), (1, "+49 511 1000"))
        r.refresh_from_db()
        self.assertEqual(r.data["phone_work"], "0511 1000")
        self.assertEqual(self.j("post", "/api/admin/phones/normalize", {"dry_run": False})["count"], 1)
        r.refresh_from_db()
        self.assertEqual((r.data["phone_work"], r.version), ("+49 511 1000", 2))
        e = AuditEntry.objects.get(target_id=str(r.uid), action="update")
        self.assertEqual(e.changes, {"phone_work": ["0511 1000", "+49 511 1000"], "normalized": [None, True]})
        self.assertTrue(AuditEntry.objects.filter(action="normalize", changes__normalized=[None, 1]).exists())
        out = StringIO()
        call_command("normalize_phones", stdout=out)
        self.assertIn('"count": 0', out.getvalue())


class DuplicateTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.co = Record.objects.create(kind="company", name="Müller GmbH", data={"company_phone": "0511 1000"})
        self.co2 = Record.objects.create(kind="company", name="mueller gmbh")  # not folded to the same name
        self.co3 = Record.objects.create(kind="company", name="MÜLLER  gmbh", legacy_id="F-9")
        mk = lambda last, **kw: Record.objects.create(kind="person", last_name=last, **kw)
        self.a = mk("Meier", first_name="Hans", company=self.co, data={"email": "H.Meier@x.de", "keywords": ["a"]})
        self.b = mk("Schulz", first_name="Hans", data={"email_private": "h.meier@x.de", "phone_work": "+49 511 1000",
                                                       "mobile": "0170 1234567", "keywords": ["b"]}, legacy_id="P-5")
        self.c = mk("Other", data={"mobile": "+49 170 1234567"})  # same mobile as b
        self.d = mk("Other", data={"phone_work": "0511 1000"})  # only the company's switchboard

    def pairs(self):
        return {frozenset((p["a"], p["b"])): p["reasons"] for p in self.j("get", "/api/duplicates")["pairs"]}

    def test_candidates(self):
        self.as_("read")
        self.j("get", "/api/duplicates", status=403)
        self.as_("maintainer")
        got = self.pairs()
        u = lambda *rs: frozenset(str(r.uid) for r in rs)
        self.assertEqual(got, {u(self.co, self.co3): ["name"], u(self.a, self.b): ["email"],
                               u(self.b, self.c): ["phone"], u(self.c, self.d): ["name"]})
        self.j("post", "/api/duplicates/dismiss", {"a": str(self.d.uid), "b": str(self.c.uid)})
        self.assertNotIn(u(self.c, self.d), self.pairs())
        self.assertEqual(NotDuplicate.objects.count(), 1)
        self.assertEqual(AuditEntry.objects.filter(action="not_duplicate").count(), 2)

    def test_merge_persons(self):
        self.as_("admin")
        Review.objects.create(record=self.a, assignee=self.users["read"], reason="manual")
        prop = Proposal.objects.create(record=self.a, kind="change", proposer=self.users["read"])
        ref = Record.objects.create(kind="company", name="Ref", data={"ceo": str(self.a.uid)})
        Record.objects.filter(pk=self.b.pk).update(updated_at=timezone.now() + timedelta(minutes=1))  # b is newer
        prev = self.j("get", f"/api/duplicates/preview?a={self.b.uid}&b={self.a.uid}")
        pick = prev["pick"]
        self.assertEqual((pick["last_name"], pick["keywords"], pick["email"], pick["company"]),
                         (str(self.b.uid), "union", str(self.a.uid), str(self.a.uid)))
        body = {"keep": str(self.b.uid), "other": str(self.a.uid), "pick": pick | {"first_name": str(self.a.uid)},
                "versions": {str(self.a.uid): 1, str(self.b.uid): 2}}
        self.j("post", "/api/duplicates/merge", body, status=409)
        body["versions"][str(self.b.uid)] = 1
        rec = self.j("post", "/api/duplicates/merge", body)
        self.assertEqual((rec["last_name"], rec["company"], rec["version"]), ("Schulz", str(self.co.uid), 2))
        self.assertEqual((rec["data"]["keywords"], rec["data"]["email"], rec["data"]["email_private"]),
                         (["b", "a"], "H.Meier@x.de", "h.meier@x.de"))
        self.a.refresh_from_db()
        self.assertEqual((self.a.merged_into_id, bool(self.a.deleted_at)), (self.b.id, True))
        self.assertEqual(Review.objects.get().record_id, self.b.id)
        prop.refresh_from_db()
        self.assertEqual(prop.record_id, self.b.id)
        ref.refresh_from_db()
        self.assertEqual(ref.data["ceo"], str(self.b.uid))
        e = AuditEntry.objects.get(action="merge")
        self.assertEqual(e.changes["merged_from"], [None, "Hans Meier"])
        self.assertEqual(e.changes["company"], [None, "Müller GmbH"])
        # the SPA follows a link to the merged-away record
        res = self.j("get", f"/api/records/{self.a.uid}", status=410)
        self.assertEqual((res["error"], res["uid"]), ("merged", str(self.b.uid)))
        self.as_("read")
        self.j("get", f"/api/records/{self.a.uid}", status=410)
        self.as_("admin")
        # restoring brings it back as its own contact
        self.j("post", f"/api/records/{self.a.uid}/restore")
        self.a.refresh_from_db()
        self.assertIsNone(self.a.merged_into_id)
        self.j("get", f"/api/records/{self.a.uid}")

    def test_merge_companies_and_reimport(self):
        self.as_("maintainer")
        Record.objects.filter(pk=self.co3.pk).update(updated_at=timezone.now() + timedelta(minutes=1))
        pick = self.j("get", f"/api/duplicates/preview?a={self.co.uid}&b={self.co3.uid}")["pick"]
        self.assertEqual((pick["name"], pick["company_phone"]), (str(self.co3.uid), str(self.co.uid)))
        rec = self.j("post", "/api/duplicates/merge", {"keep": str(self.co.uid), "other": str(self.co3.uid),
                                                       "pick": pick, "versions": {str(self.co.uid): 1, str(self.co3.uid): 1}})
        self.assertEqual(rec["name"], "MÜLLER  gmbh")
        self.a.refresh_from_db()
        self.assertEqual((self.a.company_id, self.a.version), (self.co.id, 1))  # was already there
        self.co.refresh_from_db()
        self.assertEqual(self.co.merged_legacy_ids, ["F-9"])
        csv = ("ID;Vorname;Nachname;Firma\nF-9;;;MÜLLER  gmbh\nP-99;Neu;Person;MÜLLER  gmbh\n").encode()
        res = import_test_csv(csv, dry_run=False)
        self.assertEqual((res["merged_skipped"], res["companies_created"], res["persons_created"]), (1, 0, 1))
        self.assertEqual(Record.objects.get(legacy_id="P-99").company_id, self.co.id)
        self.assertEqual(Record.objects.filter(legacy_id="F-9", deleted_at__isnull=True).count(), 0)

    def test_merge_moves_persons(self):
        self.as_("maintainer")
        pick = self.j("get", f"/api/duplicates/preview?a={self.co3.uid}&b={self.co.uid}")["pick"]
        self.j("post", "/api/duplicates/merge", {"keep": str(self.co3.uid), "other": str(self.co.uid), "pick": pick,
                                                 "versions": {str(self.co.uid): 1, str(self.co3.uid): 1}})
        self.a.refresh_from_db()
        self.assertEqual((self.a.company_id, self.a.version), (self.co3.id, 2))
        self.j("post", "/api/duplicates/merge", {"keep": str(self.a.uid), "other": str(self.co3.uid)}, status=400)


class QualityReportTests(ApiTestBase):
    def test_report(self):
        FieldDef.objects.filter(key="email").update(regex=r".*@firma\.de")
        old = timezone.now() - timedelta(days=500)
        co = Record.objects.create(kind="company", name="Leer")
        p1 = Record.objects.create(kind="person", last_name="A", data={"email": "a@x.de", "internal_contact": "admin"},
                                   reviewed_at=old)
        p2 = Record.objects.create(kind="person", last_name="B", company=co, data={"salutation": "Frau Dr."},
                                   reviewed_at=timezone.now())
        self.as_("read")
        self.j("get", "/api/quality", status=403)
        self.as_("maintainer")
        q = self.j("get", "/api/quality")
        ids = lambda k: set(q[k]["items"])
        u = lambda *rs: {str(r.uid) for r in rs}
        self.assertEqual(ids("no_responsible"), u(co, p2))
        self.assertEqual({(i["uid"], i["key"], i["error"]) for i in q["invalid"]["items"]},
                         {(str(p1.uid), "email", "pattern_mismatch"), (str(p2.uid), "salutation", "invalid_option")})
        self.assertEqual(ids("no_reach"), u(p2))
        self.assertEqual(ids("no_company"), u(p1))
        self.assertEqual(ids("empty_company"), set())
        self.assertEqual(ids("never_reviewed"), u(co))
        self.assertEqual(ids("overdue"), u(p1))
        self.assertEqual(q["duplicates"]["count"], 0)
