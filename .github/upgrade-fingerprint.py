# Fingerprint of a Kartei database for the upgrade test (CI job "Upgrade from the latest release"):
#   python manage.py shell < upgrade-fingerprint.py
# Runs on the old release and, after the migrations, on the new code; both must print the same line.
# Only uses what every release has, so the old image can run it too.
import hashlib
import json

from django.contrib.auth.models import User
from kartei.models import AuditEntry, FieldDef, Proposal, Record, Settings


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:16]


s = Settings.get()
print("FINGERPRINT " + json.dumps({
    "records": Record.objects.count(),
    "records_digest": digest(sorted(
        [str(uid), kind, version, first, last, name, str(company), data, str(deleted)]
        for uid, kind, version, first, last, name, company, data, deleted in Record.objects.values_list(
            "uid", "kind", "version", "first_name", "last_name", "name", "company__uid", "data", "deleted_at"))),
    "proposals": sorted([kind, status, str(uid)] for kind, status, uid in
                        Proposal.objects.values_list("kind", "status", "record__uid")),
    "users": sorted(User.objects.values_list("username", flat=True)),
    "fields": sorted(FieldDef.objects.values_list("key", flat=True)),
    "audit_entries": AuditEntry.objects.count(),
    "settings": [s.default_language, s.review_mode, s.review_interval_months],
}, sort_keys=True))
