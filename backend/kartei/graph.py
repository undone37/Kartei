"""Push contacts into a contact folder in every mailbox of an Entra group via Microsoft Graph.

The Outlook app for iOS and Android syncs that folder into the phone's native address book, which gives caller ID
without CardDAV. App-only auth (client credentials); needs the application permissions
Contacts.ReadWrite, GroupMember.Read.All and User.Read.All. The folder belongs to Kartei: anything else in it is removed.
"""
import hashlib
import json
import logging
import time
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.contrib.auth.models import User
from django.core.mail.backends.base import BaseEmailBackend
from django.utils import timezone

from .msg import msg
from .models import FieldDef, Record, SavedFilter, Settings, ref_names
from .vcard import _ADR_PARTS, collect

GRAPH = "https://graph.microsoft.com/v1.0"
PROP = "String {6f1d3c52-8a4e-4d0b-9c7e-2b5f0e9a1d34} Name Kartei"  # "<uid>|<hash>" of what we wrote
log = logging.getLogger(__name__)


class GraphError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status  # HTTP status, if the error came from Graph


def _message(body):
    e = (body or {}).get("error")
    return (e.get("message") if isinstance(e, dict) else (body or {}).get("error_description") or e) or ""


def _wait(headers):
    try:
        return min(int((headers or {}).get("Retry-After") or 5), 120)
    except ValueError:
        return 5


def http(method, url, body=None, token=None, form=None, ctype=None):
    """One HTTP call with retry on throttling. Returns parsed JSON ({} for empty bodies).
    body: JSON-able, or bytes sent as `ctype`."""
    headers, data = {}, None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if isinstance(body, bytes):
        data, headers["Content-Type"] = body, ctype
    elif form is not None:
        data, headers["Content-Type"] = urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    for attempt in range(5):
        try:
            with urlopen(Request(url, data, headers, method=method), timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            if e.code in (429, 503, 504) and attempt < 4:
                time.sleep(_wait(e.headers))
                continue
            try:
                detail = json.loads(e.read())
            except ValueError:
                detail = {}
            raise GraphError(f"HTTP {e.code}: {_message(detail) or e.reason}", e.code)
        except URLError as e:
            raise GraphError(str(e.reason))


class Client:
    def __init__(self, s):
        if not (s.graph_tenant_id and s.graph_client_id and s.graph_client_secret):
            raise GraphError(msg("graph_not_configured"))
        tok = http("POST", f"https://login.microsoftonline.com/{quote(s.graph_tenant_id)}/oauth2/v2.0/token", form={
            "client_id": s.graph_client_id, "client_secret": s.graph_client_secret,
            "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"})
        self.token = tok["access_token"]

    def call(self, method, path, body=None, ctype=None):
        return http(method, GRAPH + path, body, self.token, ctype=ctype)

    def get_all(self, path):
        url, out = GRAPH + path, []
        while url:
            page = http("GET", url, token=self.token)
            out += page.get("value", [])
            url = page.get("@odata.nextLink")
        return out

    def batch(self, ops):
        """ops: [(method, path, body)], sent 20 per $batch. Returns (failure messages, {op index: response body})."""
        failed, results, pending, rounds = [], {}, list(enumerate(ops)), 0
        while pending:
            chunk, pending = pending[:20], pending[20:]
            reqs = [{"id": str(i), "method": m, "url": p,
                     **({"body": b, "headers": {"Content-Type": "application/json"}} if b is not None else {})}
                    for i, (m, p, b) in chunk]
            retry, wait = [], 0
            for r in self.call("POST", "/$batch", {"requests": reqs})["responses"]:
                i, status = int(r["id"]), r["status"]
                if status in (429, 503, 504) and rounds < 20:
                    retry.append((i, ops[i]))
                    wait = max(wait, _wait(r.get("headers")))
                elif status >= 400 and not (status == 404 and ops[i][0] == "DELETE"):
                    failed.append(f"{ops[i][0]} {status}: {_message(r.get('body'))}")
                else:
                    results[i] = r.get("body") or {}
            if retry:
                rounds += 1
                time.sleep(wait)
                pending = retry + pending
        return failed, results


# ---------------------------------------------------------------- mapping

def _addr(g, where):
    p = {part: " ".join(v for v, _ in g.get(f"adr_{where}_{part}", [])) for part in _ADR_PARTS}
    return {"street": "\n".join(x for x in (p["extra"], p["street"], p["pobox"]) if x), "city": p["city"],
            "state": p["state"], "postalCode": p["zip"], "countryOrRegion": p["country"]}


def contact(r, fields, names=None):
    """Graph contact JSON for a record. Every key is always present so a PATCH also clears values."""
    g = collect(r.data or {}, fields, names)
    vals = lambda t: [v for v, _ in g.get(t, [])]
    one = lambda t: " ".join(vals(t))
    first = lambda t: next(iter(vals(t)), "")
    notes = vals("note") + [f"{label}: {v}" for v, label in g.get("note_labeled", [])]
    # Graph contacts have no fax/assistant phone or custom relations; those go into the notes
    for t, label in [("tel_fax_work", "Fax"), ("tel_fax_home", "Fax privat"), ("tel_assistant", "Assistenz")]:
        notes += [f"{label}: {v}" for v in vals(t)]
    notes += [f"{label}: {v}" for v, label in g.get("tel_fax_custom", []) + g.get("related_custom", [])]
    # new Outlook shows contact folders as categories; tags as categories would bury the folders, so they go to the notes
    if tags := [c for v in vals("categories") for c in (v if isinstance(v, list) else [v])]:
        notes.append("Schlagworte: " + ", ".join(tags))
    cells = vals("tel_cell")
    emails = [{"address": v, "name": v} for t in ("email_work", "email_custom", "email_home") for v in vals(t)]
    notes += [f"E-Mail: {e['address']}" for e in emails[3:]]  # Graph keeps at most 3
    try:
        bday = date.fromisoformat(first("bday")).isoformat() + "T00:00:00Z"
    except ValueError:
        bday = None
    if r.kind == "company":
        names = {"givenName": "", "surname": "", "displayName": r.name, "fileAs": r.name, "companyName": r.name}
    else:
        org = r.company.name if r.company_id and r.company and not r.company.deleted_at else ""
        names = {"givenName": r.first_name, "surname": r.last_name, "displayName": r.display_name,
                 "fileAs": ", ".join(x for x in (r.last_name, r.first_name) if x), "companyName": org}
    return {
        **names,
        "title": one("n_prefix"), "middleName": one("n_middle"), "generation": one("n_suffix"),
        "nickName": one("nickname"), "yomiGivenName": one("phonetic_first"), "yomiSurname": one("phonetic_last"),
        "jobTitle": one("title"), "department": one("department"), "businessHomePage": first("url"),
        "birthday": bday,
        "emailAddresses": emails[:3],
        "mobilePhone": cells[0] if cells else "",
        "businessPhones": vals("tel_work") + vals("tel_custom") + cells[1:],
        "homePhones": vals("tel_home"),
        "businessAddress": _addr(g, "work"), "homeAddress": _addr(g, "home"),
        "assistantName": first("related_assistant"), "manager": first("related_manager"),
        "categories": [],  # always sent, so a PATCH clears the categories of earlier versions
        "personalNotes": "\n".join(notes),
    }


# ---------------------------------------------------------------- sync

def mailboxes(c, group_id):
    """{user id: member} for all (nested) user members of the group that have a mailbox address."""
    members = c.get_all(f"/groups/{quote(group_id)}/transitiveMembers?$select=id,mail,userPrincipalName&$top=999")
    users = [m for m in members if m.get("@odata.type") == "#microsoft.graph.user"]
    # without User.Read.All, Graph returns users with only id and type: every mail and UPN is null
    if users and not any(m.get("userPrincipalName") for m in users):
        raise GraphError(msg("graph_no_user_read"))
    return {m["id"]: m for m in users if m.get("mail")}


def kartei_users():
    """({username lower: (username, email lower)}, {email lower: username}) of active users, to find a mailbox's owner."""
    names, emails = {}, {}
    for name, email in User.objects.filter(is_active=True).values_list("username", "email"):
        names[name.lower()] = (name, (email or "").lower())
        if email:
            emails.setdefault(email.lower(), name)
    return names, emails


def owner(member, users):
    """Kartei username of a mailbox: by full mail or UPN, else by the local part (an AD account name), but only for an
    account without an email or with one of this mailbox's addresses: never another person's account with the same name."""
    names, emails = users
    full = [k.lower() for k in (member.get("mail") or "", member.get("userPrincipalName") or "") if k]
    for k in full:
        if k in emails:
            return emails[k]
        if k in names:
            return names[k][0]
    for k in full:
        hit = names.get(k.split("@")[0])
        if hit and (not hit[1] or hit[1] in full):
            return hit[0]
    return None


def _folder(c, user, name, create=True):
    # ponytail: found by name; renaming it in the settings leaves the old folder behind
    flt = quote("displayName eq '{}'".format(name.replace("'", "''")))
    found = c.get_all(f"/users/{user}/contactFolders?$filter={flt}")
    if found:
        return found[0]["id"]
    return c.call("POST", f"/users/{user}/contactFolders", {"displayName": name})["id"] if create else None


def _known(c, user, v):
    """The filter folders Kartei created in a mailbox: {name: id}. Up to 0.8.4 only the names were kept; those
    folders were Kartei's, so their ids are looked up once by name."""
    if isinstance(v, dict):
        return v
    return {n: fid for n in v or [] if (fid := _folder(c, user, n, create=False))}


def _delete_folder(c, user, fid):
    try:
        c.call("DELETE", f"/users/{user}/contactFolders/{fid}")
    except GraphError as e:
        if e.status != 404:  # already gone (deleted in Outlook) is fine
            raise


def _filter_folders(c, user, mail, jobs, before, folders_now, add):
    """Sync one mailbox's saved-filter folders. They are found by the id Kartei got when creating them, never by
    name: a folder of the same name that Kartei didn't create (e.g. the user's own "Privat") is left alone."""
    try:
        known = _known(c, user, before)
    except GraphError as e:
        folders_now[user] = before  # retry next run
        return add(mail, {}, [str(e)])
    now = folders_now[user] = {}
    for folder, want in jobs:
        fid = known.get(folder)
        try:
            if not fid:
                if _folder(c, user, folder, create=False):  # not Kartei's: never adopt (and later delete) it
                    add(None, {}, [msg("graph_folder_taken", mailbox=mail, folder=folder)])
                    continue
                fid = _folder(c, user, folder)
            now[folder] = fid
            add(mail, *sync_mailbox(c, user, folder, want, fid))
        except GraphError as e:
            if e.status == 404 and folder in known:  # deleted in Outlook: created again on the next run
                now.pop(folder, None)
                continue
            add(mail, {}, [str(e)])
    for folder, fid in known.items():  # filter unpublished, renamed or no longer visible: its folder goes
        if folder not in now:
            try:
                _delete_folder(c, user, fid)
            except GraphError as e:
                now[folder] = fid  # retry next run
                add(mail, {}, [str(e)])


def sync_mailbox(c, user, folder, wanted, fid=None):
    """wanted: {uid: (hash, payload, photo hash, record)}. Returns ({created, updated, deleted, photos}, failures).

    fid: the folder's id when known (filter folders), else it is found by name or created.
    Each contact carries the tag "<uid>|<data hash>|<photo hash>". The photo hash is only written after the
    photo upload succeeded, so a failed upload is retried next run.
    """
    base = f"/users/{user}/contactFolders/{fid or _folder(c, user, folder)}/contacts"
    expand = quote(f"singleValueExtendedProperties($filter=id eq '{PROP}')")
    tag = lambda uid, h, ph: [{"id": PROP, "value": f"{uid}|{h}|{ph}"}]
    have, ops, photos = {}, [], []  # photos: [(contact id or op index, uid)]
    for ct in c.get_all(f"{base}?$select=id&$top=1000&$expand={expand}"):
        value = next((p.get("value", "") for p in ct.get("singleValueExtendedProperties", [])), "")
        uid, h, ph = (value.split("|") + ["", ""])[:3]
        if uid in wanted and uid not in have:
            have[uid] = (ct["id"], h, ph)
        else:  # deleted record, duplicate, or added on the phone
            ops.append(("DELETE", f"{base}/{ct['id']}", None))
    deleted = len(ops)
    for uid, (h, payload, ph, _) in wanted.items():
        old = have.get(uid)
        if old and old[2] and not ph:  # photo removed: contacts have no photo delete in v1.0, so recreate
            ops.append(("DELETE", f"{base}/{old[0]}", None))
            old = None
        if not old:
            ops.append(("POST", base, {**payload, "singleValueExtendedProperties": tag(uid, h, "")}))
            if ph:
                photos.append((len(ops) - 1, uid))
            continue
        if old[1] != h:
            ops.append(("PATCH", f"{base}/{old[0]}", {**payload, "singleValueExtendedProperties": tag(uid, h, old[2])}))
        if old[2] != ph:
            photos.append((old[0], uid))
    counts = {"created": sum(1 for m, _, _ in ops if m == "POST"), "updated": sum(1 for m, _, _ in ops if m == "PATCH"),
              "deleted": deleted, "photos": 0}  # a photo removal recreates the contact, counted as created
    failed, results = c.batch(ops)
    for ref, uid in photos:
        cid = results.get(ref, {}).get("id") if isinstance(ref, int) else ref
        if not cid:
            continue  # its POST failed and is already reported
        h, _, ph, r = wanted[uid]
        try:
            img = Record.objects.only("image", "image_type").get(pk=r.pk)  # loaded only for an actual upload
            c.call("PUT", f"{base}/{cid}/photo/$value", bytes(img.image), ctype=f"image/{img.image_type}")
            c.call("PATCH", f"{base}/{cid}", {"singleValueExtendedProperties": tag(uid, h, ph)})
            counts["photos"] += 1
        except GraphError as e:
            failed.append(f"photo {r.display_name}: {e}")
    return counts, failed


def _sync(s):
    fields = list(FieldDef.objects.filter(archived=False, visible_to="read"))  # same fields as CardDAV
    wanted, names = {}, ref_names()
    # ponytail: every photo is read once per run to hash it, but not kept: memory stays small; a stored image hash
    # would save the reads if photo counts get large
    for r in Record.objects.filter(deleted_at__isnull=True).select_related("company", "updated_by").iterator(chunk_size=200):
        p = contact(r, fields, names)
        ph = hashlib.sha256(bytes(r.image)).hexdigest()[:12] if r.image else ""
        r.image = None  # hashed above; the bytes are fetched again only for an upload
        wanted[str(r.uid)] = (hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16], p, ph, r)
    if not wanted:  # never wipe the phones because of an empty database
        raise GraphError(msg("graph_no_records"))
    c = Client(s)
    boxes = mailboxes(c, s.graph_group_id)
    if not boxes:
        raise GraphError(msg("graph_group_empty"))
    # personal folders: single-user fields mean "responsible", multi-user fields "internal contact" (like the app's lists)
    keys = lambda t: list(FieldDef.objects.filter(type=t, archived=False).values_list("key", flat=True))
    personal = [(name, ks, t) for name, ks, t in ((s.graph_folder_responsible, keys("user"), "user"),
                                                  (s.graph_folder_internal, keys("users"), "users")) if name and ks]
    published = list(SavedFilter.objects.filter(outlook_folder=True))
    personal_names = [n for n in (s.graph_folder_responsible, s.graph_folder_internal) if n]
    users = kartei_users() if personal_names or published else ({}, {})
    by_filter = FilterFolders(wanted) if published else None
    reserved = {n for n in (s.graph_folder, s.graph_folder_responsible, s.graph_folder_internal) if n}
    before = s.graph_filter_folders or {}
    folders_now = {}  # mailbox -> {filter folder name: id of the folder Kartei created}
    out = {"mailboxes": len(boxes), "created": 0, "updated": 0, "deleted": 0, "photos": 0, "failed": []}

    def add(mail, counts, failed):
        for k, n in counts.items():
            out[k] += n
        out["failed"].extend(f"{mail}: {f}" if mail else f for f in failed)

    for user, member in boxes.items():
        jobs = [(s.graph_folder, wanted)]
        name = owner(member, users)
        # no (active) Kartei user any more, or no fields for the folder: earlier personal folders must not stay stale
        active = {f for f, _, _ in personal} if name else set()
        try:
            for folder in personal_names:
                if folder not in active and (fid := _folder(c, user, folder, create=False)):
                    c.call("DELETE", f"/users/{user}/contactFolders/{fid}")
        except GraphError as e:
            out["failed"].append(f"{member['mail']}: {e}")
        filter_jobs = []
        if name:
            for folder, ks, t in personal:
                mine = (lambda d: any(d.get(k) == name for k in ks)) if t == "user" else \
                    (lambda d: any(name in (d.get(k) or []) for k in ks))
                jobs.append((folder, {uid: w for uid, w in wanted.items() if mine(w[3].data or {})}))
            if by_filter:
                filter_jobs = by_filter.jobs(name, reserved, s.graph_filter_prefix)
        for folder, want in jobs:
            try:
                add(member["mail"], *sync_mailbox(c, user, folder, want))
            except GraphError as e:
                add(member["mail"], {}, [str(e)])
        if filter_jobs or before.get(user):
            _filter_folders(c, user, member["mail"], filter_jobs, before.get(user), folders_now, add)
    keep = set(boxes)
    # ponytail: folders of a renamed or cleared setting stay behind (found by name), like a renamed main folder
    names = [n for n in (s.graph_folder, s.graph_folder_responsible, s.graph_folder_internal) if n]
    for user in set(s.graph_mailboxes) - keep:  # left the group: remove the folders
        try:
            for name in names:
                if fid := _folder(c, user, name, create=False):
                    c.call("DELETE", f"/users/{user}/contactFolders/{fid}")
            for fid in _known(c, user, before.get(user)).values():  # filter folders: only the ones Kartei created
                _delete_folder(c, user, fid)
        except GraphError as e:
            keep.add(user)  # retry next run
            folders_now[user] = before.get(user)
            out["failed"].append(f"{user}: {e}")
    Settings.objects.filter(pk=1).update(graph_mailboxes=sorted(keep),
                                         graph_filter_folders={u: n for u, n in folders_now.items() if n})
    out["failed"] = out["failed"][:20]
    return out


class FilterFolders:
    """Saved filters published as Outlook folders: for a mailbox owner, one folder per filter they can see, with the
    contacts the filter shows them (their "responsible" and "internal" lists, only fields they may see)."""

    def __init__(self, wanted):
        self.wanted = wanted
        self.per_rank = {}  # rank -> (field dicts, rows, text index): built once per run

    def _view(self, rank):
        from . import filters
        from .api import visible_fields
        if rank not in self.per_rank:
            fs = visible_fields(rank)
            keys = {f.key for f in fs}
            rows = [filters.row(w[3], keys) for w in self.wanted.values()]
            self.per_rank[rank] = (filters.field_dicts(fs), rows, {})
        return self.per_rank[rank]

    def jobs(self, username, reserved, prefix=""):
        """[(folder name, wanted)]: the folder name is the admin's prefix (e.g. "Kartei: ") plus the filter's name."""
        from . import dashboard, filters
        from .api import profile_of, rank_of
        user = User.objects.filter(username=username, is_active=True).select_related("profile").first()
        if not user:
            return []
        rank = rank_of(user)
        role = "admin" if user.is_superuser else profile_of(user).role
        fields, rows, indexed = self._view(rank)
        keys = {f["key"] for f in fields}
        out, seen = [], set(reserved)
        for f in dashboard.visible_filters(user, role):
            name = prefix + f.name
            if not f.outlook_folder or name in seen:  # two filters with one name: the first wins
                continue
            seen.add(name)
            state = f.state if f.owner_id == user.id else dashboard._visible_state(f.state, keys)
            uids = filters.match(state, rows, fields, username, indexed=indexed)
            out.append((name, {u: self.wanted[u] for u in uids}))
        return out


def run():
    """Exporter tick. Returns the status dict, or None when disabled."""
    Settings.objects.filter(pk=1).update(graph_sync_requested=None)
    s = Settings.get()
    if not s.graph_enabled:
        return None
    started = time.monotonic()
    try:
        status = _sync(s)
    except GraphError as e:
        status = {"error": str(e)}
    except Exception as e:  # anything unexpected still ends up in the status, so the monitoring sees it
        log.exception("outlook sync failed")
        status = {"error": f"{type(e).__name__}: {e}"[:300]}
    status |= {"at": timezone.now().isoformat(), "seconds": round(time.monotonic() - started, 1)}
    Settings.objects.filter(pk=1).update(graph_status=status)  # not save(): don't clobber concurrent admin edits
    return status


def test(s):
    """Settings check for the admin UI: token + group lookup, no writes."""
    try:
        c = Client(s)
        if not s.graph_group_id:
            raise GraphError(msg("graph_no_group"))
        boxes = mailboxes(c, s.graph_group_id)
    except GraphError as e:
        return {"error": str(e)}
    return {"ok": True, "mailboxes": len(boxes), "sample": sorted(m["mail"] for m in boxes.values())[:5]}


# ---------------------------------------------------------------- mail

class GraphMailBackend(BaseEmailBackend):
    """Django mail backend for Microsoft 365: sendMail via Graph with OAuth2 client credentials (app permission
    Mail.Send, best limited to the sending mailbox). Uses the app registration of the Outlook sync."""
    def __init__(self, s, **kwargs):
        super().__init__(**kwargs)
        self.s, self.client = s, None

    def open(self):
        if self.client is None:
            self.client = Client(self.s)
        return True

    def close(self):
        self.client = None

    def send_messages(self, messages):
        self.open()
        for m in messages:
            self.client.call("POST", f"/users/{quote(self.s.mail_graph_sender)}/sendMail", {"message": {
                "subject": m.subject,
                "body": {"contentType": "Text", "content": m.body},
                "toRecipients": [{"emailAddress": {"address": a}} for a in m.to],
            }, "saveToSentItems": False})
        return len(messages)
