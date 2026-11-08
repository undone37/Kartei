"""Web Push: RFC 8291 encryption, VAPID signature, subscriptions, and what the exporter pushes to whom."""
import json
import os
from unittest import mock
from urllib.error import HTTPError

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.utils import timezone

from . import push
from .models import Proposal, PushSubscription, Record, Review, Settings
from .test_webhooks import FakeResponse
from .tests import ApiTestBase


def new_sub(host="fcm.googleapis.com"):
    key = ec.generate_private_key(ec.SECP256R1())
    return {"endpoint": f"https://{host}/fcm/send/{push.b64u(os.urandom(8))}",
            "keys": {"p256dh": push.b64u(push._point(key)), "auth": push.b64u(os.urandom(16))}}


class PushCryptoTests(ApiTestBase):
    def test_rfc8291_example(self):
        """Appendix A of RFC 8291: same keys and salt give exactly the published message."""
        as_key = ec.derive_private_key(int.from_bytes(push.unb64u("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw")),
                                       ec.SECP256R1())
        body = push.encrypt("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                            "BTBZMqHH6r4Tts7J_aSIgg", b"When I grow up, I want to be a watermelon",
                            as_key=as_key, salt=push.unb64u("DGv6ra1nlYgDCS1FRnbzlw"))
        header = push.unb64u("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
                             "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8")
        cipher = push.unb64u("8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ")
        self.assertEqual(body, header + cipher)

    def test_vapid_jwt_verifies_and_key_is_kept(self):
        key = push.vapid_key()
        self.assertEqual(push.public_key(), push.b64u(push._point(key)))  # made once, then read back
        self.assertNotIn("PRIVATE", Settings.get().vapid_private_enc)  # stored encrypted
        h = push.vapid_header("https://web.push.apple.com/abc", key, "https://kartei.example")
        jwt, k = h.removeprefix("vapid t=").split(", k=")
        head, claims, sig = jwt.split(".")
        self.assertEqual(json.loads(push.unb64u(claims))["aud"], "https://web.push.apple.com")
        raw = push.unb64u(sig)
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64u(k))
        pub.verify(encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:])),
                   f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if wrong


class PushApiTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.sent = []

    def deliver(self, fail=None):
        def fake(req, timeout):
            self.sent.append((req.full_url, json.loads(req.data)))
            if fail:
                raise fail
            return FakeResponse()
        with mock.patch("kartei.push.urlopen", fake), mock.patch("kartei.push.encrypt", lambda p, a, pt: pt):
            return push.deliver_due()

    def subscribe(self, role, host="fcm.googleapis.com"):
        self.as_(role)
        sub = new_sub(host)
        self.j("post", "/api/me/push", sub)
        return sub

    def test_subscribe_checks_input(self):
        self.client.logout()
        self.j("get", "/api/me/push", status=401)
        self.as_("read")
        self.assertEqual(len(push.unb64u(self.j("get", "/api/me/push")["key"])), 65)
        good = new_sub()
        for bad in ({**good, "endpoint": "http://fcm.googleapis.com/x"},  # not https
                    {**good, "endpoint": "https://intranet.local/x"},  # not a push service: no requests to anywhere
                    {**good, "endpoint": "https://evilfcm.googleapis.com.example/x"},
                    {**good, "keys": {"p256dh": "AAAA", "auth": good["keys"]["auth"]}},
                    {**good, "keys": {"p256dh": good["keys"]["p256dh"], "auth": "AAAA"}},
                    {"endpoint": good["endpoint"]}, []):
            self.j("post", "/api/me/push", bad, status=400)
        self.j("post", "/api/me/push", good)
        self.j("post", "/api/me/push", good)  # again (every app start): still one
        self.assertEqual(PushSubscription.objects.get().user, self.users["read"])
        self.as_("maintainer")  # someone else signs in on the same device
        self.j("post", "/api/me/push", good)
        self.assertEqual(PushSubscription.objects.get().user, self.users["maintainer"])
        self.as_("read")
        self.j("delete", "/api/me/push", {"endpoint": good["endpoint"]})  # not theirs any more
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.as_("maintainer")
        self.j("delete", "/api/me/push", {"endpoint": good["endpoint"]})
        self.assertFalse(PushSubscription.objects.exists())

    def test_reviews_and_proposals_pushed_once_to_the_right_people(self):
        self.subscribe("read", "web.push.apple.com")
        self.subscribe("maintainer")
        rec = Record.objects.create(kind="person", last_name="Meier")
        Review.objects.create(record=rec, assignee=self.users["read"], reason="manual")
        Review.objects.create(record=rec, assignee=self.users["read"], reason="manual")
        prop = Proposal.objects.create(record=rec, kind="change", proposer=self.users["read"])
        Proposal.objects.create(record=rec, kind="delete", proposer=self.users["maintainer"])
        self.assertEqual(self.deliver(), 2)
        got = {url.split("/")[2]: msg for url, msg in self.sent}
        self.assertEqual(got["web.push.apple.com"], {"title": "Kartei", "body": "2 Kontakte zu prüfen",
                                                     "tag": "review", "url": "/?list=review"})
        # the maintainer's own proposal isn't news to them; the read-only user gets no proposals at all
        self.assertEqual(got["fcm.googleapis.com"]["body"], "1 Vorschlag wartet auf Entscheidung")
        self.sent.clear()
        self.assertEqual(self.deliver(), 0)  # nothing new
        Proposal.objects.filter(pk=prop.pk).update(updated_at=timezone.now())  # edited: pushed again
        self.assertEqual(self.deliver(), 1)

    def test_gone_subscription_is_removed(self):
        self.subscribe("read")
        Review.objects.create(record=Record.objects.create(kind="person", last_name="X"), assignee=self.users["read"],
                              reason="manual")
        self.assertEqual(self.deliver(fail=HTTPError("u", 410, "Gone", {}, None)), 0)
        self.assertFalse(PushSubscription.objects.exists())

    def test_nobody_subscribed_marks_them_seen(self):
        Review.objects.create(record=Record.objects.create(kind="person", last_name="X"), assignee=self.users["read"],
                              reason="manual")
        self.deliver()
        self.subscribe("read")  # subscribing later doesn't bring old news
        self.assertEqual(self.deliver(), 0)

    def test_decisions_go_to_the_proposer(self):
        self.subscribe("read")
        rec = Record.objects.create(kind="person", last_name="Meier")
        now = timezone.now()
        a = Proposal.objects.create(record=rec, kind="change", proposer=self.users["read"], status="accepted",
                                    decided_by=self.users["maintainer"], decided_at=now)
        self.assertEqual(self.deliver(), 1)
        self.assertEqual(self.sent[-1][1], {"title": "Kartei", "body": "Dein Vorschlag wurde angenommen", "tag": "decided",
                                            "url": f"/person/{rec.uid}"})
        self.assertEqual(self.deliver(), 0)
        Proposal.objects.create(kind="create", record_kind="person", proposer=self.users["read"], status="rejected",
                                decided_by=self.users["maintainer"], decided_at=now)
        Proposal.objects.create(kind="delete", record=rec, proposer=self.users["read"], status="rejected",
                                decided_by=self.users["maintainer"], decided_at=now)
        Proposal.objects.filter(pk=a.pk).update(status="withdrawn")  # not a decision
        self.assertEqual(self.deliver(), 1)
        self.assertEqual(self.sent[-1][1]["body"], "2 deiner Vorschläge wurden entschieden")

    def test_user_switches_kinds_off(self):
        self.subscribe("maintainer")
        self.j("patch", "/api/me", {"push_off": ["proposals", "nope"]}, status=400)
        self.j("patch", "/api/me", {"push_off": [{}]}, status=400)
        self.assertEqual(self.j("patch", "/api/me", {"push_off": ["proposals"]})["user"]["push_off"], ["proposals"])
        rec = Record.objects.create(kind="person", last_name="Meier")
        Proposal.objects.create(record=rec, kind="change", proposer=self.users["read"])
        Review.objects.create(record=rec, assignee=self.users["maintainer"], reason="manual")
        self.assertEqual(self.deliver(), 1)
        self.assertEqual(self.sent[-1][1]["tag"], "review")
