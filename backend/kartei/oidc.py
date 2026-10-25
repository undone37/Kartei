"""Sign in with Microsoft (Entra ID, OpenID Connect authorization code flow with PKCE).

Uses the app registration of the Outlook sync (tenant, client id, client secret). The ID token comes straight from the
token endpoint over TLS, which OpenID Connect Core 3.1.3.7 accepts in place of a signature check; issuer, audience,
tenant, expiry and nonce are still checked. Nobody is created here: the Microsoft account must match an existing,
active Kartei user by email or user name, and the role stays as it is (LDAP groups or the user list).
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote, urlencode

from django.contrib.auth.models import User
from django.db.models import Q

from .graph import GraphError, http
from .models import Settings

LOGIN = "https://login.microsoftonline.com"


class SignInError(Exception):
    """code: shown on the login page as err.<code>"""


def configured(s):
    return bool(s.oidc_enabled and s.graph_tenant_id and s.graph_client_id and s.graph_client_secret and s.base_url)


def redirect_uri(s):
    return s.base_url.rstrip("/") + "/api/oidc/callback"


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def start(session, s):
    """The Microsoft sign-in URL; state, nonce and PKCE verifier wait in the session for the callback."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    session["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier, "at": int(time.time())}
    return f"{LOGIN}/{quote(s.graph_tenant_id)}/oauth2/v2.0/authorize?" + urlencode({
        "client_id": s.graph_client_id, "response_type": "code", "response_mode": "query",
        "redirect_uri": redirect_uri(s), "scope": "openid profile email", "state": state, "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
        "prompt": "select_account"})


def _claims(id_token):
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise SignInError("sso_invalid")


def finish(session, s, code, state):
    """The Kartei user for the callback's code, or SignInError."""
    pending = session.pop("oidc", None)
    if not pending or not state or not hmac.compare_digest(pending["state"], state) or time.time() - pending["at"] > 600:
        raise SignInError("sso_expired")
    try:
        tok = http("POST", f"{LOGIN}/{quote(s.graph_tenant_id)}/oauth2/v2.0/token", form={
            "client_id": s.graph_client_id, "client_secret": s.graph_client_secret, "grant_type": "authorization_code",
            "code": code, "redirect_uri": redirect_uri(s), "code_verifier": pending["verifier"], "scope": "openid profile email"})
    except GraphError:
        raise SignInError("sso_failed")
    c = _claims(tok.get("id_token", ""))
    tid = c.get("tid", "")
    if (c.get("aud") != s.graph_client_id or c.get("iss") != f"{LOGIN}/{tid}/v2.0"
            or (len(s.graph_tenant_id) == 36 and tid != s.graph_tenant_id)  # a tenant id (not a domain) is compared too
            or float(c.get("exp", 0)) < time.time() or not hmac.compare_digest(str(c.get("nonce", "")), pending["nonce"])):
        raise SignInError("sso_invalid")
    names = {str(c[k]).strip().lower() for k in ("preferred_username", "email", "upn") if c.get(k)}
    if not names:
        raise SignInError("sso_unknown_user")
    local = {n.split("@")[0] for n in names}
    match = Q()
    for n in names:
        match |= Q(email__iexact=n) | Q(username__iexact=n)
    for n in local:
        match |= Q(username__iexact=n)
    users = list(User.objects.filter(match, is_active=True).distinct()[:2])
    if len(users) != 1:
        raise SignInError("sso_unknown_user" if not users else "sso_ambiguous")
    return users[0]
