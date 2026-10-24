"""Contact reviews: the responsible user (first single-user field) confirms a contact or proposes changes.

Started by an admin or by the exporter's schedule (rolling: N months after the last check; campaign: all contacts
once a year on a set date). New reviews are mailed as one digest per user, reviews still open N days after the
last mail as one reminder digest. New or edited proposals are mailed to the maintainers as one digest each.
"""
import logging
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.mail import EmailMessage, get_connection
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import audit
from .models import FieldDef, Proposal, Record, Review, Settings

log = logging.getLogger(__name__)


def responsible_keys():
    return list(FieldDef.objects.filter(type="user", archived=False).values_list("key", flat=True))


def responsible(r, keys, active):
    """The username in the record's first filled single-user field, if that user is active."""
    for k in keys:
        if r.data.get(k) in active:
            return r.data[k]
    return None


def open_reviews():
    return Review.objects.filter(done_at__isnull=True)


def start(records, reason, by=None):
    """Open a review for each record that has none. Returns counts."""
    keys = responsible_keys()
    active = {u.username: u for u in User.objects.filter(is_active=True)}
    busy = set(open_reviews().values_list("record_id", flat=True))
    out = {"created": 0, "already_open": 0, "no_responsible": 0}
    new = []
    for r in records:
        if r.id in busy:
            out["already_open"] += 1
        elif (name := responsible(r, keys, active)) is None:
            out["no_responsible"] += 1
        else:
            new.append(Review(record=r, assignee=active[name], reason=reason, created_by=by))
    Review.objects.bulk_create(new)
    out["created"] = len(new)
    if new:
        audit.log(by, "review", "settings", 1, "reviews", {"started": [None, {**out, "reason": reason}]})
    return out


def live():
    return Record.objects.filter(deleted_at__isnull=True)


def due(months):
    cutoff = timezone.now() - timedelta(days=round(months * 30.44))
    return live().annotate(last=Coalesce("reviewed_at", "created_at")).filter(last__lt=cutoff)


def campaign_date(s, year):
    try:
        return date(year, s.review_campaign_month, s.review_campaign_day)
    except ValueError:  # e.g. 29 Feb
        return date(year, s.review_campaign_month, 28)


def schedule(s, today=None):
    """Exporter tick: start scheduled reviews. Returns counts or None."""
    today = today or timezone.localdate()
    if s.review_mode == "rolling" and s.review_interval_months:
        return start(due(s.review_interval_months), "rolling")
    if s.review_mode == "campaign":
        day = campaign_date(s, today.year)
        if today >= day and (s.review_last_campaign is None or s.review_last_campaign < day):
            Settings.objects.filter(pk=1).update(review_last_campaign=day)
            return start(live(), "campaign")
    return None


def finish(review_qs, outcome, user=None):
    """Close open reviews of the given records; the record counts as checked unless cancelled."""
    now = timezone.now()
    reviews = list(review_qs.filter(done_at__isnull=True).select_related("record"))
    for rv in reviews:
        rv.done_at, rv.outcome = now, outcome
        rv.save(update_fields=["done_at", "outcome"])
        if outcome != "cancelled":
            r = rv.record
            r.reviewed_at, r.reviewed_by = now, user
            r.save(update_fields=["reviewed_at", "reviewed_by"])  # not a change: /api/changes also looks at reviewed_at
    return reviews


def confirm(record, user):
    reviews = finish(record.reviews.all(), "confirmed", user)
    if not reviews:  # confirming without an open review is fine too
        record.reviewed_at, record.reviewed_by = timezone.now(), user
        record.save(update_fields=["reviewed_at", "reviewed_by"])
    audit.log(user, "review", "record", record.uid, record.display_name, {"reviewed": [None, "confirmed"]})


def reassign(record):
    """After an edit: open reviews follow a changed responsible, or are cancelled if there is none."""
    rv = open_reviews().filter(record=record).first()
    if not rv:
        return
    active = {u.username: u for u in User.objects.filter(is_active=True)}
    name = responsible(record, responsible_keys(), active)
    if name is None:
        finish(Review.objects.filter(pk=rv.pk), "cancelled")
    elif rv.assignee_id != active[name].id:
        rv.assignee, rv.notified_at = active[name], None  # the new responsible gets mailed
        rv.save(update_fields=["assignee", "notified_at"])


# ---------------------------------------------------------------- mail

def mail_ready(s):
    """Is a transport configured? SMTP: server + sender; Microsoft 365: sending mailbox + the Outlook app registration."""
    if s.mail_transport == "graph":
        return bool(s.mail_graph_sender and s.graph_tenant_id and s.graph_client_id and s.graph_client_secret_enc)
    return bool(s.smtp_host and s.smtp_from)


def mail_from(s):
    return s.mail_graph_sender if s.mail_transport == "graph" else s.smtp_from


def mail_connection(s):
    if s.mail_transport == "graph":
        from .graph import GraphMailBackend
        return GraphMailBackend(s)
    return get_connection("django.core.mail.backends.smtp.EmailBackend", host=s.smtp_host, port=s.smtp_port,
                          username=s.smtp_username or None, password=s.smtp_password or None,
                          use_tls=s.smtp_security == "starttls", use_ssl=s.smtp_security == "ssl", timeout=20)


# Editable in Settings → Email (Settings.mail_templates overrides per email and language); these are the defaults.
# Placeholders: {name} greeting name, {n} number of items, {items} the list, {url} link to the list in Kartei.
DEFAULT_TEMPLATES = {
    "review": {
        "de": {"subject": "Kartei: {n} Kontakt(e) zu prüfen",
               "body": "Hallo {name},\n\nbitte prüfe, ob diese Kontakte noch aktuell sind (und ob die Firmen noch "
                       "existieren):\n\n{items}\n\nAlle offenen Prüfungen: {url}\n\nIn Kartei kannst du sie bestätigen "
                       "oder Änderungen bzw. eine Löschung vorschlagen.\n"},
        "en": {"subject": "Kartei: {n} contact(s) to review",
               "body": "Hello {name},\n\nplease check whether these contacts are still up to date (and whether the "
                       "companies still exist):\n\n{items}\n\nAll open reviews: {url}\n\nIn Kartei you can confirm them "
                       "or propose changes or a deletion.\n"},
    },
    "reminder": {
        "de": {"subject": "Kartei: Erinnerung – {n} Kontakt(e) noch zu prüfen",
               "body": "Hallo {name},\n\ndiese Kontakte warten noch auf deine Prüfung:\n\n{items}\n\n"
                       "Alle offenen Prüfungen: {url}\n\nIn Kartei kannst du sie bestätigen oder Änderungen bzw. "
                       "eine Löschung vorschlagen.\n"},
        "en": {"subject": "Kartei: reminder – {n} contact(s) still to review",
               "body": "Hello {name},\n\nthese contacts are still waiting for your review:\n\n{items}\n\n"
                       "All open reviews: {url}\n\nIn Kartei you can confirm them or propose changes or a deletion.\n"},
    },
    "proposals": {
        "de": {"subject": "Kartei: {n} Vorschlag/Vorschläge zur Entscheidung",
               "body": "Hallo {name},\n\nin Kartei warten Vorschläge auf eine Entscheidung:\n\n{items}\n\n"
                       "Alle Vorschläge: {url}\n"},
        "en": {"subject": "Kartei: {n} proposal(s) to decide",
               "body": "Hello {name},\n\nthese proposals in Kartei are waiting for a decision:\n\n{items}\n\n"
                       "All proposals: {url}\n"},
    },
}
PLACEHOLDERS = ("name", "n", "items", "url")


def check_templates(tpl):
    """Error code for templates an admin saved, or None. Placeholders must be known, braces balanced."""
    if not isinstance(tpl, dict):
        return "invalid"
    sample = {k: "x" for k in PLACEHOLDERS}
    for kind, langs in tpl.items():
        if kind not in DEFAULT_TEMPLATES or not isinstance(langs, dict):
            return "invalid"
        for lang, t in langs.items():
            if lang not in ("de", "en") or not isinstance(t, dict):
                return "invalid"
            for part in ("subject", "body"):
                text = t.get(part, "")
                if not isinstance(text, str) or len(text) > (200 if part == "subject" else 10000):
                    return "invalid"
                try:
                    text.format(**sample)
                except (KeyError, IndexError, ValueError):
                    return "invalid_template"
    return None


def render_mail(s, kind, lang, **values):
    """(subject, body) from the admin's template, falling back to the default if it is empty or broken."""
    default = DEFAULT_TEMPLATES[kind].get(lang) or DEFAULT_TEMPLATES[kind]["de"]
    custom = (s.mail_templates or {}).get(kind, {}).get(lang, {})
    for t in (custom, default):
        try:
            return (t.get("subject") or default["subject"]).format(**values), (t.get("body") or default["body"]).format(**values)
        except (KeyError, IndexError, ValueError) as e:  # unknown placeholder or stray brace
            log.warning("mail template %s/%s unusable: %s", kind, lang, e)
    raise AssertionError("default mail template broken")


def lang_of(u, s):
    return getattr(getattr(u, "profile", None), "language", "") or s.default_language


def _review_digests(s, conn, pending, kind, reminder=False):
    by_user = {}
    for rv in pending.select_related("record", "assignee"):
        by_user.setdefault(rv.assignee, []).append(rv)
    base = (s.base_url or "").rstrip("/")
    sent = 0
    for u, rvs in by_user.items():
        if not u.email:
            continue  # stays un-notified; visible in the app
        items = "\n".join(f"- {rv.record.display_name}: {base}/{rv.record.kind}/{rv.record.uid}" for rv in rvs)
        subject, body = render_mail(s, kind, lang_of(u, s), n=len(rvs), name=u.first_name or u.username, items=items,
                                    url=f"{base}/?list=review")
        msg = EmailMessage(subject, body, mail_from(s), [u.email], connection=conn)
        msg.send()
        done = Review.objects.filter(pk__in=[rv.pk for rv in rvs])
        done.update(notified_at=timezone.now(), **({"reminders": F("reminders") + 1} if reminder else {}))
        sent += 1
    return sent


def notify(s):
    """Mail each assignee one digest of their reviews not yet notified. Returns the number of mails sent."""
    if not mail_ready(s):
        return 0
    with mail_connection(s) as conn:
        return _review_digests(s, conn, open_reviews().filter(notified_at__isnull=True, assignee__isnull=False), "review")


def remind(s):
    """Mail each assignee one reminder of their open reviews last mailed at least N days ago."""
    if not mail_ready(s) or not s.review_remind_days:
        return 0
    cutoff = timezone.now() - timedelta(days=s.review_remind_days)
    pending = open_reviews().filter(notified_at__lte=cutoff, assignee__isnull=False, record__deleted_at__isnull=True)
    with mail_connection(s) as conn:
        return _review_digests(s, conn, pending, "reminder", reminder=True)


# words used inside the list of proposals (the surrounding text is the "proposals" template)
PROPOSAL_WORDS = {
    "de": {"change": "Änderung", "delete": "Löschung", "edited": " (bearbeitet)", "by": "von",
           "left": "hat das Unternehmen verlassen", "company_gone": "Firma existiert nicht mehr", "other": "anderer Grund"},
    "en": {"change": "Change", "delete": "Deletion", "edited": " (edited)", "by": "by",
           "left": "left the company", "company_gone": "company no longer exists", "other": "other reason"},
}


def proposal_recipients(s):
    """[(email, name, language, user or None)]: the fixed list, else all active maintainers/admins with an email."""
    if fixed := [a.strip() for a in s.proposal_notify_to.split(",") if a.strip()]:
        return [(a, "", s.default_language, None) for a in fixed]
    users = User.objects.filter(is_active=True).exclude(email="").select_related("profile")
    return [(u.email, u.first_name or u.username, lang_of(u, s), u) for u in users
            if u.is_superuser or getattr(getattr(u, "profile", None), "role", "") in ("maintainer", "admin")]


def notify_proposals(s):
    """Mail pending proposals that are new or were edited since their last mail. Returns the number of mails sent."""
    if not mail_ready(s) or not s.proposal_notify:
        return 0
    now = timezone.now()  # taken before reading, so an edit during sending is mailed again next tick
    props = list(Proposal.objects.filter(status="pending", record__deleted_at__isnull=True)
                 .filter(Q(notified_at__isnull=True) | Q(notified_at__lt=F("updated_at")))
                 .select_related("record").order_by("created_at"))
    if not props:
        return 0
    base = (s.base_url or "").rstrip("/")
    sent = 0
    with mail_connection(s) as conn:
        for to, name, lang, u in proposal_recipients(s):
            mine = [p for p in props if u is None or p.proposer_id != u.id]  # nobody needs mail about their own
            if not mine:
                continue
            w = PROPOSAL_WORDS.get(lang, PROPOSAL_WORDS["de"])
            items = []
            for p in mine:
                what = w.get(p.kind, p.kind) + (f" ({w.get(p.reason, p.reason)})" if p.reason else "")
                line = (f"- {p.record.display_name}: {what}{w['edited'] if p.notified_at else ''}, {w['by']} "
                        f"{p.proposer_name}\n  {base}/{p.record.kind}/{p.record.uid}")
                items.append(line + (f'\n  "{p.comment[:500]}"' if p.comment else ""))
            greeting = name or ("zusammen" if lang == "de" else "all")
            subject, body = render_mail(s, "proposals", lang, n=len(mine), name=greeting, items="\n".join(items),
                                        url=f"{base}/?list=proposals")
            EmailMessage(subject, body, mail_from(s), [to], connection=conn).send()
            sent += 1
    Proposal.objects.filter(pk__in=[p.pk for p in props]).update(notified_at=now)
    return sent


def tick():
    s = Settings.get()
    started = schedule(s)
    sent = 0
    for step in (notify, remind, notify_proposals):
        try:
            sent += step(s)
        except Exception as e:  # SMTP down: retried next tick
            log.warning("%s mail failed: %s", step.__name__, e)
    return started, sent


def _next_campaign(s):
    today = timezone.localdate()
    d = campaign_date(s, today.year)
    if today >= d and s.review_last_campaign and s.review_last_campaign >= d:
        d = campaign_date(s, today.year + 1)
    return d.isoformat()


def stats():
    s = Settings.get()
    keys = responsible_keys()
    active = set(User.objects.filter(is_active=True).values_list("username", flat=True))
    without = [r for r in live() if responsible(r, keys, active) is None]
    return {
        "open": open_reviews().count(),
        "due": due(s.review_interval_months).count() if s.review_interval_months else 0,
        "no_responsible": len(without),
        "no_responsible_sample": [{"uid": str(r.uid), "kind": r.kind, "name": r.display_name} for r in without[:20]],
        "unnotified": open_reviews().filter(notified_at__isnull=True).count(),
        "reminded": open_reviews().filter(reminders__gt=0).count(),
        "next_campaign": _next_campaign(s) if s.review_mode == "campaign" else None,
    }
