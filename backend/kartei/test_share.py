from .models import Record, Settings
from .tests import ApiTestBase

PERSON_UID = "5b0c1d2e-0000-4000-8000-000000000001"


class ShareTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        co = Record.objects.create(kind="company", name="Grüne Wiese AG")
        Record.objects.create(uid=PERSON_UID, kind="person", first_name="Jürgen", last_name="Groß", company=co,
                              data={"department": "Einkauf", "phone_work": "+49 511 1000-11"},
                              image=b"\xff\xd8\xff" + b"x" * 50, image_type="jpeg")

    def test_vcard_for_qr_has_no_photo_and_the_chosen_flavour(self):
        self.as_("read")
        full = self.client.get(f"/person/{PERSON_UID}.vcf")
        self.assertIn("attachment", full["Content-Disposition"])
        self.assertIn(b"PHOTO", full.content)
        qr = self.client.get(f"/person/{PERSON_UID}.vcf?qr=1&flavour=android")
        self.assertFalse(qr.has_header("Content-Disposition"))  # inline, read by the share dialog
        self.assertNotIn(b"PHOTO", qr.content)
        self.assertNotIn(b"SOURCE:", qr.content)
        self.assertNotIn(b"UID:", qr.content)
        self.assertTrue(qr.content.startswith(b"BEGIN:VCARD\r\nVERSION:3.0\r\n"))
        ios = self.client.get(f"/person/{PERSON_UID}.vcf?qr=1&flavour=ios").content
        self.assertNotEqual(ios, qr.content)  # iOS and Android cards differ (e.g. ORG with department, X-ABLabel)

    def test_map_url_setting(self):
        self.as_("read")
        self.assertIn("{address}", self.j("get", "/api/bootstrap")["map_url"])  # Google Maps by default
        self.as_("admin")
        r = self.j("put", "/api/admin/settings", {"map_url": "https://maps.example/?q="}, status=400)
        self.assertEqual(r["fields"], {"map_url": "map_url_invalid"})
        self.j("put", "/api/admin/settings", {"map_url": " https://www.openstreetmap.org/search?query={address} "})
        self.assertEqual(Settings.get().map_url, "https://www.openstreetmap.org/search?query={address}")
        self.j("put", "/api/admin/settings", {"map_url": ""})  # no link
        self.as_("read")
        self.assertEqual(self.j("get", "/api/bootstrap")["map_url"], "")
