import base64
import xml.etree.ElementTree as ET

from django.contrib.auth.hashers import make_password
from django.test import TestCase

from . import phonebook
from .models import AuditEntry, FieldDef, Record, Settings
from .tests import ApiTestBase, sample_records

AUTH = "Basic " + base64.b64encode(b"telefon:geheim-12345").decode()


class PhonebookTests(TestCase):
    def setUp(self):
        phonebook._cache["stamp"] = None
        Settings.get()
        self.person, self.company = sample_records()
        self.koch = Record.objects.create(kind="person", first_name="Jonas", last_name="Koch", company=self.company,
                                          data={"phone_work": "+49 511 1231232-17", "mobile": "+49 160 9997381"})
        self.vienna = Record.objects.create(kind="person", first_name="Lukas", last_name="Berg",
                                            data={"phone_work": "+43 1 234567"})
        Settings.objects.filter(pk=1).update(phonebook_enabled=True, phonebook_password_hash=make_password("geheim-12345"))

    def get(self, url, auth=AUTH, **extra):
        return self.client.get(url, HTTP_AUTHORIZATION=auth, **extra) if auth else self.client.get(url, **extra)

    def test_yealink_snom_grandstream(self):
        y = ET.fromstring(self.get("/phonebook/yealink.xml").content)
        entries = {e.findtext("Name"): [(t.get("label"), t.text) for t in e.findall("Telephone")] for e in y}
        self.assertEqual(entries["Jonas Koch – ACME GmbH"], [("Telefon", "+495111231232-17".replace("-", "")),
                                                             ("Mobil", "+491609997381")])
        meier = entries["Alexander Meier – Muster IT GmbH"]
        self.assertIn(("Mobil", "01701234567"), meier)
        self.assertNotIn("051112345671117", [n for _, n in meier])  # fax is no number to call
        self.assertIn(("Zentrale", "05111231232"), entries["ACME GmbH"])
        snom = ET.fromstring(self.get("/phonebook/snom.xml").content)
        self.assertIn(("Jonas Koch – ACME GmbH (Mobil)", "+491609997381"),
                      [(e.findtext("Name"), e.findtext("Telephone")) for e in snom.findall("DirectoryEntry")])
        gs = ET.fromstring(self.get("/phonebook/grandstream.xml").content)
        koch = next(c for c in gs if c.findtext("LastName") == "Koch")
        self.assertEqual((koch.findtext("FirstName"), koch.findtext("Company")), ("Jonas", "ACME GmbH"))
        self.assertEqual([(p.get("type"), p.findtext("phonenumber")) for p in koch.findall("Phone")],
                         [("Work", "+49511123123217"), ("Cell", "+491609997381")])
        self.assertEqual(self.get("/phonebook/nokia.xml").status_code, 404)
        self.assertEqual(self.get("/phonebook/swyx.xml").status_code, 404)

    def test_swyx(self):
        Record.objects.create(kind="person", first_name="Jonas", last_name="Koch", data={"phone_work": "0511 777"})  # same name
        r = self.get("/phonebook/swyx.csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        text = r.content.decode("utf-8-sig")
        self.assertTrue(r.content.startswith("\ufeff".encode()))
        rows = [line.split('";"') for line in text.strip().split("\r\n")]
        rows = [[c.strip('"') for c in row] for row in rows]
        self.assertIn(["Koch,Jonas (Telefon)", "+49511123123217", "ACME GmbH · Telefon"], rows)
        self.assertIn(["Koch,Jonas (Mobil)", "+491609997381", "ACME GmbH · Mobil"], rows)
        self.assertIn(["Koch,Jonas", "0511777", "Telefon"], rows)  # one number: no label in the name
        self.assertIn(["ACME GmbH", "05111231232", "Zentrale"], rows)
        names = [row[0] for row in rows]
        self.assertEqual(len(names), len(set(names)))  # Swyx needs unique names
        self.assertTrue(all(" " not in row[1] for row in rows))  # no blanks in numbers
        ansi = self.get("/phonebook/swyx.csv?charset=windows-1252")
        self.assertEqual(ansi["Content-Type"], "text/csv; charset=windows-1252")
        self.assertIn("ACME GmbH · Mobil".encode("cp1252"), ansi.content)  # "·" is 0xB7 in Windows-1252


    def test_remote_search(self):
        names = lambda q: [e.findtext("Name") for e in ET.fromstring(self.get(f"/phonebook/yealink.xml?q={q}").content)]
        self.assertEqual(names("koch"), ["Jonas Koch – ACME GmbH"])
        self.assertEqual(set(names("acme")), {"ACME GmbH", "Jonas Koch – ACME GmbH"})
        self.assertEqual(names("9997381"), ["Jonas Koch – ACME GmbH"])  # by number

    def test_lookup(self):
        who = lambda n: self.get(f"/phonebook/lookup?number={n}")
        self.assertEqual(who("+491609997381").content.decode(), "Jonas Koch · ACME GmbH")
        self.assertEqual(who("01609997381").content.decode(), "Jonas Koch · ACME GmbH")
        self.assertEqual(who("00491609997381").content.decode(), "Jonas Koch · ACME GmbH")
        self.assertEqual(who("051112312329").content.decode(), "ACME GmbH")  # unknown extension: the switchboard
        self.assertEqual(who("004312345678").content.decode(), "Lukas Berg")  # abroad, extension unknown
        self.assertEqual(who("+4312345").status_code, 404)  # shorter than any stored number
        self.assertEqual(who("0800").status_code, 404)
        self.assertEqual(self.get("/phonebook/lookup?number=%2B491609997381").content.decode(), "Jonas Koch · ACME GmbH")
        j = self.get("/phonebook/lookup?number=%2B491609997381&format=json").json()
        self.assertEqual((j["name"], j["company"], j["uid"]), ("Jonas Koch", "ACME GmbH", str(self.koch.uid)))
        self.assertEqual(self.get("/phonebook/lookup?number=123&format=json").json(), {"found": False})

    def test_only_what_read_only_users_see(self):
        FieldDef.objects.filter(key="mobile").update(visible_to="maintainer")
        phonebook._cache["at"] = 0
        y = self.get("/phonebook/yealink.xml").content.decode()
        self.assertNotIn("+491609997381", y)
        self.assertEqual(self.get("/phonebook/lookup?number=01609997381").status_code, 404)

    def test_access(self):
        self.assertEqual(self.get("/phonebook/yealink.xml", auth=None).status_code, 401)
        bad = "Basic " + base64.b64encode(b"telefon:falsch").decode()
        self.assertEqual(self.get("/phonebook/yealink.xml", auth=bad).status_code, 401)
        self.assertTrue(AuditEntry.objects.filter(action="auth_failed", changes__channel=[None, "phonebook"]).exists())
        Settings.objects.filter(pk=1).update(phonebook_allowlist=["10.0.5.0/24"])
        self.assertEqual(self.get("/phonebook/yealink.xml").status_code, 403)
        self.assertEqual(self.get("/phonebook/yealink.xml", REMOTE_ADDR="10.0.5.20").status_code, 200)
        Settings.objects.filter(pk=1).update(phonebook_enabled=False)
        self.assertEqual(self.get("/phonebook/yealink.xml", REMOTE_ADDR="10.0.5.20").status_code, 404)
        self.assertEqual(self.client.post("/phonebook/lookup", HTTP_AUTHORIZATION=AUTH).status_code, 405)

    def test_a_change_shows_up(self):
        self.assertEqual(self.get("/phonebook/lookup?number=05119999").status_code, 404)
        Record.objects.create(kind="person", last_name="Neu", data={"phone_work": "0511 9999"})
        self.assertEqual(self.get("/phonebook/lookup?number=05119999").status_code, 404)  # checked once a minute
        phonebook._cache["at"] = 0
        self.assertEqual(self.get("/phonebook/lookup?number=05119999").content.decode(), "Neu")


class PhonebookSettingsTests(ApiTestBase):
    def test_password_shown_once_and_settings(self):
        self.as_("maintainer")
        self.j("post", "/api/admin/phonebook/password", status=403)
        self.as_("admin")
        pw = self.j("post", "/api/admin/phonebook/password")["password"]
        self.assertTrue(self.j("get", "/api/admin/settings")["phonebook_password_set"])
        self.assertNotIn(pw, str(self.j("get", "/api/admin/settings")))
        r = self.j("put", "/api/admin/settings", {"phonebook_enabled": True, "phonebook_allowlist": ["10.0.0.0/8", "kein-netz"]}, status=400)
        self.assertTrue(r["fields"]["phonebook_allowlist"].startswith("invalid_network:kein-netz"))
        self.j("put", "/api/admin/settings", {"phonebook_username": "a:b"}, status=400)
        self.j("put", "/api/admin/settings", {"phonebook_enabled": True, "phonebook_allowlist": ["10.0.0.0/8"]})
        auth = "Basic " + base64.b64encode(f"telefon:{pw}".encode()).decode()
        self.assertEqual(self.client.get("/phonebook/snom.xml", HTTP_AUTHORIZATION=auth, REMOTE_ADDR="10.1.2.3").status_code, 200)
