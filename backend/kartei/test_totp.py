"""Two-factor sign-in: setup and confirm, sign-in with code or recovery code, no replay, disable, admin reset."""
import base64
import hashlib
import time
from unittest import mock

from django.core.cache import cache
from django.test import override_settings

from . import totp
from .models import AuditEntry, Profile, Settings
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
        pw = "pw-" + role * 3
        self.j("post", "/api/me/totp", {"action": "confirm", "code": "000000", "password": pw}, status=400)
        self.j("post", "/api/me/totp", {"action": "confirm", "code": now_code(s["secret"]), "password": "nope"}, status=400)
        r = self.j("post", "/api/me/totp", {"action": "confirm", "code": now_code(s["secret"]), "password": pw})
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

    def test_recovery_codes_are_keyed_with_the_secret_key(self):
        """Run-2 K-07: a database copy alone (no SECRET_KEY) must not let anyone work a code out offline."""
        codes, hashes = totp.new_recovery_codes()
        self.assertEqual(len(codes[0]), 21)  # 2 × 40 bits
        self.assertNotEqual(hashes[0], hashlib.sha256(codes[0].encode()).hexdigest())
        self.assertEqual(totp.match_recovery(hashes, codes[0].upper()), hashes[0])
        with override_settings(SECRET_KEY="another-key-" * 4):
            self.assertIsNone(totp.match_recovery(hashes, codes[0]))

    def test_recovery_codes_from_before_still_work_once(self):
        secret, codes = self.enable()
        old = ["abc123-def456", "111111-222222"]
        Profile.objects.filter(user=self.users["maintainer"]).update(
            totp_recovery=[hashlib.sha256(c.encode()).hexdigest() for c in old])
        self.as_("maintainer")
        self.assertTrue(self.j("get", "/api/session")["user"]["totp_recovery_legacy"])
        self.client.logout()
        self.login(old[0])
        self.client.logout()
        self.login(old[0], status=401)
        self.login(old[1])
        with mock.patch("kartei.totp.time.time", return_value=time.time() + 120):
            r = self.j("post", "/api/me/totp", {"action": "recovery", "code": now_code(secret)})
        self.assertFalse(r["user"]["totp_recovery_legacy"])

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
        for _ in range(5):  # the second-factor lock comes before the sign-in throttle (10)
            self.login("000000", status=401)
        self.assertEqual(self.login("000000", status=429)["error"], "too_many_attempts")

    def test_an_active_secret_cant_be_replaced(self):
        self.enable()
        self.as_("maintainer")
        self.assertEqual(self.j("post", "/api/me/totp", {"action": "setup"}, status=409)["error"], "totp_already_on")
        self.j("post", "/api/me/totp", {"action": "confirm", "code": "123456", "password": "pw-" + "maintainer" * 3}, status=409)

    def test_wrong_codes_lock_the_second_factor_in_the_database(self):
        secret, codes = self.enable()
        self.as_("maintainer")
        for _ in range(5):
            self.j("post", "/api/me/totp", {"action": "recovery", "code": "000000"}, status=400)
        self.assertEqual(self.j("post", "/api/me/totp", {"action": "disable", "code": codes[0]}, status=429)["error"], "too_many_attempts")
        cache.clear()  # the sign-in throttle is per process; the lock is not
        self.client.logout()
        self.assertEqual(self.login(codes[0], status=429)["error"], "too_many_attempts")
        Profile.objects.filter(user=self.users["maintainer"]).update(totp_failed_at=None)  # 15 minutes later
        self.login(codes[0])

    def test_policy_requires_it_for_admins_or_everyone(self):
        self.as_("admin")
        self.j("put", "/api/admin/settings", {"totp_required": "sometimes"}, status=400)
        self.j("put", "/api/admin/settings", {"totp_required": "admins"})
        self.assertTrue(self.client.get("/api/session").json()["user"]["totp_due"])
        self.assertEqual(self.j("get", "/api/bootstrap", status=403)["error"], "totp_setup_required")
        self.as_("maintainer")
        self.j("get", "/api/bootstrap")  # not an admin
        self.client.logout()
        _, codes = self.enable("admin")  # setup and confirm are allowed while it's due
        self.as_("admin")
        self.j("get", "/api/bootstrap")
        self.assertEqual(self.j("post", "/api/me/totp", {"action": "disable", "code": codes[0]}, status=409)["error"], "totp_policy")
        Settings.objects.update(totp_required="all")
        self.as_("read")
        self.assertEqual(self.j("get", "/api/bootstrap", status=403)["error"], "totp_setup_required")

    def test_wrong_step_up_passwords_lock(self):
        """F-3: a session alone must not be able to guess the password (or take the account by changing it)."""
        self.as_("read")
        for _ in range(10):
            self.j("patch", "/api/me", {"old_password": "guess", "password": "x" * 12}, status=400)
        self.j("patch", "/api/me", {"old_password": "pw-readreadread", "password": "x" * 12}, status=429)
        self.j("post", "/api/me/totp", {"action": "confirm", "code": "000000", "password": "pw-readreadread"}, status=429)
        self.assertTrue(AuditEntry.objects.filter(action="login_failed", target_label="read").exists())

    def test_password_change_needs_the_code_with_two_factor(self):
        secret, recovery = self.enable()
        self.client.force_login(self.users["maintainer"])
        body = {"old_password": "pw-" + "maintainer" * 3, "password": "y" * 12}
        r = self.j("patch", "/api/me", body, status=400)
        self.assertEqual(r["fields"], {"code": "invalid_code"})
        self.j("patch", "/api/me", body | {"code": recovery[0]})
