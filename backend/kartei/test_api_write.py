import json

from django.core.cache import cache

from . import reviews
from .models import ApiToken, AuditEntry, FieldDef, Record, Review
from .tests import ApiTestBase


class ApiWriteTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.as_("admin")
        self.read = self.j("post", "/api/admin/tokens", {"name": "Telefonanlage"}, status=201)["token"]
        self.tok = self.j("post", "/api/admin/tokens", {"name": "CRM-Sync", "scope": "write"}, status=201)["token"]
        self.client.logout()

    def api(self, method, url, body=None, status=200, token=None, **headers):
        resp = getattr(self.client, method)(url, json.dumps(body) if body is not None else "",
                                            content_type="application/json",
                                            HTTP_AUTHORIZATION=f"Bearer {token or self.tok}", **headers)
        self.assertEqual(resp.status_code, status, resp.content[:500])
        return resp.json()

    def company(self, name="Beispiel GmbH"):
        return self.api("post", "/api/v1/contacts", {"kind": "company", "name": name}, status=201)

    def test_token_scopes_in_admin(self):
        self.as_("admin")
        listed = {t["name"]: t["scope"] for t in self.j("get", "/api/admin/tokens")["tokens"]}
        self.assertEqual(listed, {"Telefonanlage": "read", "CRM-Sync": "write"})
        self.j("post", "/api/admin/tokens", {"name": "X", "scope": "admin"}, status=400)
        created = AuditEntry.objects.filter(target_type="token", action="create").values_list("changes", flat=True)
        self.assertIn({"name": [None, "CRM-Sync"], "scope": [None, "write"]}, list(created))
        self.assertEqual(ApiToken._meta.get_field("scope").default, "read")

    def test_read_token_cannot_write(self):
        c = self.company()
        url = f"/api/v1/contacts/{c['uid']}"
        self.api("post", "/api/v1/contacts", {"kind": "company", "name": "Nein"}, status=403, token=self.read)
        self.api("patch", url, {"name": "Nein"}, status=403, token=self.read)
        self.api("delete", url, status=403, token=self.read)
        self.assertEqual(self.api("get", url, token=self.read)["name"], "Beispiel GmbH")
        self.api("put", url, {"name": "Nein"}, status=405)
        self.api("post", "/api/v1/contacts", {"kind": "company", "name": "Nein"}, status=401, token="kt_wrong")
        self.assertEqual(Record.objects.count(), 1)

    def test_create_update_and_audit(self):
        c = self.company()
        self.assertEqual((c["kind"], c["name"], c["version"]), ("company", "Beispiel GmbH", 1))
        p = self.api("post", "/api/v1/contacts", {
            "kind": "person", "first_name": " Anna ", "last_name": "Schmidt", "company": c["uid"],
            "data": {"mobile": "0170/1234567", "department": "Einkauf", "keywords": ["Neu-Tag"]}}, status=201)
        self.assertEqual((p["first_name"], p["company"], p["company_name"]), ("Anna", c["uid"], "Beispiel GmbH"))
        self.assertEqual(p["data"]["mobile"], "+49 170 1234567")  # phone normalization as in the UI
        self.assertIn("Neu-Tag", [o["value"] for o in FieldDef.objects.get(key="keywords").options])  # open field

        url = f"/api/v1/contacts/{p['uid']}"
        p2 = self.api("patch", url, {"version": 1, "data": {"department": None, "job_title": "Leitung"}})
        self.assertEqual(p2["version"], 2)
        self.assertEqual(p2["data"]["mobile"], "+49 170 1234567")  # untouched keys stay
        self.assertNotIn("department", p2["data"])  # null clears
        self.assertEqual(p2["first_name"], "Anna")
        p3 = self.api("patch", url, {"data": {"job_title": ""}, "company": None})  # no version: last write wins
        self.assertEqual((p3["version"], p3["company"], p3["data"].get("job_title")), (3, None, None))
        self.assertEqual(self.api("patch", url, {"data": {}})["version"], 3)  # no change, no new version

        entries = AuditEntry.objects.filter(target_id=p["uid"]).order_by("id")
        self.assertEqual([(e.action, e.username, e.user_id) for e in entries],
                         [("create", "api:CRM-Sync", None), ("update", "api:CRM-Sync", None),
                          ("update", "api:CRM-Sync", None)])
        self.assertEqual(entries[1].changes, {"department": ["Einkauf", None], "job_title": [None, "Leitung"]})
        opt = AuditEntry.objects.get(target_type="field", action="update")
        self.assertEqual(opt.username, "api:CRM-Sync")
        self.assertIsNone(Record.objects.get(uid=p["uid"]).updated_by)

    def test_validation(self):
        c = self.company()
        url = f"/api/v1/contacts/{c['uid']}"
        e = self.api("post", "/api/v1/contacts", {"kind": "robot"}, status=400)
        self.assertEqual(e, {"error": "validation", "fields": {"kind": "invalid"}})
        e = self.api("post", "/api/v1/contacts", {"kind": "person", "first_name": "", "company": "kein-uuid",
                                                  "data": {"email": "kaputt", "nope": "x"}}, status=400)
        self.assertEqual(e["fields"], {"last_name": "required", "company": "invalid_company", "email": "invalid_email",
                                       "nope": "unknown_field"})
        self.assertEqual(self.api("patch", url, {"name": ""}, status=400)["fields"], {"name": "required"})
        self.assertEqual(self.api("patch", url, {"kind": "person"}, status=400)["fields"], {"kind": "read_only"})
        self.assertEqual(self.api("patch", url, {"version": "x"}, status=400)["fields"], {"version": "invalid"})
        resp = self.client.patch(url, "[1]", content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.tok}")
        self.assertEqual((resp.status_code, resp.json()["error"]), (400, "invalid_json"))
        self.api("patch", "/api/v1/contacts/00000000-0000-4000-8000-000000000000", {"name": "X"}, status=404)
        self.assertEqual(Record.objects.get().version, 1)

    def test_forbidden_and_hidden_fields(self):
        FieldDef.objects.filter(key="customer_no").update(editable_by="admin")
        FieldDef.objects.filter(key="contract_no").update(visible_to="maintainer")
        FieldDef.objects.filter(key="description").update(visible_to="admin", editable_by="admin")
        c = self.company()
        url = f"/api/v1/contacts/{c['uid']}"
        e = self.api("patch", url, {"data": {"customer_no": "K1", "contract_no": "V1", "description": "geheim"}},
                     status=400)
        self.assertEqual(e, {"error": "validation", "fields": {
            "customer_no": "forbidden", "contract_no": "unknown_field", "description": "unknown_field"}})
        # values set in the UI stay untouched and invisible
        Record.objects.filter(uid=c["uid"]).update(data={"contract_no": "V9", "customer_no": "K9"})
        out = self.api("patch", url, {"data": {"website": "https://example.com", "customer_no": "K9"}})
        self.assertEqual(out["data"], {"website": "https://example.com", "customer_no": "K9"})
        self.assertEqual(Record.objects.get(uid=c["uid"]).data["contract_no"], "V9")

    def test_version_conflict_and_if_match(self):
        c = self.company()
        url = f"/api/v1/contacts/{c['uid']}"
        resp = self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {self.tok}")
        self.assertEqual(resp["ETag"], '"1"')
        self.api("patch", url, {"version": 1, "name": "Neu GmbH"})
        e = self.api("patch", url, {"version": 1, "name": "Alt GmbH"}, status=409)
        self.assertEqual((e["error"], e["contact"]["name"], e["contact"]["version"]), ("version_conflict", "Neu GmbH", 2))
        self.api("patch", url, {"name": "Alt GmbH"}, status=409, HTTP_IF_MATCH='"1"')
        out = self.api("patch", url, {"name": "Alt GmbH"}, HTTP_IF_MATCH='"2"')
        self.assertEqual((out["name"], out["version"]), ("Alt GmbH", 3))

    def test_delete_and_with_persons(self):
        c = self.company()
        p = self.api("post", "/api/v1/contacts", {"kind": "person", "last_name": "Weber", "company": c["uid"]},
                     status=201)
        other = self.api("post", "/api/v1/contacts", {"kind": "person", "last_name": "Allein"}, status=201)
        out = self.api("delete", f"/api/v1/contacts/{other['uid']}")
        self.assertEqual(out, {"ok": True, "deleted": [other["uid"]]})
        self.api("delete", f"/api/v1/contacts/{other['uid']}", status=404)
        self.api("get", f"/api/v1/contacts/{other['uid']}", status=404)
        self.assertIsNotNone(Record.objects.get(uid=other["uid"]).deleted_at)  # recycle bin, not gone

        out = self.api("delete", f"/api/v1/contacts/{c['uid']}?with_persons=1")
        self.assertEqual(out["deleted"], [c["uid"], p["uid"]])
        self.assertFalse(Record.objects.filter(deleted_at__isnull=True).exists())
        logged = AuditEntry.objects.filter(action="delete", target_type="record")
        self.assertEqual({e.username for e in logged}, {"api:CRM-Sync"})
        self.assertEqual(logged.get(target_id=p["uid"]).changes, {"with_company": [None, "Beispiel GmbH"]})

        # without the flag the persons stay (and keep their company link)
        c2 = self.company("Zweite AG")
        p2 = self.api("post", "/api/v1/contacts", {"kind": "person", "last_name": "Bleibt", "company": c2["uid"]},
                      status=201)
        self.assertEqual(self.api("delete", f"/api/v1/contacts/{c2['uid']}")["deleted"], [c2["uid"]])
        self.assertIsNone(Record.objects.get(uid=p2["uid"]).deleted_at)

    def test_session_delete_with_persons(self):
        c = self.company()
        p = self.api("post", "/api/v1/contacts", {"kind": "person", "last_name": "Weber", "company": c["uid"]},
                     status=201)
        self.as_("maintainer")
        self.j("delete", f"/api/records/{c['uid']}?with_persons=1")
        self.assertIsNotNone(Record.objects.get(uid=p["uid"]).deleted_at)
        self.assertEqual(AuditEntry.objects.get(target_id=p["uid"], action="delete").username, "maintainer")

    def test_review_follows_new_responsible(self):
        c = self.api("post", "/api/v1/contacts", {"kind": "company", "name": "Beispiel GmbH",
                                                  "data": {"internal_contact": "read"}}, status=201)
        r = Record.objects.get(uid=c["uid"])
        reviews.start([r], "manual")
        self.assertEqual(Review.objects.get().assignee.username, "read")
        self.api("patch", f"/api/v1/contacts/{c['uid']}", {"data": {"internal_contact": "maintainer"}})
        self.assertEqual(Review.objects.get().assignee.username, "maintainer")
        self.api("delete", f"/api/v1/contacts/{c['uid']}")
        self.assertEqual(Review.objects.get().outcome, "cancelled")

    def test_last_used_and_rate_limit(self):
        self.company()
        self.assertIsNotNone(ApiToken.objects.get(name="CRM-Sync").last_used_at)
        for _ in range(20):
            self.api("post", "/api/v1/contacts", {"kind": "company", "name": "X"}, status=401, token="kt_wrong")
        self.api("post", "/api/v1/contacts", {"kind": "company", "name": "X"}, status=429)
        self.assertEqual(Record.objects.count(), 1)
