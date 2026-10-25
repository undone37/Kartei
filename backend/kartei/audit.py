from .models import AuditEntry

SECRET_KEYS = {"password", "secret_enc", "ldap_bind_password_enc", "carddav_password_hash", "graph_client_secret_enc", "smtp_password_enc",
               "ad_bind_password_enc", "oidc_client_secret_enc", "scim_token_hash"}


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
        target_label=str(label)[:255], changes=changes or {})
    from . import webhooks  # every contact change passes here, so webhooks see all of them
    webhooks.enqueue(entry)
