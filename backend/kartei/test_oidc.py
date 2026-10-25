"""Sign in with Microsoft: state/PKCE in the session, token checks, matching to an existing user."""
import base64
import json
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User

from .graph import GraphError
from .models import AuditEntry, Profile, Settings
from .tests import ApiTestBase

OID = "0a0a0a0a-0000-0000-0000-000000000001"
TENANT, CLIENT = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def id_token(**claims):
    body = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT, "aud": CLIENT,
            "exp": time.time() + 600, "preferred_username": "maintainer@example.com", "oid": OID} | claims
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256'})}.{enc(body)}.signature"


class OidcTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        s = Settings.get()
        s.graph_tenant_id, s.graph_client_id, s.graph_client_secret = TENANT, CLIENT, "secret"
        s.base_url, s.oidc_enabled = "https://kartei.example", True
        s.save()
        User.objects.filter(username="maintainer").update(email="maintainer@example.com")
        Profile.objects.filter(user__username__in=["maintainer", "read"]).update(source="ldap")  # directory users

    def sso(self, **claims):
        state, nonce = self.start()
        return self.callback(state, id_token(nonce=nonce, **claims))[0]["Location"]

    def start(self):
        r = self.client.get("/api/oidc/start")
        self.assertEqual(r.status_code, 302)
        q = parse_qs(urlparse(r["Location"]).query)
        self.assertEqual(q["redirect_uri"], ["https://kartei.example/api/oidc/callback"])
        self.assertEqual((q["code_challenge_method"], q["client_id"]), (["S256"], [CLIENT]))
        return q["state"][0], q["nonce"][0]

    def callback(self, state, token=None, error=None):
        with mock.patch("kartei.oidc.http", side_effect=error or (lambda *a, **k: {"id_token": token})) as http:
            r = self.client.get("/api/oidc/callback", {"code": "the-code", "state": state})
        return r, http

    def test_signs_in_an_existing_user(self):
        self.assertTrue(self.client.get("/api/session").json()["sso"])
        state, nonce = self.start()
        r, http = self.callback(state, id_token(nonce=nonce))
        self.assertEqual(r["Location"], "/")
        form = http.call_args.kwargs["form"]
        self.assertEqual((form["code"], form["grant_type"]), ("the-code", "authorization_code"))
        self.assertTrue(form["code_verifier"])  # PKCE
        self.assertEqual(self.client.get("/api/session").json()["user"]["username"], "maintainer")
        self.assertTrue(AuditEntry.objects.filter(action="login", username="maintainer").exists())

    def test_refuses_bad_state_tokens_and_unknown_users(self):
        state, nonce = self.start()
        self.assertIn("sso_expired", self.callback("forged", id_token(nonce=nonce))[0]["Location"])  # state is used up too
        for claims, code in (({"nonce": "other"}, "sso_invalid"), ({"aud": "someone-else"}, "sso_invalid"),
                             ({"tid": "99999999-2222-3333-4444-555555555555",
                               "iss": "https://login.microsoftonline.com/99999999-2222-3333-4444-555555555555/v2.0"}, "sso_invalid"),
                             ({"exp": time.time() - 1}, "sso_invalid"),
                             ({"preferred_username": "stranger@example.com"}, "sso_unknown_user")):
            state, nonce = self.start()
            r, _ = self.callback(state, id_token(**({"nonce": nonce} | claims)))
            self.assertEqual(r["Location"], f"/?login_error={code}", claims)
        state, _ = self.start()
        self.assertEqual(self.callback(state, error=GraphError("HTTP 400"))[0]["Location"], "/?login_error=sso_failed")
        self.assertFalse(self.client.get("/api/session").json()["authenticated"])
        r = self.client.get("/api/oidc/callback", {"error": "access_denied"})
        self.assertEqual(r["Location"], "/?login_error=sso_cancelled")

    def test_only_directory_users_by_upn_then_bound_to_the_account(self):
        User.objects.filter(username="read").update(email="read@example.com")
        self.assertEqual(self.sso(preferred_username="READ"), "/?login_error=sso_unknown_user")  # no local-part matching
        self.assertEqual(self.sso(preferred_username="x@example.com", email="read@example.com"), "/?login_error=sso_unknown_user")
        self.assertEqual(self.sso(idp="https://sts.windows.net/99999999-2222-3333-4444-555555555555/"),
                         "/?login_error=sso_unknown_user")  # a guest
        for username in ("admin", "maintainer"):  # a local user, a superuser
            Profile.objects.filter(user__username="maintainer").update(source="local" if username == "maintainer" else "ldap")
            User.objects.filter(username=username).update(email="who@example.com")
            self.assertEqual(self.sso(preferred_username="who@example.com"), "/?login_error=sso_unknown_user", username)
            User.objects.filter(username=username).update(email="")
        Profile.objects.filter(user__username="maintainer").update(source="ldap")
        User.objects.filter(username="maintainer").update(email="maintainer@example.com")
        self.assertEqual(self.sso(), "/")
        self.assertEqual(Profile.objects.get(user__username="maintainer").sso_oid, OID)
        self.client.logout()
        # bound: a renamed account still gets in, another account with the same name doesn't
        self.assertEqual(self.sso(preferred_username="renamed@example.com"), "/")
        self.client.logout()
        other = "0a0a0a0a-0000-0000-0000-000000000002"
        self.assertEqual(self.sso(oid=other), "/?login_error=sso_unknown_user")
        self.assertEqual(self.sso(oid=""), "/?login_error=sso_invalid")
        User.objects.filter(username="maintainer").update(is_active=False)
        self.assertEqual(self.sso(), "/?login_error=sso_unknown_user")

    def test_off_or_incomplete(self):
        Settings.objects.update(oidc_enabled=False)
        self.assertFalse(self.client.get("/api/session").json()["sso"])
        self.assertEqual(self.client.get("/api/oidc/start").status_code, 404)
        self.as_("admin")
        Settings.objects.update(base_url="")
        bad = self.j("put", "/api/admin/settings", {"oidc_enabled": True}, status=400)
        self.assertEqual(bad["fields"]["oidc_enabled"], "oidc_incomplete")
        Settings.objects.update(base_url="https://kartei.example", graph_tenant_id="common")
        bad = self.j("put", "/api/admin/settings", {"oidc_enabled": True}, status=400)
        self.assertEqual(bad["fields"]["oidc_enabled"], "oidc_tenant_id")

    def test_two_factor_still_asked_after_microsoft(self):
        from . import totp
        p = Profile.objects.get(user__username="maintainer")
        p.totp_secret = secret = totp.new_secret()
        p.save()
        self.assertEqual(self.sso(), "/?login_step=totp")
        self.assertFalse(self.client.get("/api/session").json()["authenticated"])
        self.assertEqual(self.j("post", "/api/login", {"code": "000000"}, status=401)["error"], "invalid_code")
        self.j("post", "/api/login", {"username": "", "code": totp.code_at(secret, int(time.time() // totp.STEP))})
        self.assertEqual(self.client.get("/api/session").json()["user"]["username"], "maintainer")
        self.client.logout()
        self.assertEqual(self.j("post", "/api/login", {"code": "123456"}, status=401)["error"], "invalid_credentials")
