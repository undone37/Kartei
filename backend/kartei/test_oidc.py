"""Sign in with Microsoft: state/PKCE in the session, token checks, matching to an existing user."""
import base64
import json
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User

from .graph import GraphError
from .models import AuditEntry, Settings
from .tests import ApiTestBase

TENANT, CLIENT = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def id_token(**claims):
    body = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT, "aud": CLIENT,
            "exp": time.time() + 600, "preferred_username": "maintainer@example.com"} | claims
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

    def test_user_name_from_the_account_and_inactive_users(self):
        state, nonce = self.start()  # "read" has no email: matched by the part before the @
        self.callback(state, id_token(nonce=nonce, preferred_username="READ@example.com"))
        self.assertEqual(self.client.get("/api/session").json()["user"]["username"], "read")
        self.client.logout()
        User.objects.filter(username="maintainer").update(is_active=False)
        state, nonce = self.start()
        self.assertEqual(self.callback(state, id_token(nonce=nonce))[0]["Location"], "/?login_error=sso_unknown_user")

    def test_off_or_incomplete(self):
        Settings.objects.update(oidc_enabled=False)
        self.assertFalse(self.client.get("/api/session").json()["sso"])
        self.assertEqual(self.client.get("/api/oidc/start").status_code, 404)
        self.as_("admin")
        Settings.objects.update(base_url="")
        bad = self.j("put", "/api/admin/settings", {"oidc_enabled": True}, status=400)
        self.assertEqual(bad["fields"]["oidc_enabled"], "oidc_incomplete")
