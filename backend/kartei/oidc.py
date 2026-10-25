"""Single sign-on with any OpenID Connect provider (Entra ID, Keycloak, Authentik, Okta, …): authorization code flow
with PKCE, endpoints from the provider's discovery document.

The ID token comes straight from the token endpoint over TLS, which OpenID Connect Core 3.1.3.7 accepts in place of
a signature check; issuer (exactly the discovery issuer), audience, expiry and nonce are still checked. Nobody is
created here: users come from SCIM (scim.py) or LDAP beforehand. Only active SCIM or LDAP users can sign in this
way, never local users or superusers. The first time, the configured claim must equal the SCIM user name (or the
directory email of an LDAP user) of exactly one of them; then the account's issuer + subject are stored, and from
then on only they count. The role stays as SCIM groups or LDAP groups set it.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Q

from .graph import GraphError, http
from .models import Profile, Settings

CLAIMS = ("preferred_username", "email", "upn")


class SignInError(Exception):
    """code: shown on the login page as err.<code>"""


def configured(s):
    return bool(s.oidc_enabled and s.oidc_issuer.startswith("https://") and s.oidc_client_id and s.oidc_client_secret
                and s.base_url)


def redirect_uri(s):
    return s.base_url.rstrip("/") + "/api/oidc/callback"


def discovery(s):
    """The provider's metadata, cached for 10 minutes. Its issuer must be the configured one (OIDC Discovery 4.3)."""
    issuer = s.oidc_issuer.rstrip("/")
    key = "oidc-discovery:" + hashlib.sha256(issuer.encode()).hexdigest()
    if (meta := cache.get(key)) is None:
        try:
            meta = http("GET", issuer + "/.well-known/openid-configuration")
        except GraphError:
            raise SignInError("sso_failed")
        if (str(meta.get("issuer", "")).rstrip("/") != issuer
                or not all(str(meta.get(k, "")).startswith("https://") for k in ("authorization_endpoint", "token_endpoint"))):
            raise SignInError("sso_invalid")
        cache.set(key, meta, 600)
    return meta


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def start(session, s):
    """The provider's sign-in URL; state, nonce and PKCE verifier wait in the session for the callback."""
    meta = discovery(s)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    session["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier, "at": int(time.time())}
    return meta["authorization_endpoint"] + "?" + urlencode({
        "client_id": s.oidc_client_id, "response_type": "code", "response_mode": "query",
        "redirect_uri": redirect_uri(s), "scope": s.oidc_scopes, "state": state, "nonce": nonce,
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
    meta = discovery(s)
    try:
        tok = http("POST", meta["token_endpoint"], form={
            "client_id": s.oidc_client_id, "client_secret": s.oidc_client_secret, "grant_type": "authorization_code",
            "code": code, "redirect_uri": redirect_uri(s), "code_verifier": pending["verifier"]})
    except GraphError:
        raise SignInError("sso_failed")
    c = _claims(tok.get("id_token", ""))
    aud = c.get("aud")
    sub = str(c.get("sub") or "")
    if (c.get("iss") != meta["issuer"] or s.oidc_client_id not in (aud if isinstance(aud, list) else [aud])
            or float(c.get("exp", 0)) < time.time() or not hmac.compare_digest(str(c.get("nonce", "")), pending["nonce"])
            or not sub):
        raise SignInError("sso_invalid")
    # Entra ID: a guest from another directory signs in with its own name; refused even if it was provisioned
    if c["iss"].startswith("https://login.microsoftonline.com/") and c.get("idp") and c["idp"] not in (
            c["iss"], f"https://sts.windows.net/{c.get('tid')}/"):
        raise SignInError("sso_unknown_user")
    subject = f"{c['iss']} {sub}"
    eligible = User.objects.filter(is_active=True, is_superuser=False, profile__source__in=("scim", "ldap"))
    if bound := Profile.objects.filter(sso_subject=subject).first():
        if not eligible.filter(pk=bound.user_id).exists():
            raise SignInError("sso_unknown_user")
        return bound.user
    name = str(c.get(s.oidc_claim if s.oidc_claim in CLAIMS else "preferred_username") or "").strip()
    match = Q(profile__source="scim", username__iexact=name)
    if "@" in name:
        match |= Q(profile__source="ldap", email__iexact=name)
    users = list(eligible.filter(match, profile__sso_subject="")[:2]) if name else []
    if len(users) != 1:
        raise SignInError("sso_unknown_user" if not users else "sso_ambiguous")
    Profile.objects.filter(user=users[0]).update(sso_subject=subject)
    return users[0]
