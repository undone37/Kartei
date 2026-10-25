"""LDAP backend configured from the DB (kartei.Settings) instead of Django settings."""
import hashlib
import logging
import tempfile
from pathlib import Path

import ldap
from django_auth_ldap.backend import LDAPBackend, LDAPSettings, _LDAPUser
from django_auth_ldap.config import LDAPSearch
from ldap.filter import escape_filter_chars

from . import audit
from .models import Profile, Role, Settings

log = logging.getLogger(__name__)


def ldap_settings(s):
    opts = {ldap.OPT_REFERRALS: 0, ldap.OPT_NETWORK_TIMEOUT: 5}
    if s.ldap_ca_cert.strip():
        pem = s.ldap_ca_cert.strip() + "\n"
        path = Path(tempfile.gettempdir()) / f"kartei-ldap-ca-{hashlib.sha256(pem.encode()).hexdigest()[:16]}.pem"
        if not path.exists():
            path.write_text(pem)
        opts[ldap.OPT_X_TLS_CACERTFILE] = str(path)
        opts[ldap.OPT_X_TLS_REQUIRE_CERT] = ldap.OPT_X_TLS_DEMAND
        opts[ldap.OPT_X_TLS_NEWCTX] = 0  # must be last
    conf = LDAPSettings()
    conf.SERVER_URI = s.ldap_uri
    conf.START_TLS = s.ldap_start_tls
    conf.BIND_DN = s.ldap_bind_dn
    conf.BIND_PASSWORD = s.ldap_bind_password
    conf.CONNECTION_OPTIONS = opts
    conf.USER_SEARCH = LDAPSearch(s.ldap_user_base, ldap.SCOPE_SUBTREE, s.ldap_user_filter)
    conf.USER_ATTR_MAP = {"first_name": "givenName", "last_name": "sn", "email": "mail"}
    conf.ALWAYS_UPDATE_USER = True
    return conf


def role_groups(s):
    """[(role, group dn)], highest role first."""
    return [(role, dn.strip()) for role, dn in [(Role.ADMIN, s.ldap_group_admin), (Role.MAINTAINER, s.ldap_group_maintainer),
                                                (Role.READ, s.ldap_group_read)] if dn and dn.strip()]


def role_from_groups(s, member_of):
    """Role from direct memberOf values (used by the settings test)."""
    groups = {(g.decode() if isinstance(g, bytes) else g).lower() for g in member_of}
    return next((role for role, dn in role_groups(s) if dn.lower() in groups), None)


def role_of(conn, s, dn, member_of=()):
    """Highest role whose group contains dn directly or nested; same rule as the user import (ldapusers.members)."""
    direct = role_from_groups(s, member_of)
    for role, group in role_groups(s):
        if role == direct:
            return role
        # ponytail: AD-only matching rule (LDAP_MATCHING_RULE_IN_CHAIN); other servers just see direct membership
        if conn.search_s(dn, ldap.SCOPE_BASE, f"(memberOf:1.2.840.113556.1.4.1941:={escape_filter_chars(group)})", ["1.1"]):
            return role
    return None


class DbLDAPBackend(LDAPBackend):
    @property
    def settings(self):
        if self._settings is None:
            self._settings = ldap_settings(Settings.get())
        return self._settings

    @settings.setter
    def settings(self, value):
        self._settings = value

    def get_user(self, user_id):
        # django-auth-ldap doesn't check is_active here: a user deactivated by the user import kept an open session
        user = super().get_user(user_id)
        return user if user and user.is_active else None

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not Settings.get().ldap_uri or not password:
            return None
        self._settings = None  # admin may have changed settings since last login
        return super().authenticate(request, username=username, password=password, **kwargs)

    def get_or_build_user(self, username, ldap_user):
        user, built = super().get_or_build_user(username, ldap_user)
        if not built and getattr(user, "profile", None) and user.profile.source != "ldap":
            # never let a directory account take over a local (fallback/admin) or SCIM account
            raise _LDAPUser.AuthenticationFailed("local account with same username")
        return user, built

    def authenticate_ldap_user(self, ldap_user, password):
        user = super().authenticate_ldap_user(ldap_user, password)
        if user is None:
            return None
        role = role_of(ldap_user.connection, Settings.get(), ldap_user.dn, ldap_user.attrs.get("memberOf", []))
        if role is None:
            log.info("LDAP user %s has no Kartei group, login refused", user.username)
            return None
        Profile.objects.update_or_create(user=user, defaults={"role": role, "source": "ldap"})
        if not user.is_active:  # deactivated by the user import, back in a role group now
            user.is_active = True
            user.save(update_fields=["is_active"])
            audit.log(user, "update", "user", user.id, user.username, {"is_active": [False, True]})
        return user
