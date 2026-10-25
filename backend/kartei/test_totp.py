"""Two-factor sign-in: setup and confirm, sign-in with code or recovery code, no replay, disable, admin reset."""
import base64
import time
from unittest import mock

from django.core.cache import cache

from . import totp
from .models import AuditEntry, Profile
from .tests import ApiTestBase


def now_code(secret, steps=0):
    return totp.code_at(secret, int(time.time() // totp.STEP) + steps)


class TotpTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()  # failed sign-ins of other tests

    def enable(self, role="maintainer"):
        self.as_(role)
        s = self.j("post", "/api/me/totp", {"action": "setup"})
        self.assertTrue(s["uri"].startswith("otpauth://totp/Kartei:" + role))
        self.j("post", "/api/me/totp", {"action": "confirm", "code": "000000"}, status=400)
        r = self.j("post", "/api/me/totp", {"action": "confirm", "code": now_code(s["secret"])})
        self.assertTrue(r["user"]["totp"])
        self.assertEqual(len(r["recovery"]), 8)
        self.client.logout()
        return s["secret"], r["recovery"]

    def login(self, code=None, role="maintainer", status=200):
        body = {"username": role, "password": "pw-" + role * 3} | ({"code": code} if code is not None else {})
        return self.j("post", "/api/login", body, status=status)

    def test_rfc6238_vectors(self):
        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(totp.code_at(secret, 59 // 30), "287082")
        self.assertEqual(totp.code_at(secret, 1111111109 // 30), "081804")

    def test_sign_in_needs_the_code_once(self):
        secret, _ = self.enable()
        self.assertEqual(self.login(status=401)["error"], "totp_required")
        self.assertEqual(self.login("123456", status=401)["error"], "invalid_code")
        later = now_code(secret, 1)  # the next step, as a phone slightly ahead would show it
        self.login(later)
        self.client.logout()
        self.assertEqual(self.login(later, status=401)["error"], "invalid_code")  # each code works only once
        self.assertEqual(self.login(now_code(secret), status=401)["error"], "invalid_code")  # nor an older step

    def test_recovery_codes_work_once_and_can_be_renewed(self):
        secret, codes = self.enable()
        self.login(codes[0].upper())  # case and spaces don't matter
        self.client.logout()
        self.login(codes[0], status=401)
        with mock.patch("kartei.totp.time.time", return_value=time.time() + 120):  # patches time.time everywhere
            self.login(now_code(secret))
            new = self.j("post", "/api/me/totp", {"action": "recovery", "code": codes[1]})["recovery"]
        self.client.logout()
        self.login(codes[2], status=401)  # old ones are gone
        self.login(new[0])

    def test_disable_and_admin_reset(self):
        secret, codes = self.enable()
        self.as_("maintainer")
        self.j("post", "/api/me/totp", {"action": "disable", "code": "111111"}, status=400)
        self.assertFalse(self.j("post", "/api/me/totp", {"action": "disable", "code": codes[0]})["user"]["totp"])
        self.client.logout()
        self.login()  # password alone again
        self.enable()
        self.as_("maintainer")
        uid = self.users["maintainer"].id
        self.j("post", f"/api/admin/users/{uid}/totp-reset", status=403)
        self.as_("admin")
        self.assertFalse(self.j("post", f"/api/admin/users/{uid}/totp-reset")["totp"])
        self.assertEqual(Profile.objects.get(user_id=uid).totp_secret_enc, "")
        log = " ".join(str(e.changes) for e in AuditEntry.objects.filter(target_type="user"))
        self.assertIn("'totp': [True, False]", log)
        self.assertNotIn(secret, log)

    def test_wrong_codes_count_towards_the_lockout(self):
        self.enable()
        for _ in range(10):
            self.login("000000", status=401)
        self.assertEqual(self.login("000000", status=429)["error"], "too_many_attempts")
