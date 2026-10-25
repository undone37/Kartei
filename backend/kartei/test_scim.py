"""SCIM provisioning, replayed the way Entra ID (Microsoft's provisioning service) talks to an app."""
import json

from django.contrib.auth.models import User
from django.core.cache import cache

from .models import AuditEntry, Role, ScimGroup
from .tests import ApiTestBase

PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ALICE = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User", "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"],
    "externalId": "alice", "userName": "alice@example.com", "active": True, "displayName": "Alice Example",
    "emails": [{"primary": True, "type": "work", "value": "alice@example.com"}], "meta": {"resourceType": "User"},
    "name": {"formatted": "Alice Example", "familyName": "Example", "givenName": "Alice"}, "title": "Buyer"}


class ScimTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.as_("admin")
        self.token = self.j("post", "/api/admin/scim/token")["token"]
        self.client.logout()

    def scim(self, method, path, body=None, status=200, token=None):
        r = getattr(self.client, method)("/scim/v2/" + path, json.dumps(body) if body is not None else "",
                                         content_type="application/scim+json",
                                         HTTP_AUTHORIZATION=f"Bearer {token or self.token}")
        self.assertEqual(r.status_code, status, r.content[:500])
        if r.content:
            self.assertEqual(r["Content-Type"], "application/scim+json")
            return r.json()

    def ops(self, *ops):
        return {"schemas": [PATCH], "Operations": [{"op": o, "path": p, "value": v} if p else {"op": o, "value": v}
                                                   for o, p, v in ops]}

    def alice(self):
        return User.objects.select_related("profile").get(username="alice@example.com")

    def map_group(self, role, gid):
        self.as_("admin")
        self.j("put", "/api/admin/settings", {f"scim_group_{role}": gid})
        self.client.logout()

    def test_token(self):
        self.assertEqual(self.scim("get", "Users", status=401, token="wrong")["status"], "401")
        self.assertEqual(self.client.get("/scim/v2/Users").status_code, 401)
        self.as_("maintainer")
        self.j("post", "/api/admin/scim/token", status=403)
        self.as_("admin")
        self.assertTrue(self.j("get", "/api/admin/settings")["scim_token_set"])
        new = self.j("post", "/api/admin/scim/token")["token"]
        self.assertNotIn(new, json.dumps(list(AuditEntry.objects.values_list("changes", flat=True))))
        self.scim("get", "Users", status=401)  # the old token is gone
        self.assertIsNone(self.j("get", "/api/admin/settings")["scim_seen_at"])  # failed attempts don't count
        self.scim("get", "Users", token=new)
        self.assertTrue(self.j("get", "/api/admin/settings")["scim_seen_at"])
        for path in ("ServiceProviderConfig", "ResourceTypes", "Schemas"):
            self.scim("get", path, token=new)

    def test_entra_provisioning_cycle(self):
        # "Test connection" and the first cycle: look up, create user, look up group, create group, add member
        self.assertEqual(self.scim("get", 'Users?filter=userName eq "8b1f6a5e-test"')["totalResults"], 0)
        self.assertEqual(self.scim("get", 'Users?filter=userName eq "alice@example.com"')["Resources"], [])
        uid = self.scim("post", "Users", ALICE, status=201)["id"]
        u = self.alice()
        self.assertEqual((u.first_name, u.last_name, u.email, u.profile.external_id, u.profile.source),
                         ("Alice", "Example", "alice@example.com", "alice", "scim"))
        self.assertFalse(u.is_active)  # in no mapped group yet
        self.assertFalse(u.has_usable_password())
        self.assertEqual(self.scim("get", 'Users?filter=externalId eq "alice"')["Resources"][0]["id"], uid)
        self.scim("get", 'Groups?excludedAttributes=members&filter=displayName eq "Kartei Editors"')
        gid = self.scim("post", "Groups", {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                                           "externalId": "g-1", "displayName": "Kartei Editors", "members": []}, status=201)["id"]
        self.map_group("maintainer", gid)
        self.scim("patch", f"Groups/{gid}", self.ops(("Add", "members", [{"value": uid}])))
        u = self.alice()
        self.assertTrue(u.is_active)
        self.assertEqual(u.profile.role, Role.MAINTAINER)
        self.assertEqual(self.scim("get", f"Groups/{gid}")["members"], [{"value": uid, "display": "alice@example.com"}])
        # changes
        self.scim("patch", f"Users/{uid}", self.ops(("Replace", 'emails[type eq "work"].value', "alice.new@example.com"),
                                                    ("Replace", "name.familyName", "Newname"),
                                                    ("Replace", None, {"name.givenName": "Ally", "displayName": "x"})))
        u = self.alice()
        self.assertEqual((u.first_name, u.last_name, u.email), ("Ally", "Newname", "alice.new@example.com"))
        # leaving: Entra sets active "False" (a string), later deletes
        self.scim("patch", f"Users/{uid}", self.ops(("Replace", "active", "False")))
        self.assertFalse(self.alice().is_active)
        self.assertFalse(self.scim("get", f"Users/{uid}")["active"])
        self.scim("patch", f"Users/{uid}", self.ops(("Replace", None, {"active": True})))
        self.assertTrue(self.alice().is_active)
        self.scim("patch", f"Groups/{gid}", self.ops(("Remove", f'members[value eq "{uid}"]', None)))
        self.assertFalse(self.alice().is_active)  # no role group left
        self.scim("delete", f"Users/{uid}", status=204)
        self.assertFalse(self.alice().profile.scim_active)  # never deleted: the history keeps the name
        log = AuditEntry.objects.filter(target_type="user", target_id=uid)
        self.assertEqual(set(log.values_list("username", flat=True)), {"SCIM"})
        self.assertIn(["Example", "Newname"], [e.changes.get("last_name") for e in log])

    def test_highest_role_wins_and_mapping_changes_apply(self):
        uid = self.scim("post", "Users", ALICE, status=201)["id"]
        read = self.scim("post", "Groups", {"displayName": "Staff", "members": [{"value": uid}]}, status=201)["id"]
        admins = self.scim("post", "Groups", {"displayName": "IT", "members": [{"value": uid}]}, status=201)["id"]
        self.map_group("read", read)
        self.assertEqual((self.alice().is_active, self.alice().profile.role), (True, Role.READ))
        self.map_group("admin", admins)
        self.assertEqual(self.alice().profile.role, Role.ADMIN)
        self.scim("delete", f"Groups/{admins}", status=204)
        self.assertEqual(self.alice().profile.role, Role.READ)
        self.assertFalse(ScimGroup.objects.filter(pk=admins).exists())
        for e in AuditEntry.objects.filter(target_type="group"):  # {key: [old, new]} like every audit entry
            self.assertTrue(all(isinstance(v, list) and len(v) == 2 for v in e.changes.values()), e.changes)
        self.scim("put", f"Groups/{read}", {"displayName": "Staff", "members": []})
        self.assertFalse(self.alice().is_active)

    def test_last_admin_is_kept(self):
        uid = self.scim("post", "Users", ALICE, status=201)["id"]
        gid = self.scim("post", "Groups", {"displayName": "IT", "members": [{"value": uid}]}, status=201)["id"]
        self.map_group("admin", gid)
        User.objects.filter(username="admin").update(is_active=False)  # the SCIM user is the only admin now
        self.scim("patch", f"Users/{uid}", self.ops(("replace", "active", False)))
        self.assertTrue(self.alice().is_active)
        self.assertEqual(self.alice().profile.role, Role.ADMIN)

    def test_local_and_ldap_users_are_out_of_reach(self):
        local = self.users["maintainer"]
        self.scim("get", f"Users/{local.id}", status=404)
        self.scim("patch", f"Users/{local.id}", self.ops(("replace", "active", False)), status=404)
        self.assertEqual(self.scim("post", "Users", ALICE | {"userName": "MAINTAINER"}, status=409)["scimType"], "uniqueness")
        self.assertEqual(self.scim("get", 'Users?filter=userName eq "maintainer"')["totalResults"], 0)
        uid = self.scim("post", "Users", ALICE, status=201)["id"]
        gid = self.scim("post", "Groups", {"displayName": "G", "members": [{"value": uid}, {"value": str(local.id)}]},
                        status=201)["id"]
        self.assertEqual([m["value"] for m in self.scim("get", f"Groups/{gid}")["members"]], [uid])
        self.assertEqual(self.scim("put", f"Users/{uid}", ALICE | {"userName": "maintainer"}, status=409)["status"], "409")
        # in Kartei, SCIM users are managed by the provider
        self.as_("admin")
        for body in ({"role": "admin"}, {"is_active": True}, {"password": "x" * 12}):
            self.j("patch", f"/api/admin/users/{uid}", body, status=400)

    def test_bad_requests(self):
        self.assertEqual(self.scim("get", 'Users?filter=title eq "x"', status=400)["scimType"], "invalidFilter")
        self.assertEqual(self.scim("post", "Users", {"name": {"givenName": "x"}}, status=400)["scimType"], "invalidValue")
        self.scim("patch", "Users/999", self.ops(("replace", "active", False)), status=404)
        uid = self.scim("post", "Users", ALICE, status=201)["id"]
        self.assertEqual(self.scim("patch", f"Users/{uid}", {"Operations": [{"op": "move"}]}, status=400)["scimType"],
                         "invalidSyntax")
        self.scim("get", "Nothing", status=404)
        page = self.scim("get", "Users?startIndex=1&count=0")
        self.assertEqual((page["totalResults"], page["itemsPerPage"]), (1, 0))
