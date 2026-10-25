from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.utils import timezone

from . import reviews
from .models import ApiToken, AuditEntry, FieldDef, Profile, Proposal, Record, Review, Settings
from .tests import ApiTestBase


def locmem():
    return mock.patch("kartei.reviews.mail_connection", lambda s: mail.get_connection())


class NotifyBase(ApiTestBase):
    def setUp(self):
        super().setUp()
        Settings.objects.update(smtp_host="smtp.example", smtp_from="kartei@example.com", base_url="https://kartei.example/")
        User.objects.filter(username="read").update(email="read@example.com", first_name="Rita")
        self.as_("maintainer")
        self.co = self.j("post", "/api/records", {"kind": "company", "name": "Alt GmbH",
                                                  "data": {"internal_contact": "read"}}, status=201)
        self.p = self.j("post", "/api/records", {"kind": "person", "last_name": "Meier", "company": self.co["uid"],
                                                 "data": {"internal_contact": "read"}}, status=201)


class ReminderTests(NotifyBase):
    def test_remind_after_n_days_once_per_period(self):
        self.as_("admin")
        self.j("post", "/api/admin/reviews", {"scope": "all"})
        with locmem():
            self.assertEqual(reviews.tick()[1], 1)  # first digest; reminders are off (0)
            Review.objects.update(notified_at=timezone.now() - timedelta(days=30))
            self.assertEqual(reviews.tick()[1], 0)
            Settings.objects.update(review_remind_days=7)
            # one review is done in between: only the still open one is listed
            self.as_("read")
            self.j("post", f"/api/records/{self.co['uid']}/review/confirm")
            self.assertEqual(reviews.tick()[1], 1)
            self.assertEqual(reviews.tick()[1], 0)  # not again within 7 days
            Review.objects.update(notified_at=timezone.now() - timedelta(days=7, minutes=1))
            self.assertEqual(reviews.tick()[1], 1)
        first, reminder = mail.outbox[0], mail.outbox[1]
        self.assertIn("Erinnerung", reminder.subject)
        self.assertIn("Meier: https://kartei.example/person/", reminder.body)
        self.assertNotIn("Alt GmbH", reminder.body)
        self.assertIn("https://kartei.example/?list=review", reminder.body)
        self.assertNotIn("Erinnerung", first.subject)
        self.assertEqual(Review.objects.get(record__uid=self.p["uid"]).reminders, 2)
        self.as_("admin")
        self.assertEqual(self.j("get", "/api/admin/reviews")["reminded"], 1)

    def test_reminder_in_user_language_and_setting_validation(self):
        Profile.objects.filter(user__username="read").update(language="en")
        reviews.start(Record.objects.all(), "manual")
        Review.objects.update(notified_at=timezone.now() - timedelta(days=3))
        Settings.objects.update(review_remind_days=3)
        with locmem():
            self.assertEqual(reviews.remind(Settings.get()), 1)
        self.assertIn("reminder", mail.outbox[0].subject)
        self.as_("admin")
        bad = self.j("put", "/api/admin/settings", {"review_remind_days": -1}, status=400)
        self.assertEqual(bad["fields"], {"review_remind_days": "invalid_number"})


class ProposalNotifyTests(NotifyBase):
    def setUp(self):
        super().setUp()
        User.objects.filter(username="maintainer").update(email="m@example.com")
        User.objects.filter(username="admin").update(email="a@example.com")
        Profile.objects.filter(user__username="admin").update(language="en")
        User.objects.create_user("gone", email="gone@example.com", is_active=False)  # inactive: no mail

    def propose(self):
        self.as_("read")
        return self.j("post", f"/api/records/{self.p['uid']}/proposals",
                      {"kind": "change", "last_name": "Meyer", "comment": "Tippfehler"}, status=201)["proposal"]

    def test_digest_to_maintainers_once_and_after_edit(self):
        prop = self.propose()
        with locmem():
            self.assertEqual(reviews.notify_proposals(Settings.get()), 0)  # off by default
            Settings.objects.update(proposal_notify=True)
            self.assertEqual(reviews.notify_proposals(Settings.get()), 2)
            self.assertEqual(reviews.notify_proposals(Settings.get()), 0)  # mailed once
            self.j("patch", f"/api/proposals/{prop['id']}", {"kind": "change", "last_name": "Mayer"})
            self.assertEqual(reviews.notify_proposals(Settings.get()), 2)  # edited: again
            self.j("delete", f"/api/proposals/{prop['id']}")
            Proposal.objects.update(notified_at=None)
            self.assertEqual(reviews.notify_proposals(Settings.get()), 0)  # withdrawn ones are not mailed
        self.assertEqual(sorted(m.to[0] for m in mail.outbox[:2]), ["a@example.com", "m@example.com"])
        de = next(m for m in mail.outbox[:2] if m.to == ["m@example.com"])
        en = next(m for m in mail.outbox[:2] if m.to == ["a@example.com"])
        self.assertIn("Meier: Änderung, von read", de.body)
        self.assertIn(f"https://kartei.example/person/{self.p['uid']}", de.body)
        self.assertIn('"Tippfehler"', de.body)
        self.assertIn("https://kartei.example/?list=proposals", de.body)
        self.assertIn("Change, by read", en.body)
        self.assertIn("(bearbeitet)", next(m for m in mail.outbox[2:] if m.to == ["m@example.com"]).body)

    def test_new_contact_proposal_mail(self):
        Settings.objects.update(proposal_notify=True)
        self.as_("read")
        p = self.j("post", "/api/proposals", {"kind": "company", "name": "Neu AG", "data": {"internal_contact": "read"}},
                   status=201)["proposal"]
        with locmem():
            self.assertEqual(reviews.notify_proposals(Settings.get()), 2)
        de = next(m for m in mail.outbox if m.to == ["m@example.com"])
        self.assertIn("Neu AG: neue Firma, von read", de.body)
        self.assertIn(f"https://kartei.example/proposal/{p['id']}", de.body)

    def test_fixed_recipients_and_delete_reason(self):
        Settings.objects.update(proposal_notify=True, proposal_notify_to="team@example.com, chef@example.com")
        self.as_("read")
        self.j("post", f"/api/records/{self.p['uid']}/proposals", {"kind": "delete", "reason": "left"}, status=201)
        with locmem():
            self.assertEqual(reviews.tick()[1], 2)
        tos = [m.to for m in mail.outbox]
        self.assertIn(["team@example.com"], tos)
        body = next(m for m in mail.outbox if m.to == ["chef@example.com"]).body
        self.assertIn("Löschung (hat das Unternehmen verlassen)", body)
        self.as_("admin")
        bad = self.j("put", "/api/admin/settings", {"proposal_notify_to": "a@b.de, kaputt"}, status=400)
        self.assertEqual(bad["fields"], {"proposal_notify_to": "invalid_email"})
        ok = self.j("put", "/api/admin/settings", {"proposal_notify_to": " x@example.com ", "proposal_notify": False})
        self.assertEqual((ok["proposal_notify_to"], ok["proposal_notify"]), ("x@example.com", False))


class TokenApiTests(NotifyBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.as_("admin")
        self.tok = self.j("post", "/api/admin/tokens", {"name": "Telefonanlage"}, status=201)
        self.client.logout()

    def bearer(self, url, token=None, status=200, method="get"):
        resp = getattr(self.client, method)(url, HTTP_AUTHORIZATION=f"Bearer {token or self.tok['token']}")
        self.assertEqual(resp.status_code, status, resp.content[:300])
        return resp.json()

    def test_admin_lifecycle_and_audit(self):
        self.assertTrue(self.tok["token"].startswith("kt_"))
        t = ApiToken.objects.get()
        self.assertNotEqual(t.token_hash, self.tok["token"])
        self.as_("maintainer")
        self.j("get", "/api/admin/tokens", status=403)
        self.as_("admin")
        listed = self.j("get", "/api/admin/tokens")["tokens"]
        self.assertEqual([(x["name"], x["created_by"], x["last_used_at"]) for x in listed], [("Telefonanlage", "admin", None)])
        self.assertNotIn("token", listed[0])
        self.j("delete", f"/api/admin/tokens/{t.id}")
        self.bearer("/api/v1/contacts", status=401)
        logged = AuditEntry.objects.filter(target_type="token").values_list("action", "changes")
        self.assertEqual(sorted(a for a, _ in logged), ["create", "delete"])
        self.assertNotIn(self.tok["token"], str(list(logged)))
        self.assertNotIn(t.token_hash, str(list(logged)))

    def test_contacts_full_single_and_delta(self):
        FieldDef.objects.filter(key="email").update(visible_to="maintainer")
        self.as_("maintainer")
        self.j("patch", f"/api/records/{self.p['uid']}", {"version": 1, "data": {"email": "m@alt.de", "department": "IT"}})
        self.client.logout()
        full = self.bearer("/api/v1/contacts")
        self.assertTrue(full["full"])
        person = next(c for c in full["contacts"] if c["uid"] == self.p["uid"])
        self.assertEqual((person["company"], person["company_name"], person["display_name"]),
                         (self.co["uid"], "Alt GmbH", "Meier"))
        self.assertEqual(person["data"].get("department"), "IT")
        self.assertNotIn("email", person["data"])  # only fields Read Only users see
        self.assertNotIn("image", person)
        one = self.bearer(f"/api/v1/contacts/{self.p['uid']}")
        self.assertEqual(one, person)
        # delta: renamed company also brings its persons, deleted ones come as uids
        cursor = full["cursor"]
        Record.objects.update(updated_at=timezone.now() - timedelta(hours=1))
        later = (timezone.now() - timedelta(minutes=1)).isoformat()
        self.assertEqual(self.bearer(f"/api/v1/contacts?updated_since={later.replace('+', '%2B')}")["contacts"], [])
        self.as_("maintainer")
        self.j("patch", f"/api/records/{self.co['uid']}", {"version": 1, "name": "Neu GmbH"})
        other = self.j("post", "/api/records", {"kind": "person", "last_name": "Weg"}, status=201)
        self.j("delete", f"/api/records/{other['uid']}")
        self.client.logout()
        delta = self.bearer(f"/api/v1/contacts?updated_since={later}")  # unencoded "+" is accepted too
        self.assertEqual({c["uid"] for c in delta["contacts"]}, {self.co["uid"], self.p["uid"]})
        self.assertEqual(next(c for c in delta["contacts"] if c["uid"] == self.p["uid"])["company_name"], "Neu GmbH")
        self.assertEqual(delta["deleted"], [other["uid"]])
        self.assertNotIn("full", delta)
        self.assertTrue(cursor)
        self.bearer(f"/api/v1/contacts/{other['uid']}", status=404)
        self.bearer("/api/v1/contacts?updated_since=gestern", status=400)
        Settings.objects.update(trash_days=30)
        old = (timezone.now() - timedelta(days=31)).isoformat().replace("+", "%2B")
        self.assertTrue(self.bearer(f"/api/v1/contacts?updated_since={old}")["full"])

    def test_auth_read_only_and_rate_limit(self):
        self.bearer("/api/v1/contacts")
        t = ApiToken.objects.get()
        self.assertIsNotNone(t.last_used_at)
        ApiToken.objects.update(last_used_at=timezone.now() - timedelta(seconds=30))
        self.bearer("/api/v1/contacts")
        self.assertLess(ApiToken.objects.get().last_used_at, timezone.now() - timedelta(seconds=20))  # throttled write
        # no writes with a read token, no session API, no session needed or sufficient
        self.bearer("/api/v1/contacts", method="post", status=403)
        self.bearer("/api/v1/contacts", method="put", status=405)
        resp = self.client.get("/api/bootstrap", HTTP_AUTHORIZATION=f"Bearer {self.tok['token']}")
        self.assertEqual(resp.status_code, 401)
        self.as_("admin")
        self.assertEqual(self.client.get("/api/v1/contacts").status_code, 401)
        self.client.logout()
        cache.clear()  # the cookie-only request above counted as a failure
        for _ in range(20):
            self.bearer("/api/v1/contacts", token="kt_wrong", status=401)
        self.bearer("/api/v1/contacts", status=429)  # even the right token, until the window passes
