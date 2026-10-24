"""Idempotent startup: settings row, initial fields on first run, initial admin from env."""
import json
import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import models

from kartei.api import import_fields
from kartei.models import Profile, Role, Settings

# INITIAL_FIELDS overrides it; empty or a missing file = start without fields
DEFAULT_FIELDS = settings.BASE_DIR.parent / "examples" / "fields-default.json"


class Command(BaseCommand):
    def handle(self, *args, **opts):
        if not Settings.objects.exists():
            Settings.get()
            path, n = os.environ.get("INITIAL_FIELDS", str(DEFAULT_FIELDS)), 0
            if path and os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    n = sum(r["status"] == "new" for r in import_fields(json.load(fh), apply=True)["fields"])
            self.stdout.write(f"initialized settings, {n} initial fields")
        username, password = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
        # only for a fresh install: no active admin at all (also LDAP/role admins) and the name is still free
        admins = User.objects.filter(is_active=True).filter(models.Q(is_superuser=True) | models.Q(profile__role=Role.ADMIN))
        if username and password and not admins.exists() and not User.objects.filter(username=username).exists():
            u = User.objects.create_superuser(username, "", password)
            Profile.objects.update_or_create(user=u, defaults={"role": Role.ADMIN, "source": "local"})
            self.stdout.write(f"created admin {username}")
