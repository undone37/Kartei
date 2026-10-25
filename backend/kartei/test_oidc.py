"""Single sign-on (OpenID Connect): discovery, state/PKCE in the session, token checks, matching to a provisioned user."""
import base64
import json
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.cache import cache

from .graph import GraphError
from .models import AuditEntry, Profile, Settings
from .tests import ApiTestBase

ISSUER, CLIENT = "https://id.example.com/realms/staff", "kartei"
META = {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/auth", "token_endpoint": ISSUER + "/token"}


def id_token(**claims):
    body = {"iss": ISSUER, "aud": CLIENT, "sub": "sub-1", "exp": time.time() + 600,
            "preferred_username": "maintainer@example.com"} | claims
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256'})}.{enc(body)}.signature"


class OidcTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()  # discovery
        s = Settings.get()
        s.oidc_issuer, s.oidc_client_id, s.oidc_client_secret = ISSUER, CLIENT, "secret"
        s.base_url, s.oidc_enabled = "https://kartei.example", True
        s.save()
        # "maintainer" was provisioned by SCIM, "read" comes from LDAP
        User.objects.filter(username="maintainer").update(username="maintainer@example.com")
        Profile.objects.filter(user__username="maintainer@example.com").update(source="scim")
        User.objects.filter(username="read").update(email="read@example.com")
        Profile.objects.filter(user__username="read").update(source="ldap")
        self.meta = META

    def fake_http(self, token=None, error=None):
        def http(method, url, **kw):
            if method == "GET":
                self.assertEqual(url, ISSUER + "/.well-known/openid-configuration")
                return self.meta
            self.assertEqual(url, META["token_endpoint"])
            if error:
                raise error
            return {"id_token": token}
        return mock.patch("kartei.oidc.http", side_effect=http)

    def start(self):
        with self.fake_http():
            r = self.client.get("/api/oidc/start")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(META["authorization_endpoint"] + "?"))
        q = parse_qs(urlparse(r["Location"]).query)
        self.assertEqual(q["redirect_uri"], ["https://kartei.example/api/oidc/callback"])
        self.assertEqual((q["code_challenge_method"], q["client_id"], q["scope"]), (["S256"], [CLIENT], ["openid profile email"]))
        return q["state"][0], q["nonce"][0]

    def callback(self, state, token=None, error=None):
        with self.fake_http(token, error) as http:
            r = self.client.get("/api/oidc/callback", {"code": "the-code", "state": state})
        return r, http

    def sso(self, **claims):
        state, nonce = self.start()
        return self.callback(state, id_token(**({"nonce": nonce} | claims)))[0]["Location"]

    def who(self):
        return self.client.get("/api/session").json().get("user", {}).get("username")

    def test_signs_in_a_provisioned_user(self):
        self.assertTrue(self.client.get("/api/session").json()["sso"])
        state, nonce = self.start()
        r, http = self.callback(state, id_token(nonce=nonce, aud=[CLIENT, "other"]))
        self.assertEqual(r["Location"], "/")
        form = http.call_args.kwargs["form"]
        self.assertEqual((form["code"], form["grant_type"], form["client_secret"]), ("the-code", "authorization_code", "secret"))
        self.assertTrue(form["code_verifier"])  # PKCE
        self.assertEqual(self.who(), "maintainer@example.com")
        self.assertTrue(AuditEntry.objects.filter(action="login", username="maintainer@example.com").exists())
        self.client.logout()
        self.assertEqual(self.sso(sub="sub-2", preferred_username="read@example.com"), "/")  # LDAP: by directory email
        self.assertEqual(self.who(), "read")

    def test_refuses_bad_state_tokens_and_unknown_users(self):
        state, nonce = self.start()
        self.assertIn("sso_expired", self.callback("forged", id_token(nonce=nonce))[0]["Location"])  # state is used up too
        for claims, code in (({"nonce": "other"}, "sso_invalid"), ({"aud": "someone-else"}, "sso_invalid"),
                             ({"iss": ISSUER + "/"}, "sso_invalid"), ({"iss": "https://evil.example.com"}, "sso_invalid"),
                             ({"exp": time.time() - 1}, "sso_invalid"), ({"sub": ""}, "sso_invalid"),
                             ({"preferred_username": "stranger@example.com"}, "sso_unknown_user")):
            self.assertEqual(self.sso(**claims), f"/?login_error={code}", claims)
        state, _ = self.start()
        self.assertEqual(self.callback(state, error=GraphError("HTTP 400"))[0]["Location"], "/?login_error=sso_failed")
        self.assertIsNone(self.who())
        r = self.client.get("/api/oidc/callback", {"error": "access_denied"})
        self.assertEqual(r["Location"], "/?login_error=sso_cancelled")

    def test_discovery_must_name_the_configured_issuer(self):
        for meta in (META | {"issuer": "https://other.example.com"}, META | {"token_endpoint": "http://id.example.com/token"}):
            cache.clear()
            self.meta = meta
            with self.fake_http():
                self.assertEqual(self.client.get("/api/oidc/start")["Location"], "/?login_error=sso_invalid")

    def test_only_provisioned_users_then_bound_to_the_account(self):
        self.assertEqual(self.sso(preferred_username="MAINTAINER"), "/?login_error=sso_unknown_user")  # no partial match
        self.assertEqual(self.sso(preferred_username="read"), "/?login_error=sso_unknown_user")  # LDAP: email only
        self.assertEqual(self.sso(preferred_username="x@example.com", email="read@example.com"), "/?login_error=sso_unknown_user")
        for username in ("admin", "editor"):  # a superuser, a local user
            User.objects.create_user(username) if username == "editor" else None
            u = User.objects.get(username=username)
            Profile.objects.update_or_create(user=u, defaults={"source": "scim" if u.is_superuser else "local"})
            User.objects.filter(pk=u.pk).update(email="who@example.com")
            self.assertEqual(self.sso(preferred_username=username), "/?login_error=sso_unknown_user", username)
            self.assertEqual(self.sso(preferred_username="who@example.com"), "/?login_error=sso_unknown_user", username)
        self.assertEqual(self.sso(), "/")
        self.assertEqual(Profile.objects.get(user__username="maintainer@example.com").sso_subject, f"{ISSUER} sub-1")
        self.client.logout()
        # bound: a renamed account still gets in, another account with the same name doesn't
        self.assertEqual(self.sso(preferred_username="renamed@example.com"), "/")
        self.client.logout()
        self.assertEqual(self.sso(sub="sub-9"), "/?login_error=sso_unknown_user")
        User.objects.filter(username="maintainer@example.com").update(is_active=False)
        self.assertEqual(self.sso(), "/?login_error=sso_unknown_user")

    def test_entra_guests_are_refused(self):
        tenant = "11111111-2222-3333-4444-555555555555"
        issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
        Settings.objects.update(oidc_issuer=issuer)
        self.meta = META | {"issuer": issuer}
        global ISSUER
        old, ISSUER = ISSUER, issuer
        try:
            with mock.patch("kartei.oidc.http", side_effect=lambda m, u, **k: self.meta if m == "GET" else self.tok):
                for idp, ok in (("https://sts.windows.net/99999999-2222-3333-4444-555555555555/", False), (None, True)):
                    r = self.client.get("/api/oidc/start")
                    q = parse_qs(urlparse(r["Location"]).query)
                    self.tok = {"id_token": id_token(nonce=q["nonce"][0], tid=tenant, **({"idp": idp} if idp else {}))}
                    loc = self.client.get("/api/oidc/callback", {"code": "c", "state": q["state"][0]})["Location"]
                    self.assertEqual(loc, "/" if ok else "/?login_error=sso_unknown_user")
        finally:
            ISSUER = old

    def test_off_or_incomplete(self):
        Settings.objects.update(oidc_enabled=False)
        self.assertFalse(self.client.get("/api/session").json()["sso"])
        self.assertEqual(self.client.get("/api/oidc/start").status_code, 404)
        self.as_("admin")
        Settings.objects.update(base_url="")
        bad = self.j("put", "/api/admin/settings", {"oidc_enabled": True}, status=400)["fields"]
        self.assertEqual(bad["oidc_enabled"], "oidc_incomplete")
        bad = self.j("put", "/api/admin/settings", {"oidc_issuer": "http://id.example.com", "oidc_claim": "sub",
                                                     "oidc_scopes": "profile"}, status=400)["fields"]
        self.assertEqual(bad, {"oidc_issuer": "https_required", "oidc_claim": "invalid", "oidc_scopes": "openid_required"})
        r = self.j("put", "/api/admin/settings", {"oidc_label": "Sign in with Example ID", "oidc_client_secret": "new"})
        self.assertTrue(r["oidc_client_secret_set"])
        self.assertNotIn("new", json.dumps(r))
        self.assertEqual(self.client.get("/api/session").json()["sso_label"], "Sign in with Example ID")
