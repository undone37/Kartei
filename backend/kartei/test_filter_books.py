"""Saved filters published as Outlook folders and CardDAV address books."""
import base64
import re
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.test import TestCase

from . import carddav, graph
from .models import FieldDef, Profile, Record, SavedFilter, Settings
from .tests import ApiTestBase, FakeGraph, sample_records


class FilterFolderTests(TestCase):
    def setUp(self):
        self.person, self.company = sample_records()
        s = Settings.get()
        s.graph_enabled, s.graph_tenant_id, s.graph_client_id, s.graph_group_id = True, "t", "c", "g"
        s.graph_client_secret = "secret"
        s.save()
        self.fake = FakeGraph({"u1": "a@x.de", "u2": "b@x.de"})
        patcher = mock.patch.object(graph, "http", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        FieldDef.objects.create(key="owner", label_de="Zuständig", label_en="Owner", type="user", applies_to="both")
        self.anna = User.objects.create(username="anna", email="A@x.de")  # mailbox u1
        self.b = User.objects.create(username="b")  # mailbox u2 by the local part
        Profile.objects.create(user=self.anna, role="maintainer")
        Profile.objects.create(user=self.b, role="read")
        Record.objects.filter(pk=self.person.pk).update(data={**self.person.data, "owner": "anna"})
        Record.objects.filter(pk=self.company.pk).update(data={**self.company.data, "owner": "b"})

    def folder(self, user, name):
        found = [d for (u, _), d in self.fake.folders.items() if u == user and d["name"] == name]
        return sorted(c["displayName"] for d in found for c in d["contacts"].values()) if found else None

    def test_each_owner_gets_the_filter_with_their_own_contacts(self):
        mine = SavedFilter.objects.create(owner=self.anna, name="Meine Kontakte", shared=True, outlook_folder=True,
                                          state={"q": "", "scope": "responsible", "kind": "all", "filters": {}})
        private = SavedFilter.objects.create(owner=self.anna, name="Nur Anna", outlook_folder=True,
                                             state={"q": "meier", "scope": "all", "kind": "all", "filters": {}})
        self.assertEqual(graph.run()["failed"], [])
        self.assertEqual(self.folder("u1", "Meine Kontakte"), ["Alexander Meier"])
        self.assertEqual(self.folder("u2", "Meine Kontakte"), ["ACME GmbH"])  # the same filter, b's own contacts
        self.assertEqual(self.folder("u1", "Nur Anna"), ["Alexander Meier"])
        self.assertIsNone(self.folder("u2", "Nur Anna"))  # not shared with b
        self.assertEqual(Settings.get().graph_filter_folders, {"u1": ["Meine Kontakte", "Nur Anna"], "u2": ["Meine Kontakte"]})
        private.outlook_folder = False
        private.save()
        mine.shared = False  # b no longer sees it
        mine.save()
        graph.run()
        self.assertIsNone(self.folder("u1", "Nur Anna"))  # unpublished: removed
        self.assertIsNone(self.folder("u2", "Meine Kontakte"))  # no longer visible: removed
        self.assertEqual(self.folder("u1", "Meine Kontakte"), ["Alexander Meier"])
        self.assertIsNotNone(self.folder("u1", "Kartei"))  # the main folder is never touched

    def test_a_filter_cannot_take_over_the_main_folder(self):
        SavedFilter.objects.create(owner=self.anna, name="Kartei", outlook_folder=True,
                                   state={"q": "meier", "scope": "all", "kind": "all", "filters": {}})
        graph.run()
        self.assertEqual(len(self.folder("u1", "Kartei")), Record.objects.count())  # still everything

    def test_hidden_fields_dont_count_for_read_only_owners(self):
        FieldDef.objects.filter(key="description").update(visible_to="maintainer")
        SavedFilter.objects.create(owner=self.anna, name="Kaffee", shared=True, outlook_folder=True,
                                   state={"q": "", "scope": "all", "kind": "all", "filters": {},
                                          "adv": {"mode": "all", "items": [{"field": "description", "op": "contains", "value": "kaffe"}]}})
        graph.run()
        self.assertEqual(self.folder("u1", "Kaffee"), ["Alexander Meier"])
        self.assertEqual(len(self.folder("u2", "Kaffee")), Record.objects.count())  # b can't see the field: dropped


class FilterBookTests(TestCase):
    def setUp(self):
        carddav._members.update(stamp=None, at=0.0, sets={}, view=None)
        self.person, self.company = sample_records()
        s = Settings.get()
        s.carddav_enabled, s.carddav_password_hash = True, make_password("phone-secret")
        s.save()
        self.auth = "Basic " + base64.b64encode(b"carddav:phone-secret").decode()
        owner = User.objects.create(username="m")
        Profile.objects.create(user=owner, role="maintainer")
        self.f = SavedFilter.objects.create(owner=owner, name="Firmen", shared=True, carddav_book=True,
                                            state={"q": "", "scope": "all", "kind": "company", "filters": {}})

    def dav(self, method, path, body="", **headers):
        return self.client.generic(method, path, body, content_type="application/xml", HTTP_AUTHORIZATION=self.auth, **headers)

    def test_book_lists_and_serves_only_its_contacts(self):
        root = self.dav("PROPFIND", "/carddav/", HTTP_DEPTH="1").content.decode()
        self.assertIn(f"/carddav/f-{self.f.id}/", root)
        self.assertIn("Firmen", root)
        book = self.dav("PROPFIND", f"/carddav/f-{self.f.id}/", HTTP_DEPTH="1").content.decode()
        companies = {str(u) for u in Record.objects.filter(kind="company").values_list("uid", flat=True)}
        self.assertEqual(set(re.findall(r"/carddav/f-\d+/([0-9a-f-]{36})\.vcf", book)), companies)
        self.assertEqual(self.dav("GET", f"/carddav/f-{self.f.id}/{self.person.uid}.vcf").status_code, 404)
        self.assertEqual(self.dav("GET", f"/carddav/f-{self.f.id}/{self.company.uid}.vcf").status_code, 200)
        self.assertEqual(self.dav("PROPFIND", "/carddav/f-999/", HTTP_DEPTH="0").status_code, 404)

    def test_membership_change_restarts_the_sync(self):
        body = ('<d:sync-collection xmlns:d="DAV:"><d:sync-token></d:sync-token><d:sync-level>1</d:sync-level>'
                '<d:prop><d:getetag/></d:prop></d:sync-collection>')
        r = self.dav("REPORT", f"/carddav/f-{self.f.id}/", body)
        token = re.findall(r"<d:sync-token>([^<]+)</d:sync-token>", r.content.decode())[-1]
        Record.objects.create(kind="company", name="Neue AG")
        carddav._members["at"] = 0.0
        again = body.replace("<d:sync-token></d:sync-token>", f"<d:sync-token>{token}</d:sync-token>")
        self.assertEqual(self.dav("REPORT", f"/carddav/f-{self.f.id}/", again).status_code, 403)  # start over

    def test_unshared_or_restricted_filters_are_no_books(self):
        self.f.shared = False
        self.f.save()
        self.assertEqual(self.dav("PROPFIND", f"/carddav/f-{self.f.id}/", HTTP_DEPTH="0").status_code, 404)
        self.f.shared = True
        self.f.state = {**self.f.state, "filters": {"description": ["x"]}}
        self.f.save()
        FieldDef.objects.filter(key="description").update(visible_to="maintainer")  # restricted after publishing
        self.assertNotIn(f"f-{self.f.id}", self.dav("PROPFIND", "/carddav/", HTTP_DEPTH="1").content.decode())


class PublishRuleTests(ApiTestBase):
    def create(self, status=201, **extra):
        body = {"name": "Kunden", "state": {"q": "", "scope": "all", "kind": "all", "filters": {}}, **extra}
        return self.j("post", "/api/filters", body, status=status)

    def test_rules(self):
        self.as_("read")
        self.assertEqual(self.create(status=400, outlook_folder=True)["fields"]["outlook_folder"], "forbidden")
        self.as_("maintainer")
        f = self.create(outlook_folder=True)
        self.assertEqual((f["outlook_folder"], f["carddav_book"]), (True, False))
        self.assertEqual(self.create(status=400, carddav_book=True)["fields"]["carddav_book"], "carddav_book_shared")
        self.assertEqual(self.create(status=400, carddav_book=True, share=["all"],
                                     state={"q": "", "scope": "responsible", "kind": "all", "filters": {}})["fields"]["carddav_book"],
                         "publish_scope")
        FieldDef.objects.filter(key="description").update(visible_to="maintainer")
        self.assertEqual(self.create(status=400, carddav_book=True, share=["all"],
                                     state={"q": "", "scope": "all", "kind": "all", "filters": {"description": ["x"]}})["fields"]["carddav_book"],
                         "carddav_book_fields")
        self.assertEqual(self.create(status=400, outlook_folder=True,
                                     state={"q": "", "scope": "review", "kind": "all", "filters": {}})["fields"]["outlook_folder"],
                         "publish_scope")
        for i in range(9):
            self.create(name=f"F{i}", outlook_folder=True)
        self.assertEqual(self.create(status=400, outlook_folder=True)["fields"]["outlook_folder"], "publish_limit")
        self.create()  # unpublished filters are not limited
