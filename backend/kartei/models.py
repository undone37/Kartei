import base64
import hashlib
import uuid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings as dj_settings
from django.contrib.auth.models import User
from django.db import models

from .vcard import TARGETS as VCARD_TARGETS


class Role(models.TextChoices):
    READ = "read", "Read Only"
    MAINTAINER = "maintainer", "Maintainer"
    ADMIN = "admin", "Admin"


ROLE_RANK = {Role.READ: 0, Role.MAINTAINER: 1, Role.ADMIN: 2}
LANGUAGES = [("de", "Deutsch"), ("en", "English")]


def _fernet():
    key = hashlib.sha256(("kartei-secrets:" + dj_settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _secret(attr):
    """Property that stores a value Fernet-encrypted in `attr`."""
    def fget(self):
        if not getattr(self, attr):
            return ""
        try:
            return _fernet().decrypt(getattr(self, attr).encode()).decode()
        except InvalidToken:  # SECRET_KEY changed
            return ""

    def fset(self, value):
        setattr(self, attr, _fernet().encrypt(value.encode()).decode() if value else "")
    return property(fget, fset)


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.READ)
    language = models.CharField(max_length=2, choices=LANGUAGES, blank=True)  # '' = admin default
    source = models.CharField(max_length=5, choices=[("local", "local"), ("ldap", "ldap")], default="local")
    recent = models.JSONField(default=list, blank=True)  # record uids, last viewed first (dashboard)
    favorites = models.JSONField(default=list, blank=True)  # record uids, starred first

    @property
    def rank(self):
        return 2 if self.user.is_superuser else ROLE_RANK[self.role]


def ad_default_columns():
    return []  # mapping comes from the admin (Active Directory tab, import: examples/ad-mapping.json)


class Settings(models.Model):
    """Singleton (pk=1) holding everything an admin configures in the UI."""
    default_language = models.CharField(max_length=2, choices=LANGUAGES, default="de")
    base_url = models.URLField(blank=True)
    trash_days = models.PositiveIntegerField(default=0)  # 0 = recycle bin is never purged
    export_interval_minutes = models.PositiveIntegerField(default=15)

    ldap_uri = models.CharField(max_length=255, blank=True)  # empty = LDAP disabled
    ldap_start_tls = models.BooleanField(default=False)
    ldap_ca_cert = models.TextField(blank=True)
    ldap_bind_dn = models.CharField(max_length=255, blank=True)
    ldap_bind_password_enc = models.TextField(blank=True)
    ldap_user_base = models.CharField(max_length=255, blank=True)
    ldap_user_filter = models.CharField(max_length=255, default="(sAMAccountName=%(user)s)")
    ldap_group_admin = models.CharField(max_length=255, blank=True)
    ldap_group_maintainer = models.CharField(max_length=255, blank=True)
    ldap_group_read = models.CharField(max_length=255, blank=True)

    carddav_enabled = models.BooleanField(default=False)
    carddav_username = models.CharField(max_length=64, default="carddav")
    carddav_password_hash = models.CharField(max_length=255, blank=True)
    # CardDAV relay in the DMZ (relaypush.py): Kartei pushes the cards there, phones read them there
    carddav_relay_enabled = models.BooleanField(default=False)
    carddav_relay_url = models.CharField(max_length=255, blank=True)  # https://carddav.example.de
    carddav_relay_token_enc = models.TextField(blank=True)
    carddav_relay_tls_verify = models.BooleanField(default=True)
    carddav_relay_ca_cert = models.TextField(blank=True)  # PEM; empty = system CAs
    carddav_relay_max_delete_percent = models.PositiveSmallIntegerField(default=10)
    carddav_relay_status = models.JSONField(default=dict, blank=True)  # last run, written by the exporter
    carddav_relay_requested = models.DateTimeField(null=True, blank=True)  # "sync now"; the exporter polls it

    graph_enabled = models.BooleanField(default=False)
    oidc_enabled = models.BooleanField(default=False)  # "Sign in with Microsoft" with the same app registration
    graph_tenant_id = models.CharField(max_length=64, blank=True)
    graph_client_id = models.CharField(max_length=64, blank=True)
    graph_client_secret_enc = models.TextField(blank=True)
    graph_group_id = models.CharField(max_length=64, blank=True)  # Entra group whose members get the folder
    graph_folder = models.CharField(max_length=100, default="Kartei")
    graph_mailboxes = models.JSONField(default=list, blank=True)  # user ids synced last run, to clean up leavers
    graph_status = models.JSONField(default=dict, blank=True)  # last run, written by the exporter
    graph_sync_requested = models.DateTimeField(null=True, blank=True)  # "sync now"; the exporter polls it

    review_mode = models.CharField(max_length=8, default="off",
                                   choices=[("off", "off"), ("rolling", "rolling"), ("campaign", "campaign")])
    review_interval_months = models.PositiveSmallIntegerField(default=12)  # rolling: due N months after last check
    review_campaign_month = models.PositiveSmallIntegerField(default=1)  # campaign: every year on this date
    review_campaign_day = models.PositiveSmallIntegerField(default=15)
    review_last_campaign = models.DateField(null=True, blank=True)

    smtp_host = models.CharField(max_length=255, blank=True)  # empty = no emails
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_security = models.CharField(max_length=8, default="starttls",
                                     choices=[("starttls", "starttls"), ("ssl", "ssl"), ("none", "none")])
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password_enc = models.TextField(blank=True)
    smtp_from = models.CharField(max_length=255, blank=True)

    review_remind_days = models.PositiveSmallIntegerField(default=0)  # 0 = no reminders
    proposal_notify = models.BooleanField(default=False)  # mail new/edited proposals to maintainers
    proposal_notify_to = models.CharField(max_length=500, blank=True)  # comma-separated; empty = all maintainers/admins
    ldap_users_status = models.JSONField(default=dict, blank=True)  # last AD user import (daily, see ldapusers)
    ad_enabled = models.BooleanField(default=False)  # write AD contact objects, see adsync
    ad_ou = models.CharField(max_length=255, blank=True)
    ad_bind_dn = models.CharField(max_length=255, blank=True)  # empty = LDAP service account
    ad_bind_password_enc = models.TextField(blank=True)
    ad_kinds = models.CharField(max_length=7, default="both",
                                choices=[("person", "person"), ("company", "company"), ("both", "both")])
    ad_columns = models.JSONField(default=ad_default_columns, blank=True)  # [{"attr", "person", "company"}]
    ad_max_shrink_percent = models.PositiveSmallIntegerField(default=10)
    ad_status = models.JSONField(default=dict, blank=True)
    ad_sync_requested = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    phone_normalize = models.BooleanField(default=True)  # phone fields are saved in international form
    phone_country_code = models.CharField(max_length=5, default="+49")  # for national numbers (leading 0)

    # email: templates per email and language (empty = default, see reviews.DEFAULT_TEMPLATES) and the transport
    mail_templates = models.JSONField(default=dict, blank=True)  # {"review"|"reminder"|"proposals": {"de"|"en": {"subject", "body"}}}
    mail_transport = models.CharField(max_length=5, default="smtp", choices=[("smtp", "smtp"), ("graph", "graph")])
    mail_graph_sender = models.CharField(max_length=255, blank=True)  # mailbox that sends via Microsoft Graph

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]

    ldap_bind_password = _secret("ldap_bind_password_enc")
    graph_client_secret = _secret("graph_client_secret_enc")
    smtp_password = _secret("smtp_password_enc")
    ad_bind_password = _secret("ad_bind_password_enc")
    carddav_relay_token = _secret("carddav_relay_token_enc")


class Kind(models.TextChoices):
    PERSON = "person", "Person"
    COMPANY = "company", "Company"


class FieldType(models.TextChoices):
    TEXT = "text"
    LONGTEXT = "longtext"
    INTEGER = "integer"
    DECIMAL = "decimal"
    SELECT = "select"
    MULTISELECT = "multiselect"
    PHONE = "phone"
    EMAIL = "email"
    URL = "url"
    DATE = "date"
    CHECKBOX = "checkbox"
    USER = "user"  # one Kartei user (stored as username), e.g. the internal person responsible
    USERS = "users"  # several Kartei users, e.g. internal contacts
    CONTACT = "contact"  # a person record (stored as uid) or, with open_options, free text


USER_TYPES = ("user", "users")
REF_TYPES = ("user", "users", "contact")  # stored as keys, rendered via ref_names()


def user_label(u):
    return f"{u.first_name} {u.last_name}".strip() or u.username


def assignable(u):
    """Users that can be picked in user fields (e.g. internal contacts): active, and not administrators."""
    role = getattr(getattr(u, "profile", None), "role", None)
    return u.is_active and not u.is_superuser and role != Role.ADMIN


def user_options():
    """All users as select options for user fields. Inactive users and admins stay listed so existing values still
    display, but carry "pick": false: the forms don't offer them and validation refuses them as new values."""
    users = sorted(User.objects.select_related("profile").only(
        "username", "first_name", "last_name", "is_active", "is_superuser", "profile__role"), key=lambda u: user_label(u).lower())
    return [{"value": u.username, "de": user_label(u) + ("" if u.is_active else " (inaktiv)"),
             "en": user_label(u) + ("" if u.is_active else " (inactive)")} | ({} if assignable(u) else {"pick": False})
            for u in users]


class FieldSection(models.Model):
    """A named group of fields in the contact form and view; key is the stable id used in field files.
    The section with key "person" / "company" is shown in the header block of the person / company form."""
    key = models.SlugField(max_length=64, unique=True)
    label_de = models.CharField(max_length=100)
    label_en = models.CharField(max_length=100)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class FieldDef(models.Model):
    key = models.SlugField(max_length=64, unique=True)
    label_de = models.CharField(max_length=100)
    label_en = models.CharField(max_length=100)
    applies_to = models.CharField(max_length=7, choices=[("person", "person"), ("company", "company"), ("both", "both")])
    type = models.CharField(max_length=12, choices=FieldType.choices, default=FieldType.TEXT)
    options = models.JSONField(default=list, blank=True)  # [{"value", "de", "en"}]
    open_options = models.BooleanField(default=False)
    quick_filter = models.BooleanField(default=False)  # offered in the list's quick field filter (choice/user fields)  # editors may add new options while typing (e.g. keywords)
    required = models.BooleanField(default=False)
    min_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    max_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    decimals = models.PositiveSmallIntegerField(default=2)
    section = models.ForeignKey(FieldSection, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="fields")  # None = "Other"
    order = models.IntegerField(default=0)
    visible_to = models.CharField(max_length=12, choices=Role.choices, default=Role.READ)  # minimum role
    editable_by = models.CharField(max_length=12, choices=Role.choices[1:], default=Role.MAINTAINER)
    searchable = models.BooleanField(default=True)
    regex = models.CharField(max_length=500, blank=True)  # full-match pattern for text-like types
    help_de = models.TextField(blank=True)
    help_en = models.TextField(blank=True)
    vcard = models.CharField(max_length=32, choices=[(t, t) for t in VCARD_TARGETS], blank=True)
    vcard_label = models.CharField(max_length=64, blank=True)
    copy_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                  limit_choices_to={"applies_to__in": ["company", "both"]})
    import_aliases = models.JSONField(default=list, blank=True)  # alternative CSV header names for the import
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "id"]

    def applies(self, kind):
        return self.applies_to in (kind, "both")

    def visible(self, rank):
        return rank >= ROLE_RANK[self.visible_to]

    def editable(self, rank):
        return rank >= ROLE_RANK[self.editable_by]


class Record(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=7, choices=Kind.choices)
    legacy_id = models.CharField(max_length=64, blank=True, db_index=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=200, blank=True)  # company name
    company = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="persons", limit_choices_to={"kind": Kind.COMPANY})
    image = models.BinaryField(null=True, blank=True)
    image_type = models.CharField(max_length=4, blank=True)  # png/jpeg
    data = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    merged_legacy_ids = models.JSONField(default=list, blank=True)  # legacy ids of records merged into this one

    @property
    def display_name(self):
        if self.kind == Kind.COMPANY:
            return self.name
        return f"{self.first_name} {self.last_name}".strip()


def default_csv_options():
    return {"delimiter": ";", "quotechar": '"', "quoting": "minimal", "encoding": "utf-8-sig",
            "line_ending": "crlf", "header": True, "newlines": "keep", "multi_sep": ", ",
            "date_format": "%d.%m.%Y", "decimal_sep": ","}


def default_xlsx_options():
    return {"sheet_name": "Kontakte", "header": True, "bold_header": True, "autofilter": True,
            "freeze_header": True, "autowidth": True, "date_format": "DD.MM.YYYY", "number_format": "#,##0.00"}


class ExportProfile(models.Model):
    name = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    format = models.CharField(max_length=4, choices=[("csv", "CSV"), ("xlsx", "XLSX")], default="csv")
    path = models.CharField(max_length=500, help_text="Absolute target path, supports {date}")
    schedule = models.CharField(max_length=6, choices=[("auto", "auto"), ("manual", "manual")], default="auto")
    kinds = models.CharField(max_length=7, choices=[("person", "person"), ("company", "company"), ("both", "both")], default="both")
    filter_field = models.ForeignKey(FieldDef, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    filter_values = models.JSONField(default=list, blank=True)
    columns = models.JSONField(default=list, blank=True)  # [{"header", "person", "company"}], see exports.resolve()
    options = models.JSONField(default=dict, blank=True)  # merged over default_*_options()
    max_shrink_percent = models.PositiveSmallIntegerField(default=10)

    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=7, blank=True)  # ok / skipped / error
    last_message = models.TextField(blank=True)
    last_rows = models.IntegerField(null=True, blank=True)
    last_hash = models.CharField(max_length=64, blank=True)

    def effective_options(self):
        base = default_csv_options() if self.format == "csv" else default_xlsx_options()
        return {**base, **self.options}


class AuditEntry(models.Model):
    """Append-only log of every change: records, fields, users, settings, exports."""
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=150, blank=True)  # survives user deletion
    action = models.CharField(max_length=16)  # create/update/delete/restore/purge/import/login/...
    target_type = models.CharField(max_length=16, db_index=True)  # record/field/user/settings/export
    target_id = models.CharField(max_length=64, db_index=True)
    target_label = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)  # {key: [old, new]}

    class Meta:
        ordering = ["-at", "-id"]


class Review(models.Model):
    """A request to the responsible user to check that a contact is still up to date."""
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="reviews")
    assignee = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="reviews")
    reason = models.CharField(max_length=8)  # rolling / campaign / manual
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    notified_at = models.DateTimeField(null=True, blank=True)  # last mail, first digest or reminder
    reminders = models.PositiveSmallIntegerField(default=0)
    done_at = models.DateTimeField(null=True, blank=True, db_index=True)
    outcome = models.CharField(max_length=10, blank=True)  # confirmed / proposed / cancelled


class Proposal(models.Model):
    """A change, deletion or new contact suggested by a user who may not edit (e.g. the read-only responsible)."""
    # create: no record until a maintainer accepts it, then the new record
    record = models.ForeignKey(Record, null=True, blank=True, on_delete=models.CASCADE, related_name="proposals")
    kind = models.CharField(max_length=6)  # change / delete / create
    record_kind = models.CharField(max_length=7, blank=True)  # create: person / company
    changes = models.JSONField(default=dict, blank=True)  # {"core": {...}, "data": {...}} new values
    base = models.JSONField(default=dict, blank=True)  # same shape, values at proposal time
    comment = models.TextField(blank=True)
    # deletions: left (person left the company) / company_gone (company and all its persons) / other (comment)
    reason = models.CharField(max_length=12, blank=True)
    proposer = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="proposals")
    proposer_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, default="pending", db_index=True)  # pending/accepted/rejected/withdrawn
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    notified_at = models.DateTimeField(null=True, blank=True)  # mailed to maintainers; again if updated_at is newer


    @property
    def label(self):
        """Name of the contact concerned; for a new contact the proposed name."""
        if self.record_id:
            return self.record.display_name
        core = self.changes.get("core", {})
        return Record(kind=self.record_kind, first_name=core.get("first_name") or "", last_name=core.get("last_name") or "",
                      name=core.get("name") or "").display_name


class NotDuplicate(models.Model):
    """A candidate pair someone marked as \"not a duplicate\" (a.id < b.id)."""
    a = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="+")
    b = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="+")
    by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("a", "b")]


def ref_names():
    """{username or record uid: display name} for user and contact fields, used by vCards, exports and Outlook.
    Contacts: only persons actually referenced (soft-deleted ones keep their name)."""
    names = {u.username: user_label(u) for u in User.objects.only("username", "first_name", "last_name")}
    keys = list(FieldDef.objects.filter(type="contact").values_list("key", flat=True))
    if keys:
        refs = set()
        for data in Record.objects.filter(data__has_any_keys=keys).values_list("data", flat=True):
            refs.update(str(data[k]) for k in keys if data.get(k))
        uids = []
        for x in refs:
            try:
                uids.append(uuid.UUID(x))
            except ValueError:  # free text
                pass
        for r in Record.objects.filter(uid__in=uids).only("uid", "kind", "first_name", "last_name", "name"):
            names[str(r.uid)] = r.display_name
    return names


class ApiToken(models.Model):
    """Bearer token for other systems (/api/v1). Only the SHA-256 is stored; the token is shown once.
    scope "write" also creates, updates and deletes contacts with the rights of a maintainer."""
    SCOPES = ("read", "write")
    name = models.CharField(max_length=100)
    scope = models.CharField(max_length=5, choices=[(s, s) for s in SCOPES], default="read")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_used_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()


class Webhook(models.Model):
    """POSTs contact changes to another system. The HMAC secret is stored encrypted and shown once when created."""
    EVENTS = ("contact.created", "contact.updated", "contact.deleted", "contact.restored")
    name = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    events = models.JSONField(default=list, blank=True)  # subset of EVENTS; empty = all
    enabled = models.BooleanField(default=True)
    secret_enc = models.TextField(blank=True)
    secret = _secret("secret_enc")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_status = models.JSONField(default=dict, blank=True)  # {"at", "ok", "code", "error"} of the last attempt

    def wants(self, event):
        return self.enabled and (not self.events or event in self.events)


class WebhookDelivery(models.Model):
    """One event for one webhook; sent by the exporter, retried with growing pauses, then given up."""
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=20)
    record_uid = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, default="pending", db_index=True)  # pending / delivered / failed
    attempts = models.PositiveSmallIntegerField(default=0)
    next_at = models.DateTimeField(db_index=True)
    last_error = models.CharField(max_length=300, blank=True)


class SavedFilter(models.Model):
    """A named list state (search, scope, kind, field filters); private or shared with everyone."""
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_filters")
    name = models.CharField(max_length=100)
    state = models.JSONField(default=dict)  # {"q", "scope", "kind", "filters": {key: [values]}}
    shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
