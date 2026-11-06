import logging

from .models import AuditEntry
from .net import current_ip

log_ = logging.getLogger("kartei.audit")

SECRET_KEYS = {"password", "totp_secret_enc", "secret_enc", "ldap_bind_password_enc", "carddav_password_hash", "graph_client_secret_enc",
               "smtp_password_enc", "ad_bind_password_enc", "oidc_client_secret_enc", "scim_token_hash"}


def diff(old, new):
    """{key: [old, new]} for keys whose value changed. Secrets are masked."""
    out = {}
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if a != b:
            out[k] = ["***", "***"] if k in SECRET_KEYS else [a, b]
    return out


def log(user, action, target_type, target_id, label="", changes=None, username=None):
    """username: shown instead of the user's name, e.g. "api:<token name>" for changes through the API."""
    entry = AuditEntry.objects.create(
        user=user if user and user.is_authenticated else None,
        username=username or getattr(user, "username", "") or "system",
        action=action, target_type=target_type, target_id=str(target_id),
        target_label=str(label)[:255], changes=changes or {}, ip=current_ip.get())
    emit(entry)
    from . import webhooks  # every contact change passes here, so webhooks see all of them
    webhooks.enqueue(entry)


def emit(entry):
    """The entry as a log line (JSON in production, see logs.py) for the container log and the syslog sender.
    Contacts: only the changed field names (data minimisation); everything else with old/new, secrets already masked."""
    changes = sorted(entry.changes) if entry.target_type == "record" else entry.changes
    log_.info("%s %s %s", entry.action, entry.target_type, entry.target_label, extra={"audit": {
        "event": entry.action, "area": entry.target_type, "object_id": entry.target_id, "object": entry.target_label,
        "user": entry.username, "ip": entry.ip, "changes": changes}})
