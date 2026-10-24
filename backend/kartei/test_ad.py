"""AD user import and AD contact sync against a small in-memory stand-in for a python-ldap connection."""
from datetime import timedelta
from unittest import mock

import ldap
import ldap.filter
from django.contrib.auth.models import User
from django.utils import timezone
from ldap.controls import SimplePagedResultsControl
from ldap.dn import str2dn

from . import adsync, ldapusers
from .auth import role_of
from .management.commands import export_loop
from .models import AuditEntry, FieldDef, Profile, Record, Role, Settings
from .tests import ApiTestBase, example

OU = "OU=Kartei,DC=ex,DC=local"
G = {"admin": "CN=K-Admin,DC=ex,DC=local", "maintainer": "CN=K-Maint,DC=ex,DC=local", "read": "CN=K-Read,DC=ex,DC=local"}


class FakeLdap:
    """entries: {dn: {attr: [bytes]}}; groups: {group dn: [user dn]} (transitive members). Pages of 2 entries."""

    def __init__(self):
        self.entries, self.groups, self.ops, self.binds, self.fail = {}, {}, [], [], set()

    def set_option(self, *a):
        pass

    def start_tls_s(self):
        pass

    def simple_bind_s(self, dn, pw):
        self.binds.append(dn)

    def search_ext(self, base, scope, flt, attrs, serverctrls=()):
        if "memberOf:1.2.840.113556.1.4.1941:=" in flt:
            group = next(g for g in self.groups if ldap.filter.escape_filter_chars(g) in flt)
            hits = [(dn, self.entries[dn]) for dn in self.groups[group]]
        else:
            assert scope == ldap.SCOPE_ONELEVEL
            hits = [(dn, a) for dn, a in self.entries.items() if dn.lower().endswith("," + base.lower())]
        start = int(serverctrls[0].cookie or 0)
        self._page = (hits[start:start + 2], str(start + 2).encode() if start + 2 < len(hits) else b"")
        return 1

    def result3(self, msgid):
        data, cookie = self._page
        return 101, data, msgid, [SimplePagedResultsControl(True, size=2, cookie=cookie)]

    def search_s(self, dn, scope, flt, attrs):  # role_of: nested membership check of one user
        return [(dn, {})] if any(ldap.filter.escape_filter_chars(g) in flt and dn in m for g, m in self.groups.items()) else []

    def _op(self, kind, dn):
        self.ops.append((kind, dn))
        if dn in self.fail:
            raise ldap.CONSTRAINT_VIOLATION({"desc": "Constraint violation", "info": "too long"})

    def add_s(self, dn, modlist):
        self._op("add", dn)
        self.entries[dn] = dict(modlist)

    def modify_s(self, dn, mods):
        self._op("modify", dn)
        e = self.entries[dn]
        for op, k, v in mods:
            if op == ldap.MOD_DELETE:
                e.pop(next(x for x in e if x.lower() == k.lower()))
            else:
                e[k] = v

    def rename_s(self, dn, newrdn, newsuperior=None, delold=1):
        self._op("rename", dn)
        e = self.entries.pop(dn)
        e["cn"] = [str2dn(newrdn)[0][0][1].encode()]
        self.entries[f"{newrdn},{dn.split(',', 1)[1]}"] = e

    def delete_s(self, dn):
        self._op("delete", dn)
        del self.entries[dn]


class AdTestBase(ApiTestBase):
    def setUp(self):
        super().setUp()
        s = Settings.get()
        s.ldap_uri, s.ldap_bind_dn, s.ldap_user_base = "ldaps://dc", "CN=svc,DC=ex,DC=local", "DC=ex,DC=local"
        s.ldap_bind_password = "pw"
        s.ldap_group_admin, s.ldap_group_maintainer, s.ldap_group_read = G["admin"], G["maintainer"], G["read"]
        s.save()
        self.fake = FakeLdap()
        patcher = mock.patch("ldap.initialize", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)


def user_entry(sam, first, last):
    return {"sAMAccountName": [sam.encode()], "givenName": [first.encode()], "sn": [last.encode()],
            "mail": [f"{sam.lower()}@ex.de".encode()]}


class UserImportTests(AdTestBase):
    def setUp(self):
        super().setUp()
        for sam, first, last in [("MMuster", "Max", "Muster"), ("EBoss", "Eva", "Boss"), ("read", "Local", "Clash"),
                                 ("LLeser", "Lea", "Leser")]:
            self.fake.entries[f"CN={first} {last},OU=Users,DC=ex,DC=local"] = user_entry(sam, first, last)
        dn = lambda first, last: f"CN={first} {last},OU=Users,DC=ex,DC=local"
        self.fake.groups = {G["admin"]: [dn("Eva", "Boss")], G["maintainer"]: [dn("Max", "Muster"), dn("Eva", "Boss")],
                            G["read"]: [dn("Local", "Clash"), dn("Lea", "Leser")]}

    def test_import_creates_updates_and_deactivates(self):
        st = ldapusers.run()
        self.assertEqual((st["created"], st["updated"], st["deactivated"], st["skipped_local"]), (3, 0, 0, 1))
        eva = User.objects.get(username="eboss")  # lower-case like django-auth-ldap
        self.assertEqual((eva.first_name, eva.email, eva.profile.role, eva.profile.source), ("Eva", "eboss@ex.de", "admin", "ldap"))
        self.assertFalse(eva.has_usable_password())
        self.assertEqual(User.objects.get(username="mmuster").profile.role, "maintainer")
        local = User.objects.get(username="read")  # local user with the same name: untouched
        self.assertEqual((local.first_name, local.profile.source), ("", "local"))
        self.assertTrue(AuditEntry.objects.filter(action="create", target_type="user", target_label="eboss").exists())

        self.assertEqual(ldapusers.run()["updated"], 0)  # nothing changed
        self.fake.groups[G["admin"]] = []
        self.fake.groups[G["read"]].remove("CN=Lea Leser,OU=Users,DC=ex,DC=local")
        st = ldapusers.run()
        self.assertEqual((st["updated"], st["deactivated"]), (1, 1))
        self.assertEqual(User.objects.get(username="eboss").profile.role, "maintainer")
        self.assertFalse(User.objects.get(username="lleser").is_active)
        self.assertTrue(User.objects.get(username="read").is_active)  # local users are never deactivated
        self.fake.groups[G["read"]].append("CN=Lea Leser,OU=Users,DC=ex,DC=local")
        self.assertEqual(ldapusers.run()["updated"], 1)
        self.assertTrue(User.objects.get(username="lleser").is_active)

    def test_nobody_found_changes_nothing(self):
        ldapusers.run()
        self.fake.groups = {g: [] for g in G.values()}
        self.assertIn("@ldap_users_none", ldapusers.run()["error"])
        self.assertTrue(User.objects.get(username="eboss").is_active)
        s = Settings.get()
        s.ldap_group_admin = s.ldap_group_maintainer = s.ldap_group_read = ""
        s.save()
        self.assertIn("@ldap_users_not_configured", ldapusers.run()["error"])

    def test_username_attribute_from_filter(self):
        s = Settings.get()
        s.ldap_user_filter = "(&(objectClass=user)(userPrincipalName=%(user)s))"
        self.assertEqual(ldapusers.username_attr(s), "userPrincipalName")
        s.ldap_user_filter = "(sAMAccountName=%(user)s)"
        self.assertEqual(ldapusers.username_attr(s), "sAMAccountName")

    def test_daily_in_tick_and_button(self):
        export_loop.tick()
        self.assertTrue(User.objects.filter(username="eboss").exists())
        self.assertFalse(ldapusers.due(Settings.get()))
        Settings.objects.filter(pk=1).update(ldap_users_status={"at": (timezone.now() - timedelta(hours=25)).isoformat()})
        self.assertTrue(ldapusers.due(Settings.get()))
        self.as_("admin")
        r = self.j("post", "/api/admin/ldap/import-users")
        self.assertEqual(r["updated"], 0)
        self.assertEqual(self.j("get", "/api/admin/settings")["ldap_users_status"]["at"], r["at"])
        self.as_("maintainer")
        self.j("post", "/api/admin/ldap/import-users", status=403)

    def test_login_role_uses_nested_groups(self):
        s, dn = Settings.get(), "CN=Max Muster,OU=Users,DC=ex,DC=local"
        self.assertEqual(role_of(self.fake, s, dn, []), Role.MAINTAINER)  # only via (nested) search
        self.assertEqual(role_of(self.fake, s, dn, [G["read"].encode()]), Role.MAINTAINER)  # highest wins
        self.assertEqual(role_of(self.fake, s, dn, [G["admin"]]), Role.ADMIN)
        self.assertIsNone(role_of(self.fake, s, "CN=Nobody,DC=ex,DC=local", []))

    def test_ldap_users_active_flag_is_managed_by_ad(self):
        ldapusers.run()
        self.as_("admin")
        u = User.objects.get(username="mmuster")
        r = self.j("patch", f"/api/admin/users/{u.id}", {"is_active": False}, status=400)
        self.assertEqual(r["fields"], {"is_active": "ldap_managed"})
        self.j("patch", f"/api/admin/users/{u.id}", {"is_active": True, "language": "en"})  # unchanged: fine


class AdSyncTests(AdTestBase):
    def setUp(self):
        super().setUp()
        s = Settings.get()
        s.ad_enabled, s.ad_ou = True, OU
        s.ad_columns = example("ad-mapping.json")["columns"]  # empty by default
        s.save()
        self.meier = Record.objects.create(kind="person", first_name="Anna", last_name="Meier",
                                           data={"phone_work": "+49 511 1", "mobile": "+49 170 2", "job_title": "CEO"})
        self.acme = Record.objects.create(kind="company", name="ACME, Inc.", data={"company_phone": "+49 511 0"})
        self.meier.company = self.acme
        self.meier.save()

    def entry(self, uid):
        return next((dn, e) for dn, e in self.fake.entries.items() if e.get("adminDescription") == [f"kartei:{uid}".encode()])

    def test_create_update_rename_delete(self):
        self.fake.entries[f"CN=Fremd,{OU}"] = {"cn": [b"Fremd"], "telephoneNumber": [b"1"]}  # not ours
        dry = self.j_dry()
        self.assertEqual((dry["created"], dry["deleted"]), (2, 0))
        self.assertEqual(self.fake.ops, [])  # dry run writes nothing
        st = adsync.run()
        self.assertEqual((st["created"], st["updated"], st["failed"]), (2, 0, []))
        self.assertEqual(self.fake.binds[-1], "CN=svc,DC=ex,DC=local")  # falls back to the LDAP service account
        dn, e = self.entry(self.acme.uid)
        self.assertEqual(dn, rf"CN=ACME\, Inc.,{OU}")  # DN special characters escaped
        self.assertEqual((e["objectClass"], e["cn"], e["company"], e["telephoneNumber"]),
                         ([b"contact"], [b"ACME, Inc."], [b"ACME, Inc."], [b"+49 511 0"]))
        dn, e = self.entry(self.meier.uid)
        self.assertEqual((e["givenName"], e["sn"], e["displayName"], e["company"], e["title"], e["mobile"]),
                         ([b"Anna"], [b"Meier"], [b"Anna Meier"], [b"ACME, Inc."], [b"CEO"], [b"+49 170 2"]))
        self.assertNotIn("homePhone", e)

        self.fake.ops = []
        self.assertEqual(adsync.run()["unchanged"], 2)
        self.assertEqual(self.fake.ops, [])

        self.meier.data = {"phone_work": "+49 511 9", "job_title": "CEO"}  # changed + removed
        self.meier.last_name = "Schulz"
        self.meier.save()
        st = adsync.run()
        self.assertEqual((st["renamed"], st["updated"], st["unchanged"]), (1, 1, 1))
        dn, e = self.entry(self.meier.uid)
        self.assertEqual((dn, e["cn"], e["sn"], e["telephoneNumber"]), (f"CN=Anna Schulz,{OU}", [b"Anna Schulz"], [b"Schulz"], [b"+49 511 9"]))
        self.assertNotIn("mobile", e)

        self.meier.deleted_at = timezone.now()
        self.meier.save()
        s = Settings.get()
        st = adsync.run()  # 1 of 2 = 50 % > 10 %
        self.assertIn("@ad_too_many_deletes", st["error"])
        s.ad_max_shrink_percent = 50
        s.save()
        self.assertEqual(adsync.run()["deleted"], 1)
        self.assertEqual(sorted(self.fake.entries), sorted([f"CN=Fremd,{OU}", rf"CN=ACME\, Inc.,{OU}"]))
        self.assertEqual(self.fake.entries[f"CN=Fremd,{OU}"], {"cn": [b"Fremd"], "telephoneNumber": [b"1"]})
        self.assertEqual(Settings.get().ad_status["deleted"], 1)

    def j_dry(self):
        self.as_("admin")
        return self.j("post", "/api/admin/ad/dry-run")

    def test_cn_collisions_and_length(self):
        self.fake.entries[f"CN=Anna Meier,{OU}"] = {"cn": [b"Anna Meier"]}  # someone else's object
        twin = Record.objects.create(kind="person", first_name="Anna", last_name="Meier")
        long = Record.objects.create(kind="person", first_name="A" * 40, last_name="B" * 40)
        adsync.run()
        cns = sorted(self.entry(r.uid)[1]["cn"][0].decode() for r in (self.meier, twin))
        self.assertEqual(cns, ["Anna Meier (2)", "Anna Meier (3)"])
        self.assertEqual(len(self.entry(long.uid)[1]["cn"][0]), 64)
        self.fake.ops = []
        adsync.run()
        self.assertEqual(self.fake.ops, [])  # suffixed or shortened names are stable

    def test_guards_and_failures(self):
        Record.objects.all().delete()
        self.assertIn("@ad_no_records", adsync.run()["error"])
        Record.objects.create(kind="person", first_name="X", last_name="Y")
        self.fake.fail.add(f"CN=X Y,{OU}")
        st = adsync.run()
        self.assertEqual((st["created"], st["failed"]), (0, ["X Y: Constraint violation – too long"]))
        s = Settings.get()
        s.ad_enabled = False
        s.save()
        self.assertIsNone(adsync.run())

    def test_separate_bind_account_and_kinds(self):
        s = Settings.get()
        s.ad_bind_dn, s.ad_bind_password, s.ad_kinds = "CN=writer,DC=ex,DC=local", "w", "company"
        s.save()
        self.assertEqual(adsync.run()["created"], 1)
        self.assertEqual(self.fake.binds[-1], "CN=writer,DC=ex,DC=local")

    def test_settings_api(self):
        self.as_("admin")
        s = self.j("get", "/api/admin/settings")
        self.assertEqual(s["ad_columns"][0], {"attr": "givenName", "person": "core:first_name", "company": "field:short_name"})
        r = self.j("put", "/api/admin/settings", {"ad_columns": [{"attr": "cn", "person": "core:name", "company": ""}]}, status=400)
        self.assertEqual(r["fields"], {"ad_columns": "invalid_attr:cn"})
        r = self.j("put", "/api/admin/settings", {"ad_ou": "", "ad_enabled": True}, status=400)
        self.assertEqual(r["fields"], {"ad_enabled": "ad_incomplete"})
        s = self.j("put", "/api/admin/settings", {"ad_bind_password": "geheim", "ad_max_shrink_percent": 20})
        self.assertTrue(s["ad_bind_password_set"])
        self.assertEqual(AuditEntry.objects.filter(target_type="settings").first().changes["ad_bind_password_enc"], ["***", "***"])
        s = self.j("post", "/api/admin/ad/sync")
        self.assertTrue(s["ad_sync_requested"])
        adsync.run()  # what the exporter does when it sees the request
        self.assertIsNone(Settings.get().ad_sync_requested)
        Settings.objects.filter(pk=1).update(ad_enabled=False)
        self.j("post", "/api/admin/ad/sync", status=409)
