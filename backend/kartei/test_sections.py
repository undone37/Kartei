"""Field sections: CRUD, delete guard, ordering, field files v1 and v2."""
import copy
from urllib.parse import urlencode

from .models import AuditEntry, FieldDef, FieldSection
from .tests import ApiTestBase, example


def keys(qs):
    return list(qs.values_list("key", flat=True))


class SectionApiTests(ApiTestBase):
    def test_example_sections_loaded_in_file_order(self):
        self.assertEqual(keys(FieldSection.objects.all()), [s["key"] for s in example("fields-example.json")["sections"]])
        self.assertEqual(FieldDef.objects.get(key="mobile").section.key, "communication")
        self.assertEqual(FieldDef.objects.get(key="description").section.key, "notes")

    def test_admin_only(self):
        self.as_("maintainer")
        self.j("get", "/api/admin/sections", status=403)
        self.j("post", "/api/admin/sections", {"label": {"de": "X", "en": "X"}}, status=403)

    def test_create_rename_reorder(self):
        self.as_("admin")
        s = self.j("post", "/api/admin/sections", {"label": {"de": "Vertrag", "en": ""}}, status=201)
        self.assertEqual((s["key"], s["label"]), ("vertrag", {"de": "Vertrag", "en": "Vertrag"}))
        self.assertEqual(FieldSection.objects.last().key, "vertrag")  # appended
        self.j("post", "/api/admin/sections", {"label": {"de": "", "en": " "}}, status=400)
        again = self.j("post", "/api/admin/sections", {"label": {"de": "Vertrag", "en": "Vertrag"}}, status=201)
        self.assertEqual(again["key"], "vertrag_2")

        s = self.j("patch", f"/api/admin/sections/{s['id']}", {"label": {"de": "Verträge", "en": "Contracts"}})
        self.assertEqual((s["key"], s["label"]["en"]), ("vertrag", "Contracts"))  # key stays stable
        e = AuditEntry.objects.filter(target_type="section", action="update").first()
        self.assertEqual(e.changes, {"label_de": ["Vertrag", "Verträge"], "label_en": ["Vertrag", "Contracts"]})

        ids = list(FieldSection.objects.values_list("id", flat=True))
        ids.remove(s["id"])
        res = self.j("post", "/api/admin/sections/reorder", {"ids": [s["id"], *ids]})["sections"]
        self.assertEqual(res[0]["key"], "vertrag")
        self.assertTrue(AuditEntry.objects.filter(target_type="section", action="reorder").exists())

    def test_bootstrap_lists_sections_and_field_ids(self):
        self.as_("read")
        b = self.j("get", "/api/bootstrap")
        self.assertEqual([s["key"] for s in b["sections"]], keys(FieldSection.objects.all()))
        self.assertEqual(set(b["sections"][0]), {"id", "key", "label", "order"})
        comm = FieldSection.objects.get(key="communication").id
        self.assertEqual(next(f for f in b["fields"] if f["key"] == "mobile")["section"], comm)
        self.assertIn("sections", self.j("get", "/api/changes?" + urlencode({"since": b["cursor"]})))

    def test_field_section_by_id(self):
        self.as_("admin")
        notes = FieldSection.objects.get(key="notes")
        f = self.j("post", "/api/admin/fields", {"label": {"de": "A", "en": "A"}, "section": notes.id}, status=201)
        self.assertEqual(f["section"], notes.id)
        f = self.j("patch", f"/api/admin/fields/{f['id']}", {"section": None})
        self.assertIsNone(f["section"])
        e = AuditEntry.objects.filter(target_type="field", action="update").first()
        self.assertEqual(e.changes, {"section": [notes.id, None]})
        r = self.j("patch", f"/api/admin/fields/{f['id']}", {"section": 99999}, status=400)
        self.assertEqual(r["fields"], {"section": "invalid"})

    def test_drag_between_sections(self):
        self.as_("admin")
        mobile, notes = FieldDef.objects.get(key="mobile"), FieldSection.objects.get(key="notes")
        ids = list(FieldDef.objects.exclude(pk=mobile.pk).values_list("id", flat=True)) + [mobile.id]
        self.j("post", "/api/admin/fields/reorder", {"ids": ids, "moves": {str(mobile.id): notes.id}})
        mobile.refresh_from_db()
        self.assertEqual((mobile.section_id, list(FieldDef.objects.values_list("id", flat=True))[-1]), (notes.id, mobile.id))
        self.j("post", "/api/admin/fields/reorder", {"ids": ids, "moves": {str(mobile.id): "x"}}, status=400)

    def test_delete_guard(self):
        self.as_("admin")
        comm, notes = FieldSection.objects.get(key="communication"), FieldSection.objects.get(key="notes")
        n = FieldDef.objects.filter(section=comm, archived=False).count()
        r = self.j("delete", f"/api/admin/sections/{comm.id}", status=409)
        self.assertEqual((r["error"], r["count"]), ("section_in_use", n))
        self.j("delete", f"/api/admin/sections/{comm.id}?move_to={comm.id}", status=400)  # not into itself

        # archived fields don't block; they fall back to "Other"
        FieldDef.objects.filter(section=notes).update(archived=True)
        self.j("delete", f"/api/admin/sections/{notes.id}")
        self.assertIsNone(FieldDef.objects.get(key="description").section_id)
        self.assertTrue(AuditEntry.objects.filter(target_type="section", action="delete", target_label="Notizen").exists())

        # move the fields to another section, then delete
        internal = FieldSection.objects.get(key="internal")
        self.j("delete", f"/api/admin/sections/{comm.id}?move_to={internal.id}")
        self.assertEqual(FieldDef.objects.filter(section=internal).count(), 5 + n)
        self.assertFalse(FieldSection.objects.filter(key="communication").exists())
        home = FieldSection.objects.get(key="home_address")
        self.j("delete", f"/api/admin/sections/{home.id}?move_to=other")
        self.assertIsNone(FieldDef.objects.get(key="home_city").section_id)


class SectionFileTests(ApiTestBase):
    def test_export_round_trip(self):
        self.as_("admin")
        FieldDef.objects.filter(key="internal_contact").update(required=True)  # as in the file
        doc = self.j("get", "/api/admin/fields/export")
        self.assertEqual((doc["version"], doc["sections"][2]), (2, {"key": "communication",
                                                                   "label": {"de": "Kommunikation", "en": "Communication"}}))
        self.assertEqual(next(f for f in doc["fields"] if f["key"] == "mobile")["section"], "communication")
        # into an empty installation: same sections, same order, same file
        FieldDef.objects.all().delete()
        FieldSection.objects.all().delete()
        self.j("post", "/api/admin/fields/import", {"document": doc, "apply": True})
        self.assertEqual(self.j("get", "/api/admin/fields/export"), doc)

    def test_v2_preview_and_apply(self):
        self.as_("admin")
        doc = copy.deepcopy(example("fields-example.json"))
        doc["sections"][0]["label"]["en"] = "Personal"
        doc["sections"].append({"key": "extra", "label": {"de": "Extra", "en": ""}})
        doc["sections"].append({"key": "Bad Key", "label": {"de": "X", "en": "X"}})
        fields = {f["key"]: f for f in doc["fields"]}
        fields["mobile"]["section"] = "extra"
        fields["fax"]["section"] = "nope"
        fields["website"]["section"] = None
        res = self.j("post", "/api/admin/fields/import", {"document": doc})
        sec = {s["key"]: s for s in res["sections"]}
        self.assertEqual((sec["person"]["status"], sec["extra"]["status"], sec["Bad Key"]["status"],
                          sec["notes"]["status"]), ("changed", "new", "invalid", "unchanged"))
        flds = {f["key"]: f for f in res["fields"]}
        self.assertEqual((flds["mobile"]["status"], flds["mobile"]["changes"]), ("changed", ["section"]))
        self.assertEqual(flds["fax"]["errors"], {"section": "invalid"})
        self.assertFalse(FieldSection.objects.filter(key="extra").exists())  # preview only

        self.j("post", "/api/admin/fields/import", {"document": doc, "apply": True})
        extra = FieldSection.objects.get(key="extra")
        self.assertEqual((extra.label_en, FieldSection.objects.last()), ("Extra", extra))
        self.assertEqual(FieldDef.objects.get(key="mobile").section, extra)
        self.assertIsNone(FieldDef.objects.get(key="website").section)
        self.assertEqual(FieldSection.objects.get(key="person").label_en, "Personal")

    def test_v1_finds_or_creates_by_label(self):
        self.as_("admin")
        doc = {"format": "kartei-fields", "version": 1, "fields": [
            {"key": "a1", "label": {"de": "A", "en": "A"}, "section": {"de": "kommunikation", "en": ""}},
            {"key": "a2", "label": {"de": "B", "en": "B"}, "section": {"de": "Bank", "en": "Bank details"}},
            {"key": "a3", "label": {"de": "C", "en": "C"}, "section": {"de": "Bankverbindung", "en": "Bank details"}},
            {"key": "a4", "label": {"de": "D", "en": "D"}, "section": {"de": "", "en": ""}},
        ]}
        res = self.j("post", "/api/admin/fields/import", {"document": doc, "apply": True})
        self.assertEqual([s["key"] for s in res["sections"]], ["bank_details"])
        get = lambda k: FieldDef.objects.get(key=k).section
        self.assertEqual(get("a1").key, "communication")
        self.assertEqual((get("a2").key, get("a2").label_de), ("bank_details", "Bank"))
        self.assertEqual(get("a3"), get("a2"))  # found by its English label
        self.assertIsNone(get("a4"))
        self.j("post", "/api/admin/fields/import", {"document": {**doc, "version": 3}}, status=400)
