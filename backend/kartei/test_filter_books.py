"""Saved filters published as Outlook folders and CardDAV address books."""
import base64
import re
import xml.etree.ElementTree as ET
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.test import TestCase

from . import carddav, graph, relaypush
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
        self.assertEqual(self.folder("u1", "Kartei: Meine Kontakte"), ["Alexander Meier"])
        self.assertEqual(self.folder("u2", "Kartei: Meine Kontakte"), ["ACME GmbH"])  # the same filter, b's own contacts
        self.assertEqual(self.folder("u1", "Kartei: Nur Anna"), ["Alexander Meier"])
        self.assertIsNone(self.folder("u2", "Kartei: Nur Anna"))  # not shared with b
        self.assertEqual({u: sorted(v) for u, v in Settings.get().graph_filter_folders.items()},
                         {"u1": ["Kartei: Meine Kontakte", "Kartei: Nur Anna"], "u2": ["Kartei: Meine Kontakte"]})
        private.outlook_folder = False
        private.save()
        mine.shared = False  # b no longer sees it
        mine.save()
        graph.run()
        self.assertIsNone(self.folder("u1", "Kartei: Nur Anna"))  # unpublished: removed
        self.assertIsNone(self.folder("u2", "Kartei: Meine Kontakte"))  # no longer visible: removed
        self.assertEqual(self.folder("u1", "Kartei: Meine Kontakte"), ["Alexander Meier"])
        self.assertIsNotNone(self.folder("u1", "Kartei"))  # the main folder is never touched

    def test_a_filter_cannot_take_over_the_main_folder(self):
        Settings.objects.filter(pk=1).update(graph_filter_prefix="")
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
        self.assertEqual(self.folder("u1", "Kartei: Kaffee"), ["Alexander Meier"])
        self.assertEqual(len(self.folder("u2", "Kartei: Kaffee")), Record.objects.count())  # b can't see the field: dropped

    def own_folder(self, user, name, contact):
        """A folder the mailbox owner made themselves, with one private contact."""
        fid = self.fake._id()
        self.fake.folders[(user, fid)] = {"name": name, "contacts": {self.fake._id(): {"displayName": contact}}}

    def test_a_users_own_folder_of_the_same_name_is_never_touched(self):
        Settings.objects.filter(pk=1).update(graph_filter_prefix="")  # even without the prefix
        self.own_folder("u1", "Privat", "Bruder")
        self.own_folder("u2", "Privat", "Partnerin")
        f = SavedFilter.objects.create(owner=self.anna, name="Privat", shared=True, outlook_folder=True,
                                       state={"q": "", "scope": "all", "kind": "all", "filters": {}})
        failed = graph.run()["failed"]
        self.assertEqual(self.folder("u1", "Privat"), ["Bruder"])
        self.assertEqual(self.folder("u2", "Privat"), ["Partnerin"])
        self.assertEqual(len(failed), 2)
        self.assertTrue(all(x.startswith("@graph_folder_taken ") for x in failed))
        self.assertEqual(Settings.get().graph_filter_folders, {})
        f.outlook_folder = False
        f.save()
        graph.run()
        self.assertEqual(self.folder("u1", "Privat"), ["Bruder"])  # unpublishing doesn't delete it either
        self.assertEqual(self.folder("u2", "Privat"), ["Partnerin"])

    def test_folders_named_by_0_8_4_are_taken_over_and_renamed_with_the_prefix(self):
        Settings.objects.filter(pk=1).update(graph_filter_prefix="")
        SavedFilter.objects.create(owner=self.anna, name="Nur Anna", outlook_folder=True,
                                   state={"q": "meier", "scope": "all", "kind": "all", "filters": {}})
        graph.run()
        old = Settings.get().graph_filter_folders
        Settings.objects.filter(pk=1).update(graph_filter_prefix="Kartei: ",
                                             graph_filter_folders={u: list(v) for u, v in old.items()})  # old format
        self.assertEqual(graph.run()["failed"], [])
        self.assertIsNone(self.folder("u1", "Nur Anna"))
        self.assertEqual(self.folder("u1", "Kartei: Nur Anna"), ["Alexander Meier"])
        self.assertEqual(list(Settings.get().graph_filter_folders["u1"]), ["Kartei: Nur Anna"])

    def test_a_filter_folder_deleted_in_outlook_comes_back(self):
        SavedFilter.objects.create(owner=self.anna, name="Nur Anna", outlook_folder=True,
                                   state={"q": "meier", "scope": "all", "kind": "all", "filters": {}})
        graph.run()
        fid = Settings.get().graph_filter_folders["u1"]["Kartei: Nur Anna"]
        del self.fake.folders[("u1", fid)]
        graph.run()  # notices it's gone
        self.assertEqual(graph.run()["failed"], [])
        self.assertEqual(self.folder("u1", "Kartei: Nur Anna"), ["Alexander Meier"])


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
        self.assertNotIn(f"<d:href>/carddav/f-{self.f.id}/</d:href>", self.dav("PROPFIND", "/carddav/", HTTP_DEPTH="1").content.decode())


class BrokenFilterTests(FilterBookTests):
    """Audit run 2 K-10/K-11: one maintainer filter must not break discovery, the relay push or the Outlook sync."""

    def root(self):
        r = self.dav("PROPFIND", "/carddav/", HTTP_DEPTH="1")
        self.assertEqual(r.status_code, 207)
        return ET.fromstring(r.content)  # well-formed

    def test_xml_illegal_characters_in_a_book_name(self):
        SavedFilter.objects.filter(pk=self.f.pk).update(name="Fir\x01men\ufffe")  # saved before the input check
        self.assertIn("Firmen", ET.tostring(self.root(), encoding="unicode"))

    def test_a_huge_day_count_is_ignored(self):
        self.f.state = {**self.f.state, "adv": {"mode": "all", "items": [
            {"field": "@updated_at", "op": "last", "value": str(10 ** 12)}]}}
        self.f.save()
        self.root()
        self.assertTrue(carddav.members(self.f))  # condition ignored, like an empty one
        self.assertIsNotNone(relaypush._books({str(self.company.uid): None}, {}))

    def test_a_filter_that_fails_is_skipped(self):
        with mock.patch("kartei.filters.match", side_effect=OverflowError), self.assertLogs("kartei.carddav", "ERROR"):
            self.root()
            self.assertEqual(carddav.members(self.f), set())

    def test_an_overlong_sync_token_is_invalid_not_an_error(self):
        body = ('<d:sync-collection xmlns:d="DAV:"><d:sync-token>urn:kartei:sync:9999999999999999999999:x</d:sync-token>'
                '<d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>')
        self.assertEqual(self.dav("REPORT", f"/carddav/f-{self.f.id}/", body).status_code, 403)


class PublishRuleTests(ApiTestBase):
    def create(self, status=201, **extra):
        body = {"name": "Kunden", "state": {"q": "", "scope": "all", "kind": "all", "filters": {}}, **extra}
        return self.j("post", "/api/filters", body, status=status)

    def test_size_and_name_limits(self):
        self.as_("maintainer")
        leaf = {"field": "description", "op": "contains", "value": "x"}
        big = {"mode": "any", "items": [{"mode": "any", "items": [leaf] * 50} for _ in range(11)]}  # 550 conditions
        state = {"q": "", "scope": "all", "kind": "all", "filters": {}}
        self.assertEqual(self.create(status=400, state=state | {"adv": big})["fields"]["state"], "invalid")
        big["items"] = big["items"][:10]  # 500: fine
        self.create(state=state | {"adv": big})
        self.assertEqual(self.create(name="Kun\x01den\ufffe 2")["name"], "Kunden 2")

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
