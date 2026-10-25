"""Data protection: the data subject access report for one contact (GDPR Art. 15) and erasure on purge (Art. 17).

purge() is the one way a contact leaves the recycle bin for good (button and automatic emptying). With
Settings.purge_anonymize the contact's history keeps who did what and when, but loses all values and the name.
"""
from django.utils import timezone

from . import audit, exports
from .models import ApiToken, AuditEntry, ExportProfile, FieldDef, Proposal, Settings, Webhook


def purge(user, r, extra=None):
    """Delete a record from the recycle bin for good."""
    from .api import snapshot
    if Settings.get().purge_anonymize:
        # ponytail: values copied into other contacts' entries (e.g. "merged from <name>") stay; they are rare
        AuditEntry.objects.filter(target_type="record", target_id=str(r.uid)).update(changes={}, target_label="")
        audit.log(user, "purge", "record", r.uid, "", {"anonymized": [None, True]} | (extra or {}))
    else:
        audit.log(user, "purge", "record", r.uid, r.display_name, audit.diff(snapshot(r), {}) | (extra or {}))
    r.delete()


def report(r, user):
    """Everything Kartei holds about one contact and where it goes, for the data subject access report."""
    from .api import ADMIN, ser_audit, ser_proposal, ser_record, visible_fields
    s = Settings.get()
    fields = list(FieldDef.objects.filter(archived=False))
    shared = [f for f in fields if f.visible_to == "read" and f.applies(r.kind) and r.data.get(f.key) not in (None, "", [])]
    label = lambda f: {"de": f.label_de, "en": f.label_en}
    live = not r.deleted_at
    recipients = []
    if live and s.carddav_enabled:
        recipients.append({"system": "carddav", "fields": [label(f) for f in shared if f.vcard]})
    if live and s.carddav_relay_enabled:
        recipients.append({"system": "relay", "fields": [label(f) for f in shared if f.vcard]})
    if live and s.graph_enabled:
        recipients.append({"system": "outlook", "fields": [label(f) for f in shared if f.vcard]})
    if live and s.ad_enabled and s.ad_kinds in ("both", r.kind):
        recipients.append({"system": "ad", "detail": [c.get("attr", "") for c in s.ad_columns]})
    for p in ExportProfile.objects.filter(enabled=True).select_related("filter_field"):
        if live and exports.included(p, r):
            recipients.append({"system": "export", "name": p.name, "detail": [c.get("header", "") for c in p.columns]})
    for t in ApiToken.objects.all():
        recipients.append({"system": "api", "name": t.name, "fields": [label(f) for f in shared]})
    for h in Webhook.objects.filter(enabled=True):
        recipients.append({"system": "webhook", "name": h.name, "fields": [label(f) for f in shared]})
    entries = AuditEntry.objects.filter(target_type="record", target_id=str(r.uid)).order_by("at")
    return {
        "generated_at": timezone.now().isoformat(), "generated_by": user.username,
        "record": ser_record(r, visible_fields(ADMIN)), "image": bool(r.image_type), "in_trash": bool(r.deleted_at),
        "company": r.company.name if r.company_id and r.company else None,
        "history": [ser_audit(e, ADMIN) for e in entries],
        "proposals": [ser_proposal(p) | {"decided_at": p.decided_at.isoformat() if p.decided_at else None}
                      for p in Proposal.objects.filter(record=r).select_related("record").order_by("created_at")],
        "reviews": [{"created_at": rv.created_at.isoformat(), "done_at": rv.done_at.isoformat() if rv.done_at else None,
                     "assignee": rv.assignee.username if rv.assignee else "", "outcome": rv.outcome}
                    for rv in r.reviews.select_related("assignee").order_by("created_at")],
        "recipients": recipients,
    }
