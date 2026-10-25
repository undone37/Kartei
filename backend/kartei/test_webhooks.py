"""Webhooks: queued from the audit log, delivered signed by the exporter, retried, managed by admins."""
import hashlib
import hmac
import json
from unittest import mock
from urllib.error import HTTPError

from django.db import transaction
from django.utils import timezone

from . import webhooks
from .models import Record, Webhook, WebhookDelivery
from .tests import ApiTestBase, import_test_csv


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class WebhookTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.as_("admin")
        self.hook = self.j("post", "/api/admin/webhooks", {"name": "Intranet", "url": "https://intranet.example/hook"},
                           status=201)
        self.sent = []

    def deliver(self, fail=None):
        def fake(req, timeout):
            self.sent.append(req)
            if fail:
                raise fail
            return FakeResponse()
        with mock.patch("kartei.webhooks.urlopen", fake):
            return webhooks.deliver_due()

    def events(self):
        return [(json.loads(r.data)["event"], json.loads(r.data)["uid"]) for r in self.sent]

    def test_admin_only_and_secret_shown_once(self):
        self.assertTrue(self.hook["secret"].startswith("whsec_"))
        listed = self.j("get", "/api/admin/webhooks")["webhooks"]
        self.assertNotIn("secret", listed[0])
        self.assertEqual(Webhook.objects.get().secret, self.hook["secret"])  # stored encrypted, readable for signing
        self.assertNotIn(self.hook["secret"], Webhook.objects.get().secret_enc)
        bad = self.j("post", "/api/admin/webhooks", {"name": "", "url": "ftp://x", "events": ["contact.eaten"]}, status=400)
        self.assertEqual(set(bad["fields"]), {"name", "url", "events"})
        for role in ("maintainer", "read"):
            self.as_(role)
            self.j("get", "/api/admin/webhooks", status=403)

    def test_contact_lifecycle_is_delivered_signed(self):
        self.as_("maintainer")
        r = self.j("post", "/api/records", {"kind": "person", "last_name": "Hook"}, status=201)
        self.assertEqual(WebhookDelivery.objects.filter(status="pending").count(), 1)
        self.assertEqual(self.deliver(), 1)
        req = self.sent[0]
        body = json.loads(req.data)
        self.assertEqual((body["event"], body["uid"], body["contact"]["last_name"]), ("contact.created", r["uid"], "Hook"))
        ts = req.get_header("X-kartei-timestamp")
        expected = "sha256=" + hmac.new(self.hook["secret"].encode(), f"{ts}.".encode() + req.data, hashlib.sha256).hexdigest()
        self.assertEqual(req.get_header("X-kartei-signature"), expected)
        self.assertEqual(req.get_header("X-kartei-event"), "contact.created")
        r = self.j("patch", f"/api/records/{r['uid']}", {"version": r["version"], "first_name": "Hanna"})
        self.j("delete", f"/api/records/{r['uid']}")
        self.j("post", f"/api/records/{r['uid']}/restore")
        self.sent.clear()
        self.deliver()
        self.assertEqual([e for e, _ in self.events()], ["contact.updated", "contact.deleted", "contact.restored"])
        self.assertEqual(self.j("get", "/api/admin/webhooks", status=403)["error"], "forbidden")
        self.assertEqual(WebhookDelivery.objects.filter(status="delivered").count(), 4)
        self.assertTrue(Webhook.objects.get().last_status["ok"])

    def test_event_filter_disabled_and_rollback(self):
        self.j("patch", f"/api/admin/webhooks/{self.hook['id']}", {"events": ["contact.deleted"]})
        self.as_("maintainer")
        r = self.j("post", "/api/records", {"kind": "person", "last_name": "Only"}, status=201)
        self.assertFalse(WebhookDelivery.objects.exists())  # created: not wanted
        self.j("delete", f"/api/records/{r['uid']}")
        self.assertEqual(list(WebhookDelivery.objects.values_list("event", flat=True)), ["contact.deleted"])
        self.deliver()
        self.assertIsNone(json.loads(self.sent[0].data)["contact"])  # deleted: no contact data any more
        Webhook.objects.update(enabled=False, events=[])
        self.j("post", "/api/records", {"kind": "person", "last_name": "Off"}, status=201)
        self.assertEqual(WebhookDelivery.objects.count(), 1)
        Webhook.objects.update(enabled=True)
        with transaction.atomic():  # a rolled back change sends nothing
            self.j("post", "/api/records", {"kind": "person", "last_name": "Gone"}, status=201)
            transaction.set_rollback(True)
        self.assertEqual(WebhookDelivery.objects.count(), 1)

    def test_retries_then_gives_up(self):
        self.as_("maintainer")
        self.j("post", "/api/records", {"kind": "person", "last_name": "Retry"}, status=201)
        d = WebhookDelivery.objects.get()
        self.deliver(fail=HTTPError("https://intranet.example/hook", 503, "busy", {}, None))
        d.refresh_from_db()
        self.assertEqual((d.status, d.attempts, d.last_error), ("pending", 1, "HTTP 503"))
        self.assertGreater(d.next_at, timezone.now())
        self.assertEqual(self.deliver(), 0)  # not due yet
        for _ in range(len(webhooks.RETRY_MINUTES)):
            WebhookDelivery.objects.update(next_at=timezone.now())
            self.deliver(fail=OSError("connection refused"))
        d.refresh_from_db()
        self.assertEqual((d.status, d.attempts), ("failed", 7))
        self.assertEqual(Webhook.objects.get().last_status["error"], "connection refused")
        self.as_("admin")
        self.assertEqual(self.j("get", "/api/admin/webhooks")["webhooks"][0]["failed"], 1)

    def test_import_created_or_updated(self):
        csv_data = "ID;Vorname;Nachname;Firma\nP-1;A;Neu;\n".encode()
        import_test_csv(csv_data, dry_run=False)
        import_test_csv("ID;Vorname;Nachname;Firma\nP-1;A;Neuer;\n".encode(), dry_run=False)
        events = list(WebhookDelivery.objects.order_by("pk").values_list("event", flat=True))
        self.assertEqual(events, ["contact.created", "contact.updated"])
        self.assertEqual(str(WebhookDelivery.objects.first().record_uid), str(Record.objects.get(legacy_id="P-1").uid))

    def test_ping_new_secret_delete(self):
        with mock.patch("kartei.webhooks.urlopen", lambda req, timeout: FakeResponse()):
            self.assertEqual(self.j("post", f"/api/admin/webhooks/{self.hook['id']}/test")["ok"], True)
        new = self.j("post", f"/api/admin/webhooks/{self.hook['id']}/secret")["secret"]
        self.assertNotEqual(new, self.hook["secret"])
        self.assertEqual(Webhook.objects.get().secret, new)
        self.j("post", f"/api/admin/webhooks/{self.hook['id']}/nonsense", status=404)
        self.j("delete", f"/api/admin/webhooks/{self.hook['id']}")
        self.assertFalse(Webhook.objects.exists())

    def test_one_failing_receiver_costs_one_attempt_per_run(self):
        Webhook.objects.create(name="Second", url="https://second.example/hook", secret="x")
        self.as_("maintainer")
        for name in ("A", "B", "C"):
            self.j("post", "/api/records", {"kind": "person", "last_name": name}, status=201)
        urls = []

        def fake(req, timeout):
            urls.append(req.full_url)
            if "intranet" in req.full_url:
                raise OSError("timed out")
            return FakeResponse()
        with mock.patch("kartei.webhooks.urlopen", fake):
            webhooks.deliver_due()
        self.assertEqual(urls.count("https://intranet.example/hook"), 1)  # the other two wait for the next run
        self.assertEqual(urls.count("https://second.example/hook"), 3)
        self.assertEqual(WebhookDelivery.objects.filter(webhook__name="Intranet", attempts=0).count(), 2)

    def test_time_budget_and_no_redirects(self):
        self.as_("maintainer")
        self.j("post", "/api/records", {"kind": "person", "last_name": "A"}, status=201)
        self.j("post", "/api/records", {"kind": "person", "last_name": "B"}, status=201)
        clock = iter([0, 0, 100, 100, 100])
        with mock.patch("kartei.webhooks.time.monotonic", lambda: next(clock)), \
             mock.patch("kartei.webhooks.urlopen", lambda req, timeout: FakeResponse()):
            self.assertEqual(webhooks.deliver_due(), 1)  # the budget ran out after the first
        self.assertIsNone(webhooks._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example"))

