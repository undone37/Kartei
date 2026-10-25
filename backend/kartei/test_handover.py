"""Handover when someone leaves: user fields of all contacts and open reviews go to the successor."""
from django.contrib.auth.models import User

from .models import AuditEntry, FieldDef, Profile, Record, Review
from .tests import ApiTestBase


class HandoverTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        FieldDef.objects.create(key="colleagues", label_de="Kollegen", label_en="Colleagues", type="users", applies_to="both")
        self.next = User.objects.create_user("next", password="x" * 12)
        Profile.objects.create(user=self.next, role="maintainer")
        self.a = Record.objects.create(kind="person", last_name="A", data={"internal_contact": "read", "colleagues": ["read", "next"]})
        self.b = Record.objects.create(kind="person", last_name="B", data={"colleagues": ["maintainer", "read"]})
        self.c = Record.objects.create(kind="person", last_name="C", data={"internal_contact": "maintainer"})
        Review.objects.create(record=self.a, assignee=self.users["read"], reason="manual")
        self.read = self.users["read"]
        User.objects.filter(pk=self.read.pk).update(is_active=False)  # left the company
        self.as_("admin")

    def test_preview_then_handover(self):
        users = {u["username"]: u for u in self.j("get", "/api/admin/users")["users"]}
        self.assertEqual((users["read"]["refs"], users["maintainer"]["refs"]), (2, 2))
        url = f"/api/admin/users/{self.read.id}/handover"
        self.assertEqual(self.j("get", url), {"records": 2, "fields": {"internal_contact": 1, "colleagues": 2}, "reviews": 1})
        for to in ("admin", "read", "nobody"):  # admins aren't picked in user fields; not oneself
            self.j("post", url, {"to": to}, status=400)
        self.assertEqual(self.j("post", url, {"to": "next"}), {"records": 2})
        self.a.refresh_from_db(); self.b.refresh_from_db(); self.c.refresh_from_db()
        self.assertEqual(self.a.data, {"internal_contact": "next", "colleagues": ["next"]})  # no duplicate
        self.assertEqual(self.b.data["colleagues"], ["maintainer", "next"])  # order kept
        self.assertEqual(self.c.data["internal_contact"], "maintainer")
        self.assertEqual(Review.objects.get(record=self.a).assignee, self.next)  # the review follows
        self.assertTrue(AuditEntry.objects.filter(action="handover", target_label="read").exists())
        self.assertIn("handover", AuditEntry.objects.filter(target_type="record", target_label="A").last().changes)

    def test_delete_only_after_handover(self):
        self.assertEqual(self.j("delete", f"/api/admin/users/{self.read.id}", status=409)["error"], "handover_first")
        self.j("post", f"/api/admin/users/{self.read.id}/handover", {"to": "next"})
        self.j("delete", f"/api/admin/users/{self.read.id}")
        self.assertTrue(AuditEntry.objects.filter(username="admin", target_label="read", action="delete").exists())

    def test_no_review_mails_to_people_who_left(self):
        from django.core import mail
        from unittest import mock
        from . import reviews
        from .models import Settings
        Settings.objects.update(smtp_host="smtp.example", smtp_from="kartei@example.com", base_url="https://kartei.example")
        User.objects.filter(pk=self.read.pk).update(email="read@example.com")
        with mock.patch("kartei.reviews.mail_connection", lambda s: mail.get_connection()):
            self.assertEqual(reviews.notify(Settings.get()), 0)
