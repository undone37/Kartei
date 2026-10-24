"""Kartei side of the CardDAV relay: push job (diff, guards, status), settings API and the HTTP client.

The relay is the real relay app (installed for tests), reached through the Django test client instead of the network.
"""
import base64
import hashlib
import json
import ssl
from io import BytesIO
from unittest import mock
from urllib.error import HTTPError

from django.contrib.auth.hashers import make_password
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from relay.models import Book, Card

from . import relaypush
from .carddav import _fields
from .management.commands import export_loop
from .models import Record, Settings, ref_names
from .tests import PERSON_UID, ApiTestBase, sample_records
from .vcard import render

IOS = "iOS/17.0 (21A329) dataaccessd/1.0"


class FakeRelay:
    """Routes relaypush.call to the relay views; records the requests."""

    def __init__(self):
        self.client, self.requests = Client(), []

    def __call__(self, s, method, body=None):
        self.requests.append((method, body))
        sha = hashlib.sha256(s.carddav_relay_token.encode()).hexdigest()
        with override_settings(ROOT_URLCONF="config.relay_urls", RELAY_PUSH_TOKEN_SHA256=sha):
            auth = {"HTTP_AUTHORIZATION": f"Bearer {s.carddav_relay_token}"}
            r = (self.client.get("/push", **auth) if method == "GET" else
                 self.client.post("/push", json.dumps(body), content_type="application/json", **auth))
        if r.status_code != 200:
            raise relaypush.RelayError(f"HTTP {r.status_code}")
        return r.json()

    def dav(self, path, ua="DAVx5/4.4", pw="phone-secret"):
        with override_settings(ROOT_URLCONF="config.relay_urls"):
            return self.client.get(path, HTTP_USER_AGENT=ua,
                                   HTTP_AUTHORIZATION="Basic " + base64.b64encode(f"carddav:{pw}".encode()).decode())


def configure(**kw):
    s = Settings.get()
    s.carddav_relay_enabled, s.carddav_relay_url, s.carddav_relay_token = True, "https://relay.example", "tok-123"
    s.carddav_password_hash = make_password("phone-secret")
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    return s


class PushJobTests(TestCase):
    def setUp(self):
        self.person, self.company = sample_records()
        self.relay = FakeRelay()
        patcher = mock.patch.object(relaypush, "call", self.relay)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled(self):
        self.assertIsNone(relaypush.run())
        self.assertEqual(self.relay.requests, [])

    def test_push_diff_and_serve(self):
        configure()
        st = relaypush.run()
        self.assertEqual((st["updated"], st["deleted"], st["total"]), (3, 0, 3), st)
        self.assertEqual(Settings.get().carddav_relay_status["updated"], 3)
        self.assertEqual(Book.get().username, "carddav")
        # the phone gets exactly what the built-in server would render, per flavour
        fields, names = _fields(), ref_names()
        r = self.relay.dav(f"/carddav/kontakte/{PERSON_UID}.vcf", ua=IOS)
        self.assertEqual(r.content.decode(), render(self.person, fields, "ios", "", names))
        r = self.relay.dav(f"/carddav/kontakte/{PERSON_UID}.vcf")
        self.assertEqual(r.content.decode(), render(self.person, fields, "android", "", names))
        self.assertEqual(self.relay.dav("/carddav/kontakte/", pw="wrong").status_code, 401)

        self.assertEqual(relaypush.run()["updated"], 0)  # nothing changed: only the login is sent
        self.assertEqual(self.relay.requests[-1][1]["cards"], [])
        self.person.data["nickname"] = "Sandro"
        self.person.version += 1
        self.person.save()
        st = relaypush.run()
        self.assertEqual((st["updated"], st["deleted"]), (1, 0))
        self.assertIn("Sandro", Card.objects.get(uid=PERSON_UID).ios)

    def test_delete_guard_and_strays(self):
        configure(carddav_relay_max_delete_percent=10)
        relaypush.run()
        Record.objects.filter(uid=PERSON_UID).update(deleted_at=timezone.now())
        st = relaypush.run()  # 1 of 3 = 33 % > 10 %
        self.assertTrue(st["error"].startswith("@relay_too_many_deletes"), st)
        self.assertEqual(Card.objects.count(), 3)
        Settings.objects.update(carddav_relay_max_delete_percent=50)
        Card.objects.create(uid="44444444-4444-4444-8444-444444444444", etag='"x"', ios="BEGIN:VCARD", android="BEGIN:VCARD")
        st = relaypush.run()  # the deleted record and the stray the relay had on its own
        self.assertEqual((st["deleted"], st["total"]), (2, 2), st)

    def test_no_records_guard(self):
        configure()
        Record.objects.all().delete()
        self.assertEqual(relaypush.run()["error"], '@relay_no_records {}')
        self.assertEqual(self.relay.requests, [])

    def test_credentials_follow(self):
        configure()
        relaypush.run()
        Settings.objects.update(carddav_password_hash=make_password("new-secret"))
        relaypush.run()
        self.assertEqual(self.relay.dav("/carddav/kontakte/", pw="phone-secret").status_code, 401)
        self.assertEqual(self.relay.dav("/carddav/kontakte/", pw="new-secret").status_code, 200)

    def test_chunks(self):
        configure()
        with mock.patch.object(relaypush, "CHUNK", 1):
            relaypush.run()
        posts = [b for m, b in self.relay.requests if m == "POST"]
        self.assertEqual([len(b["cards"]) for b in posts], [1, 1, 1, 0])

    def test_exporter_runs_push(self):
        configure()
        Settings.objects.update(carddav_relay_requested=timezone.now())
        export_loop.tick()
        s = Settings.get()
        self.assertIsNone(s.carddav_relay_requested)
        self.assertEqual(s.carddav_relay_status["total"], 3)


class ClientTests(TestCase):
    def test_request_and_errors(self):
        s = configure(carddav_relay_tls_verify=False)
        seen = {}

        def fake(req, timeout, context):
            seen.update(url=req.full_url, auth=req.get_header("Authorization"), verify=context.verify_mode)
            return BytesIO(b'{"cards": {}}')
        with mock.patch.object(relaypush, "urlopen", fake):
            self.assertEqual(relaypush.test(s), {"ok": True, "cards": 0})
        self.assertEqual(seen, {"url": "https://relay.example/push", "auth": "Bearer tok-123", "verify": ssl.CERT_NONE})

        def denied(req, timeout, context):
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        with mock.patch.object(relaypush, "urlopen", denied):
            self.assertEqual(relaypush.test(s), {"error": "@relay_unauthorized {}"})
        s.carddav_relay_tls_verify, s.carddav_relay_ca_cert = True, "-----BEGIN CERTIFICATE-----\nnope\n-----END CERTIFICATE-----"
        self.assertIn("error", relaypush.test(s))


class SettingsApiTests(ApiTestBase):
    def test_settings_token_sync(self):
        self.as_("admin")
        r = self.j("put", "/api/admin/settings", {"carddav_relay_enabled": True}, status=400)
        self.assertEqual(r["fields"]["carddav_relay_enabled"], "relay_incomplete")
        r = self.j("put", "/api/admin/settings", {"carddav_relay_url": "http://relay.example"}, status=400)
        self.assertEqual(r["fields"]["carddav_relay_url"], "invalid_url")
        self.j("post", "/api/admin/carddav/relay-sync", status=409)
        r = self.j("post", "/api/admin/carddav/relay-token")
        s = Settings.get()
        self.assertEqual(r["carddav_relay_token_sha256"], hashlib.sha256(s.carddav_relay_token.encode()).hexdigest())
        self.assertNotIn(s.carddav_relay_token, json.dumps(r))
        self.assertNotIn(s.carddav_relay_token, s.carddav_relay_token_enc)
        r = self.j("put", "/api/admin/settings", {"carddav_relay_enabled": True, "carddav_relay_url": "https://relay.example/",
                                                  "carddav_enabled": False})
        self.assertTrue(r["carddav_relay_enabled"])
        self.assertIsNotNone(self.j("post", "/api/admin/carddav/relay-sync")["carddav_relay_requested"])
        self.assertEqual(self.client.generic("PROPFIND", "/carddav/").status_code, 404)  # inside server is off
        self.as_("maintainer")
        self.j("post", "/api/admin/carddav/relay-token", status=403)
