"""DMZ relay: push endpoint and CardDAV serving of pushed cards.

Runs with the Kartei settings (manage.py test adds the relay app) and with config.relay_settings.
"""
import base64
import hashlib
import json
import re
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Book, Card

TOKEN = "push-token-for-tests"
A, B, C = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
           "33333333-3333-4333-8333-333333333333")


def card(uid, n=1):
    return {"uid": uid, "etag": f'"{n}-abc"', "ios": f"BEGIN:VCARD\r\nFN:iOS {uid} v{n}\r\nEND:VCARD\r\n",
            "android": f"BEGIN:VCARD\r\nFN:Android {uid} v{n}\r\nEND:VCARD\r\n"}


@override_settings(ROOT_URLCONF="config.relay_urls", RELAY_PUSH_TOKEN_SHA256=hashlib.sha256(TOKEN.encode()).hexdigest())
class RelayTestBase(TestCase):
    def push(self, body, token=TOKEN, status=200, raw=None, ctype="application/json"):
        r = self.client.post("/push", raw if raw is not None else json.dumps(body), content_type=ctype,
                             HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, status, r.content[:300])
        return r.json()

    def cred(self, pw="phone-secret"):
        return {"username": "carddav", "password_hash": make_password(pw)}


class PushTests(RelayTestBase):
    def test_auth(self):
        self.assertEqual(self.client.get("/push").status_code, 401)
        self.push({}, token="wrong", status=401)
        self.assertEqual(self.client.get("/push", HTTP_AUTHORIZATION=f"Bearer {TOKEN}").json(), {"cards": {}})
        with override_settings(RELAY_PUSH_TOKEN_SHA256=""):  # no token configured: push is off
            self.push({}, status=401)

    def test_validation(self):
        self.push(None, raw="cards=1", ctype="application/x-www-form-urlencoded", status=415)
        self.push(None, raw="{not json", status=400)
        self.push({"cards": [], "records": []}, status=400)  # nothing but cards, deletes and the login
        self.push({"cards": [{**card(A), "note": "x"}]}, status=400)
        self.push({"cards": [{**card(A), "uid": "../etc"}]}, status=400)
        self.push({"cards": [{**card(A), "etag": '"1"\r\nSet-Cookie: x'}]}, status=400)
        self.push({"cards": [{**card(A), "ios": "<html>"}]}, status=400)
        self.push({"delete": ["nope"]}, status=400)
        self.push({"credentials": {"username": "carddav", "password_hash": "plain-text"}}, status=400)
        self.push({"credentials": {"username": "carddav", "password_hash": "x", "admin": True}}, status=400)
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1000):
            self.assertEqual(self.client.post("/push", json.dumps({"cards": [card(A)] * 20}), content_type="application/json",
                                              HTTP_AUTHORIZATION=f"Bearer {TOKEN}").status_code, 413)
        self.assertFalse(Card.objects.exists())

    def test_create_update_delete_idempotent(self):
        r = self.push({"cards": [card(A), card(B)], "credentials": self.cred()})
        self.assertEqual((r["updated"], r["deleted"], r["total"]), (2, 0, 2))
        ctag = Book.get().ctag
        r = self.push({"cards": [card(A), card(B)]})  # same again: nothing changes, ctag stays
        self.assertEqual((r["updated"], Book.get().ctag), (0, ctag))
        r = self.push({"cards": [card(A, 2)], "delete": [B, C]})
        self.assertEqual((r["updated"], r["deleted"], r["total"]), (1, 1, 1))
        self.assertNotEqual(Book.get().ctag, ctag)
        self.assertIn("v2", Card.objects.get(uid=A).ios)
        self.assertEqual(self.client.get("/push", HTTP_AUTHORIZATION=f"Bearer {TOKEN}").json(), {"cards": {A: '"2-abc"'}})

    def test_credentials(self):
        self.push({"credentials": self.cred("first")})
        self.assertEqual(Book.get().username, "carddav")
        self.push({"cards": [card(A)]})  # without credentials: login unchanged
        self.assertTrue(Book.get().password_hash.startswith("pbkdf2"))
        self.push({"credentials": {"username": "carddav", "password_hash": ""}})  # empty hash locks phones out
        self.assertEqual(Book.get().password_hash, "")


class CardDavTests(RelayTestBase):
    def setUp(self):
        self.push({"cards": [card(A), card(B)], "credentials": self.cred()})
        self.auth = "Basic " + base64.b64encode(b"carddav:phone-secret").decode()

    def dav(self, method, path, body="", **headers):
        return self.client.generic(method, path, body, content_type="application/xml", HTTP_AUTHORIZATION=self.auth,
                                   **headers)

    def test_auth_and_readonly(self):
        self.assertEqual(self.client.generic("PROPFIND", "/carddav/").status_code, 401)
        self.assertEqual(self.client.generic("PROPFIND", "/carddav/", HTTP_AUTHORIZATION="Basic "
                         + base64.b64encode(b"carddav:wrong").decode()).status_code, 401)
        self.assertEqual(self.dav("PUT", f"/carddav/kontakte/{A}.vcf", "x").status_code, 403)
        self.assertEqual(self.dav("DELETE", f"/carddav/kontakte/{A}.vcf").status_code, 403)
        self.assertEqual(self.client.options("/carddav/").status_code, 200)
        self.assertEqual(self.client.get("/.well-known/carddav")["Location"], "/carddav/")
        for path in ("/", "/django-admin/", "/admin/", "/api/session", "/static/x.js", "/carddav/other/"):
            self.assertEqual(self.dav("GET", path).status_code, 404, path)

    def test_lockout(self):
        bad = "Basic " + base64.b64encode(b"carddav:wrong").decode()
        for _ in range(20):
            self.client.generic("PROPFIND", "/carddav/", HTTP_AUTHORIZATION=bad, REMOTE_ADDR="10.9.9.9")
        r = self.client.generic("PROPFIND", "/carddav/", HTTP_AUTHORIZATION=self.auth, REMOTE_ADDR="10.9.9.9")
        self.assertEqual(r.status_code, 401)

    def test_propfind_get_report(self):
        r = self.dav("PROPFIND", "/carddav/kontakte/", HTTP_DEPTH="1")
        self.assertEqual(r.status_code, 207)
        self.assertEqual(r.content.count(b".vcf</d:href>"), 2)
        self.assertIn(f'"{Book.get().ctag}"'.encode(), r.content)
        self.assertIn(b'<d:getetag>"1-abc"</d:getetag>', r.content)
        r = self.dav("PROPFIND", f"/carddav/kontakte/{A}.vcf", HTTP_DEPTH="0")
        self.assertIn(b'<d:getetag>"1-abc"</d:getetag>', r.content)
        self.assertEqual(self.dav("PROPFIND", f"/carddav/kontakte/{C}.vcf").status_code, 404)

        r = self.dav("GET", f"/carddav/kontakte/{A}.vcf", HTTP_USER_AGENT="iOS/17.0 (21A329) dataaccessd/1.0")
        self.assertEqual((r.content.decode(), r["ETag"]), (card(A)["ios"], '"1-abc"'))
        r = self.dav("GET", f"/carddav/kontakte/{A}.vcf", HTTP_USER_AGENT="DAVx5/4.4")
        self.assertEqual(r.content.decode(), card(A)["android"])
        self.assertEqual(self.dav("GET", f"/carddav/kontakte/{C}.vcf").status_code, 404)

        body = ('<c:addressbook-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop>'
                f'<d:getetag/><c:address-data/></d:prop><d:href>/carddav/kontakte/{B}.vcf</d:href>'
                '</c:addressbook-multiget>')
        r = self.dav("REPORT", "/carddav/kontakte/", body, HTTP_USER_AGENT="iOS/17.0 (21A329) dataaccessd/1.0")
        self.assertEqual(r.status_code, 207)
        self.assertEqual(r.content.count(b"BEGIN:VCARD"), 1)
        self.assertIn(f"iOS {B}".encode(), r.content)
        r = self.dav("REPORT", "/carddav/kontakte/", '<c:addressbook-query xmlns:c="urn:ietf:params:xml:ns:carddav"/>')
        self.assertEqual(r.content.count(b"BEGIN:VCARD"), 2)

    def sync(self, token=""):
        body = ('<d:sync-collection xmlns:d="DAV:"><d:sync-token>' + token + '</d:sync-token><d:sync-level>1</d:sync-level>'
                '<d:prop><d:getetag/></d:prop></d:sync-collection>')
        return self.dav("REPORT", "/carddav/kontakte/", body)

    def test_sync_collection(self):
        r = self.sync()  # first sync: everything
        self.assertEqual((r.status_code, r.content.count(b".vcf</d:href>")), (207, 2))
        Card.objects.update(changed_at=timezone.now() - timedelta(hours=1))
        token = re.search(rb"<d:sync-token>([^<]+)</d:sync-token>", r.content)[1].decode()
        self.assertEqual(self.sync(token).content.count(b"<d:response>"), 0)  # nothing new
        self.push({"cards": [card(A, 2), card(C)], "delete": [B]})
        r = self.sync(token)
        self.assertIn(f"{A}.vcf</d:href><d:propstat>".encode(), r.content)
        self.assertIn(f"{C}.vcf</d:href><d:propstat>".encode(), r.content)
        self.assertIn(f"{B}.vcf</d:href><d:status>HTTP/1.1 404 Not Found".encode(), r.content)
        self.assertEqual(self.dav("GET", f"/carddav/kontakte/{B}.vcf").status_code, 404)  # a tombstone isn't served
        self.push({"cards": [card(B, 3)]})  # comes back
        self.assertEqual(self.dav("GET", f"/carddav/kontakte/{B}.vcf").status_code, 200)
        # tombstones are kept 30 days; a token from before that can't be served any more
        Card.objects.filter(uid=C).update(deleted=True, changed_at=timezone.now() - timedelta(days=40))
        self.push({})
        self.assertFalse(Card.objects.filter(uid=C).exists())
        self.assertEqual(self.sync(token).status_code, 207)  # this phone synced after the cut: still fine
        old = int((timezone.now() - timedelta(days=35)).timestamp() * 1e6)
        r = self.sync(f"urn:kartei:sync:{old}")
        self.assertEqual(r.status_code, 403)
        self.assertIn(b"valid-sync-token", r.content)
        self.assertEqual(self.sync("garbage").status_code, 403)

