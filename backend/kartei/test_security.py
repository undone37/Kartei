"""Regression tests for the pre-1.0 security review."""
import io
import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from . import exports, ldapusers, syslog, vcard
from .auth import DbLDAPBackend
from .management.commands import export_loop
from .models import ExportProfile, FieldDef, Profile, Record, SavedFilter, Settings
from .net import client_ip
from .tests import ApiTestBase
from .validation import clean_value


class AccessTests(ApiTestBase):
    def test_django_admin_is_off(self):
        r = self.client.get("/django-admin/login/")  # no Django admin login form (it would skip 2FA and the lockout)
        self.assertNotIn(b"csrfmiddlewaretoken", r.content)
        self.assertNotEqual(self.client.get("/django-admin/").status_code, 302)

    def test_legacy_redirect_stays_on_this_site(self):
        r = self.client.get("/crm//evil.example/x")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r["Location"].startswith("/") and not r["Location"].startswith("//"), r["Location"])

    def test_trashed_contact_history_and_photo_hidden_from_read_only(self):
        rec = Record.objects.create(kind="company", name="Weg GmbH", image=b"\x89PNG", image_type="png")
        Record.objects.filter(pk=rec.pk).update(deleted_at="2026-01-01T00:00:00Z")
        self.as_("read")
        self.j("get", f"/api/records/{rec.uid}/history", status=404)
        self.assertEqual(self.client.get(f"/api/img/{rec.uid}").status_code, 404)
        self.as_("maintainer")
        self.j("get", f"/api/records/{rec.uid}/history")

    def test_shared_filter_hides_fields_the_viewer_cannot_see(self):
        FieldDef.objects.filter(key="customer_no").update(visible_to="admin")
        admin = self.users["admin"]
        SavedFilter.objects.create(owner=admin, name="Großkunden", shared=True, state={
            "filters": {"customer_no": ["K-1"], "keywords": ["Kunde"]},
            "adv": {"mode": "all", "items": [{"field": "customer_no", "op": "eq", "value": "K-1"},
                                             {"field": "@kind", "op": "in", "value": ["company"]}]}})
        self.as_("read")
        st = self.j("get", "/api/bootstrap")["filters"][0]["state"]
        self.assertEqual(st["filters"], {"keywords": ["Kunde"]})
        self.assertEqual([i["field"] for i in st["adv"]["items"]], ["@kind"])

    def test_propagate_preview_only_shows_fields_the_user_may_see(self):
        FieldDef.objects.filter(key="mobile").update(visible_to="admin", editable_by="admin")
        self.as_("maintainer")
        co = self.j("post", "/api/records", {"kind": "company", "name": "X", "data": {"company_phone": "0151 2300"}}, status=201)
        Record.objects.create(kind="person", last_name="P", company_id=Record.objects.get(uid=co["uid"]).id,
                              data={"mobile": "0151 2300 99"})
        items = self.j("post", f"/api/records/{co['uid']}/propagate",
                       {"changes": {"company_phone": ["0151 2300", "0151 9999"]}})["items"]
        self.assertEqual([i for i in items if i["key"] == "mobile"], [])

    def test_bad_input_is_a_400_not_a_crash(self):
        self.as_("admin")
        self.assertEqual(self.client.post("/api/records", "[1]", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get("/api/admin/audit?before=abc").status_code, 200)
        self.assertEqual(self.client.get("/api/changes?since=2026-01-01T00:00:00").status_code, 200)  # naive
        r = self.client.post("/api/admin/users", json.dumps({"username": "x", "password": 1234567890, "role": "read"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_numbers_cannot_be_made_huge(self):
        f = FieldDef(key="n", type="integer")
        for v in ("1e999999999", "9" * 41):
            with self.assertRaises(ValueError):
                clean_value(f, v)
        self.assertEqual(clean_value(f, "1000"), 1000)

    def test_text_loses_control_characters(self):
        f = FieldDef(key="t", type="longtext")
        self.assertEqual(clean_value(f, "a\x01b\rc"), "ab\nc")


class ProxyTests(ApiTestBase):
    def ip(self, remote, fwd):
        return client_ip(RequestFactory().get("/", REMOTE_ADDR=remote, HTTP_X_FORWARDED_FOR=fwd))

    def test_forwarded_for_only_from_a_trusted_proxy(self):
        self.assertEqual(self.ip("172.18.0.1", "203.0.113.9"), "203.0.113.9")  # the proxy (Docker network)
        self.assertEqual(self.ip("10.0.5.31", "1.2.3.4"), "10.0.5.31")  # a client talking to Kartei directly
        with override_settings(TRUSTED_PROXIES=["10.0.5.0/24"]):
            self.assertEqual(self.ip("10.0.5.31", "1.2.3.4"), "1.2.3.4")

    def test_failed_sign_ins_are_counted_across_attempts(self):
        cache.clear()
        for _ in range(10):
            self.client.post("/api/login", json.dumps({"username": "read", "password": "x"}),
                             content_type="application/json", REMOTE_ADDR="10.9.9.9", HTTP_X_FORWARDED_FOR="1.1.1.1")
        r = self.client.post("/api/login", json.dumps({"username": "read", "password": "pw-readreadread"}),
                             content_type="application/json", REMOTE_ADDR="10.9.9.9", HTTP_X_FORWARDED_FOR="2.2.2.2")
        self.assertEqual(r.status_code, 429)  # a new X-Forwarded-For per try doesn't help


class LdapTakeoverTests(ApiTestBase):
    def test_directory_user_cannot_take_over_a_local_account_without_profile(self):
        boss = User.objects.create_superuser("boss", "", "pw-bossbossboss")
        backend = DbLDAPBackend()
        with mock.patch("django_auth_ldap.backend.LDAPBackend.get_or_build_user", return_value=(boss, False)):
            with self.assertRaises(Exception):
                backend.get_or_build_user("boss", mock.Mock(attrs={}))
        plain = User.objects.create_user("plain")  # local, no profile yet
        with mock.patch("django_auth_ldap.backend.LDAPBackend.get_or_build_user", return_value=(plain, False)):
            with self.assertRaises(Exception):
                backend.get_or_build_user("plain", mock.Mock(attrs={}))
        ldap_user = User.objects.create_user("dir")
        Profile.objects.create(user=ldap_user, source="ldap")
        with mock.patch("django_auth_ldap.backend.LDAPBackend.get_or_build_user", return_value=(ldap_user, False)):
            self.assertEqual(backend.get_or_build_user("dir", mock.Mock(attrs={}))[0], ldap_user)

    def test_user_import_stops_before_deactivating_too_many(self):
        for i in range(10):
            u = User.objects.create_user(f"d{i}")
            Profile.objects.create(user=u, source="ldap", role="read")
        found = {f"d{i}": ("read", {}) for i in range(5)}  # half the directory users "gone"
        with self.assertRaises(ldapusers.LdapError):
            ldapusers.apply(found, limit=20)
        self.assertEqual(User.objects.filter(username__startswith="d", is_active=True).count(), 10)
        self.assertEqual(ldapusers.apply(found, limit=60)["deactivated"], 5)


class ExportTests(ApiTestBase):
    def test_formulas_are_neutralised(self):
        from openpyxl import load_workbook
        from .models import default_csv_options, default_xlsx_options
        x = exports.render_xlsx(["a"], [['=HYPERLINK("http://x")'], ["ok\x01"]], default_xlsx_options())
        cells = [c for c in load_workbook(io.BytesIO(x)).active["A"]][1:]
        self.assertEqual([(c.value, c.data_type) for c in cells], [('=HYPERLINK("http://x")', "s"), ("ok", "s")])
        csv_ = exports.render_csv(["a"], [["=1+1"], ["+49 511 1"], ["-12,5"], ["@SUM(A1)"]], default_csv_options()).decode("utf-8-sig")
        self.assertEqual(csv_.split("\r\n")[1:5], ["'=1+1", "+49 511 1", "-12,5", "'@SUM(A1)"])
        raw = exports.render_csv(["a"], [["=1+1"]], {**default_csv_options(), "escape_formulas": False}).decode("utf-8-sig")
        self.assertIn("\r\n=1+1", raw)

    def test_one_failing_step_does_not_stop_the_others(self):
        ExportProfile.objects.create(name="Kaputt", path="/export/x.csv")
        ran = []
        with mock.patch.object(exports, "validate_profile", return_value={}), \
                mock.patch.object(exports, "build_rows", side_effect=RuntimeError("boom")), \
                mock.patch.object(export_loop, "STEPS", export_loop.STEPS[:1] + [("probe", lambda s: ran.append(1))]):
            export_loop.tick()
        self.assertEqual(ran, [1])
        p = ExportProfile.objects.get(name="Kaputt")
        self.assertEqual(p.last_status, "error")
        self.assertIn("boom", p.last_message)


class FormatTests(ApiTestBase):
    def test_vcard_values_cannot_start_new_lines(self):
        self.assertEqual(vcard.esc("a\rTEL:1"), "a\\nTEL:1")
        rec = Record(kind="person", first_name="A", last_name="B\rEND:VCARD", data={})
        card = vcard.render(rec, [], "android")
        self.assertEqual([line for line in card.split("\r\n") if line.startswith(("END:", "BEGIN:", "TEL"))],
                         ["BEGIN:VCARD", "END:VCARD"])

    def test_oversized_syslog_event_is_shortened_for_udp(self):
        rec = {"ts": "t", "level": "INFO", "logger": syslog.AUDIT, "msg": "update settings",
               "audit": {"event": "update", "changes": {"mail_templates": ["x" * 20000, "y" * 20000]}}}
        data = syslog.line(rec, "local0", syslog.UDP_MAX)
        self.assertLessEqual(len(data), syslog.UDP_MAX)
        body = json.loads(data.decode().split(" - ", 1)[1])
        self.assertEqual((body["truncated"], body["audit"]["changes"]), (True, ["mail_templates"]))

    def test_import_skips_rows_of_trashed_contacts(self):
        from .importer import import_csv
        r = Record.objects.create(kind="person", last_name="Alt", legacy_id="P-1")
        Record.objects.filter(pk=r.pk).update(deleted_at="2026-01-01T00:00:00Z")
        res = import_csv("ID;Nachname\nP-1;Neu\n".encode(), dry_run=False)
        self.assertEqual((res["persons_updated"], res["persons_created"], res.get("trashed_skipped")), (0, 0, 1))
        self.assertEqual(Record.objects.get(pk=r.pk).last_name, "Alt")


class EdgeCaseTests(ApiTestBase):
    def test_reset_2fa_command(self):
        from io import StringIO
        from django.core.management import call_command
        p = self.users["admin"].profile
        p.totp_secret, p.totp_recovery = "JBSWY3DPEHPK3PXP", ["x"]
        p.save()
        out = StringIO()
        call_command("reset_2fa", "ADMIN", stdout=out)
        p.refresh_from_db()
        self.assertEqual((p.totp_secret_enc, p.totp_recovery), ("", []))
        self.assertIn("switched off", out.getvalue())

    def test_same_wrong_carddav_login_counts_once(self):
        from django.contrib.auth.hashers import make_password
        import base64
        cache.clear()
        s = Settings.get()
        s.carddav_enabled, s.carddav_username, s.carddav_password_hash = True, "phone", make_password("right")
        s.save()
        basic = lambda pw: "Basic " + base64.b64encode(f"phone:{pw}".encode()).decode()
        for _ in range(30):  # an old phone retrying all day, behind the office's address
            self.client.generic("PROPFIND", "/carddav/kontakte/", HTTP_AUTHORIZATION=basic("old"), HTTP_DEPTH="0")
        ok = self.client.generic("PROPFIND", "/carddav/kontakte/", HTTP_AUTHORIZATION=basic("right"), HTTP_DEPTH="0")
        self.assertEqual(ok.status_code, 207)  # the other phones still work
        for i in range(20):  # guessing: every attempt is different and counts
            self.client.generic("PROPFIND", "/carddav/kontakte/", HTTP_AUTHORIZATION=basic(f"guess{i}"), HTTP_DEPTH="0")
        locked = self.client.generic("PROPFIND", "/carddav/kontakte/", HTTP_AUTHORIZATION=basic("right"), HTTP_DEPTH="0")
        self.assertEqual(locked.status_code, 401)

    def test_export_reports_characters_the_encoding_cant_hold(self):
        from .models import default_csv_options
        o = {**default_csv_options(), "encoding": "cp1252"}
        self.assertEqual(exports.lossy_values(["Name"], [["Müller"], ["Łukasz"], ["Çelik Ş."]], o), 2)
        self.assertEqual(exports.lossy_values(["Name"], [["Łukasz"]], default_csv_options()), 0)  # UTF-8 holds all
