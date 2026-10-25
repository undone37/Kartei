# Kartei REST API

Kartei offers a **REST API** so other systems (phone systems, intranet pages, CRM or HR systems, scripts, data warehouses) can read the contact directory and, with a write token, keep it up to date. Every token reads the same contacts and fields a user with the *Read only* role sees. A token with the *Read and write* permission can additionally create, change and delete contacts, with the rights of a *Maintainer* on those fields.

The machine-readable description is [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1). Use it to generate a client or to explore the API in Swagger UI or a similar tool.

## Contents

- [Authentication](#authentication)
- [Permissions per token](#permissions-per-token)
- [Reading](#reading)
  - [List all contacts](#list-all-contacts)
  - [Changes since the last call (delta sync)](#changes-since-the-last-call-delta-sync)
  - [One contact](#one-contact)
- [Writing](#writing)
  - [Create a contact](#create-a-contact)
  - [Change a contact](#change-a-contact)
  - [Delete a contact](#delete-a-contact)
  - [Validation errors](#validation-errors)
  - [Conflicts (optimistic locking)](#conflicts-optimistic-locking)
  - [History and side effects](#history-and-side-effects)
- [The contact object](#the-contact-object)
- [Field values by type](#field-values-by-type)
- [Errors](#errors)
- [Rate limiting](#rate-limiting)
- [Examples](#examples)
- [Recommended sync pattern](#recommended-sync-pattern)
- [Webhooks](#webhooks)
- [User provisioning (SCIM 2.0)](#user-provisioning-scim-20)

## Authentication

Every request needs an API token in the `Authorization` header:

```
Authorization: Bearer kt_…
```

- **Creating tokens:** an administrator creates them under *Settings → API* and chooses *Read only* or *Read and write*. A token is shown **once**, when it's created; Kartei stores only a SHA-256 hash of it. Give each system its own token, so you can revoke one without affecting the others.
- **Revoking:** a revoked token stops working immediately.
- **Last used:** the token list shows when each token was last used (updated at most once per minute).
- **Scope:** tokens only work for `/api/v1/…`. They don't work for the web interface or any other endpoint. No session cookie or CSRF token is involved.
- **Transport:** always call the API over HTTPS. The token is a password – a write token even more so.
- **Independent of people:** a token belongs to Kartei, not to the admin who created it. It keeps working when that admin leaves, and two-factor sign-in doesn't apply to it.

## Permissions per token

| Permission | Can do |
|---|---|
| *Read only* (default) | `GET` the contacts. Any `POST`, `PATCH` or `DELETE` returns `403 forbidden`. |
| *Read and write* | Everything a read token can, plus create, change and delete contacts. |

A write token acts like a **Maintainer who only sees what *Read only* users see**:

- It can set the core fields (`first_name`, `last_name`, `name`, `company`) and every field that is **visible to *Read only* users and editable by maintainers**.
- Fields **editable only by admins** can't be changed: sending a different value returns the validation code `forbidden` for that field (sending the current value unchanged is fine).
- Fields **visible only to maintainers or admins** don't exist for the API: sending them returns `unknown_field`. Values stored there (set in the web interface) are kept untouched when the API changes other fields.
- It can't restore or purge contacts from the recycle bin, change images, confirm reviews or decide proposals – that stays in the web interface.

## Reading

Base URL: `https://<your-kartei-host>/api/v1`. All responses are `application/json`.

### List all contacts

```
GET /api/v1/contacts
```

Returns every contact that isn't in the recycle bin:

```json
{
  "cursor": "2026-10-24T20:30:00.123456+00:00",
  "full": true,
  "contacts": [ { …contact… }, { …contact… } ]
}
```

| Key | Meaning |
|---|---|
| `cursor` | Server time of this response. Pass it as `updated_since` next time to get only the changes. |
| `full` | `true`: this is the complete list. Replace your copy with it. |
| `contacts` | All contacts (see [the contact object](#the-contact-object)), persons and companies. |

### Changes since the last call (delta sync)

```
GET /api/v1/contacts?updated_since=<cursor>
```

Returns only what changed since the given point in time:

```json
{
  "cursor": "2026-10-24T20:45:00.654321+00:00",
  "contacts": [ { …changed or new contact… } ],
  "deleted": [ "8f0c6a2e-…", "…" ]
}
```

| Key | Meaning |
|---|---|
| `cursor` | Use this value for the next call. |
| `contacts` | Contacts created or changed since `updated_since`. Persons also appear when their company changed, e.g. was renamed, so `company_name` stays correct. |
| `deleted` | UIDs of contacts that were deleted (moved to the recycle bin) since then. Remove them from your copy. |

Notes:

- **Overlap:** the server looks back 5 seconds before `updated_since`, so a contact can appear in two consecutive responses. Treat updates as "insert or replace" by `uid`.
- **Too old:** if `updated_since` is older than the recycle-bin retention configured in Kartei, deletions may already have been purged. Kartei then returns the **full list** with `"full": true` instead, and you should replace your copy.
- **Format:** `updated_since` must be an ISO 8601 timestamp, ideally the `cursor` exactly as received. URL-encode it (`+` → `%2B`). A timestamp without a timezone is read in the server's timezone.

### One contact

```
GET /api/v1/contacts/<uid>
```

Returns one contact object, or `404` if the UID is unknown or the contact is in the recycle bin. The response carries an `ETag: "<version>"` header; you can send it back as `If-Match` when [changing](#change-a-contact) the contact.


## Writing

Only tokens with the *Read and write* permission (see [permissions](#permissions-per-token)). Send JSON with `Content-Type: application/json`. Read tokens get `403 {"error": "forbidden"}`.

### Create a contact

```
POST /api/v1/contacts
```

Body (the same shape the web interface uses):

| Key | Required | Meaning |
|---|---|---|
| `kind` | yes | `"person"` or `"company"` |
| `first_name`, `last_name` | persons: at least one | Spaces are trimmed and collapsed. |
| `name` | companies: yes | Company name. |
| `company` | no | Persons: UID of a company (not in the recycle bin), or `null`. |
| `data` | no | `{field key: value}`, values as described under [field values by type](#field-values-by-type). |

Other keys (e.g. `uid`, `display_name`) are ignored.

```http
POST /api/v1/contacts
Authorization: Bearer kt_…
Content-Type: application/json

{
  "kind": "person",
  "first_name": "Anna",
  "last_name": "Schmidt",
  "company": "d8c52355-6825-4f0c-a0f6-1300ce45a0e6",
  "data": {
    "job_title": "Einkauf",
    "email": "anna.schmidt@musterfirma.example",
    "mobile": "0170 1234567",
    "keywords": ["Kunde"]
  }
}
```

Response `201 Created` with the new [contact](#the-contact-object) (phone numbers already normalized if that's enabled):

```json
{
  "uid": "5b1c7a0e-3f7d-4c55-9a3e-0d6f1b2c3d4e",
  "kind": "person",
  "legacy_id": "",
  "first_name": "Anna",
  "last_name": "Schmidt",
  "name": "",
  "company": "d8c52355-6825-4f0c-a0f6-1300ce45a0e6",
  "company_name": "Musterfirma Energie AG",
  "display_name": "Anna Schmidt",
  "data": {
    "job_title": "Einkauf",
    "email": "anna.schmidt@musterfirma.example",
    "mobile": "+49 170 1234567",
    "keywords": ["Kunde"]
  },
  "version": 1,
  "updated_at": "2026-10-24T21:02:11.402871+00:00"
}
```

### Change a contact

```
PATCH /api/v1/contacts/<uid>
```

A **partial update**: only the keys you send are changed.

- Core keys (`first_name`, `last_name`, `name`, `company`) are set if present. `"company": null` removes a person from their company.
- `data` is **merged** into the existing values: keys you don't send stay as they are. A value of `null` or `""` (or `[]` for lists) **clears** that field.
- `kind` can't be changed (`read_only` validation error if it differs).
- `version` (optional): the `version` you last read. If the contact has changed since, you get `409 version_conflict` instead of overwriting the other change (see [conflicts](#conflicts-optimistic-locking)). Instead of the body key you can send the header `If-Match: "<version>"`. Without either, the last write wins.

```http
PATCH /api/v1/contacts/5b1c7a0e-3f7d-4c55-9a3e-0d6f1b2c3d4e
Authorization: Bearer kt_…
Content-Type: application/json

{ "version": 1, "data": { "job_title": "Leitung Einkauf", "mobile": null } }
```

Response `200 OK` with the updated contact (`version` is now `2`). If nothing actually changed, the contact is returned unchanged with the same `version` and nothing is logged.

### Delete a contact

```
DELETE /api/v1/contacts/<uid>
DELETE /api/v1/contacts/<uid>?with_persons=1
```

Moves the contact to the **recycle bin**, exactly like deleting in the web interface: maintainers can restore it there until it's purged after the configured retention. Open reviews of the contact are cancelled. Delta syncs report it under `deleted`.

For a company, `?with_persons=1` also moves all its persons to the recycle bin. Without it, the persons stay and keep pointing to the (deleted) company.

```json
{ "ok": true, "deleted": ["d8c52355-6825-4f0c-a0f6-1300ce45a0e6", "5b1c7a0e-3f7d-4c55-9a3e-0d6f1b2c3d4e"] }
```

`deleted` lists the UIDs moved to the recycle bin (the contact itself first). A contact that is already in the recycle bin returns `404`.

### Validation errors

Invalid input changes nothing and returns `400` with a code per field:

```json
{
  "error": "validation",
  "fields": {
    "last_name": "required",
    "email": "invalid_email",
    "customer_no": "forbidden",
    "contract_no": "unknown_field"
  }
}
```

The codes are the same the web interface shows. The most common ones:

| Code | Meaning |
|---|---|
| `required` | A required value is missing (persons: first or last name; companies: name; fields marked *required*). |
| `too_long` | Name longer than 100 (persons) or 200 (companies) characters. |
| `invalid` | `kind`, `version` or `data` has the wrong form. |
| `read_only` | `kind` can't be changed. |
| `invalid_company` | `company` is not the UID of a company outside the recycle bin. |
| `unknown_field` | No such field for this kind of contact, archived, or not visible to *Read only* users. |
| `forbidden` | The field can only be changed by admins. |
| `invalid_email`, `invalid_url`, `invalid_phone`, `invalid_integer`, `invalid_number`, `invalid_date`, `invalid_option`, `invalid_user`, `invalid_contact`, `pattern_mismatch`, `too_small`, `too_large`, `too_long` | The value doesn't fit the field's type, options, range or pattern. |

A body that isn't a JSON object returns `400 {"error": "invalid_json"}`.

### Conflicts (optimistic locking)

If you send `version` (or `If-Match`) and the contact was changed in the meantime – in the web interface or by another system – the change is rejected:

```json
{
  "error": "version_conflict",
  "contact": { …the current contact, with its current "version"… }
}
```

Status `409`. Merge your change into the current state from `contact` and send it again with the new `version`.

### History and side effects

API changes behave like changes in the web interface:

- Every created, changed or deleted contact gets an entry in its **history** and in the admin's audit log. The user shown is **`api:<token name>`**, e.g. `api:CRM-Sync`. Give tokens recognizable names.
- Phone numbers are normalized to international form if that's enabled.
- New values in select fields that allow new options become options of the field (logged as a field change by the same `api:<token name>`).
- If a change moves the responsibility of a contact with an open review (e.g. a new internal contact), the review follows the new responsible person.
- User fields (person responsible, internal contacts) hold user names. When an admin [hands over](../manuals/en/admin.md#leavers) the contacts of someone who left, those values change to the successor; every affected contact is a normal change (new `version`, delta sync, `contact.updated`).
- A contact moved to the recycle bin is reported in the delta sync's `deleted`. When it is later purged, it is gone for good, and its history may be anonymised (setting *Anonymise the history when deleting permanently*).
- Changed contacts appear in everyone's list right away and in the next delta sync of all API clients – including your own, so expect to see your own changes there.

## The contact object

```json
{
  "uid": "2148941b-9a89-4b3a-aad1-ea2bea426fba",
  "kind": "person",
  "legacy_id": "",
  "first_name": "David",
  "last_name": "Becker",
  "name": "",
  "company": "d8c52355-6825-4f0c-a0f6-1300ce45a0e6",
  "company_name": "Musterfirma Energie AG",
  "display_name": "David Becker",
  "data": {
    "salutation": "Herr",
    "job_title": "Buchhaltung",
    "department": "Finanzen",
    "email": "david.becker@musterfirma.example",
    "phone_work": "+49 511 1000-11",
    "mobile": "+49 170 5614226",
    "work_street": "Testallee 2",
    "work_zip": "30159",
    "work_city": "Hannover",
    "work_country": "Deutschland",
    "keywords": ["Kunde"],
    "internal_contact": "kkramer"
  },
  "version": 7,
  "updated_at": "2026-10-24T20:21:50.115627+00:00"
}
```

| Key | Type | Meaning |
|---|---|---|
| `uid` | string (UUID) | Permanent ID of the contact. Never changes. |
| `kind` | `"person"` \| `"company"` | |
| `legacy_id` | string | ID from a system the data was imported from; empty if none. |
| `first_name`, `last_name` | string | Persons only (empty for companies). |
| `name` | string | Company name (empty for persons). |
| `company` | string (UUID) \| null | Persons: the UID of their company. |
| `company_name` | string \| null | Persons: the name of their company. |
| `display_name` | string | "First Last" for persons, the name for companies. |
| `data` | object | All admin-defined fields that have a value, keyed by field key. Empty fields are left out. |
| `version` | integer | Increases with every change. Send it with a [`PATCH`](#change-a-contact) to detect conflicts. |
| `updated_at` | string (ISO 8601) | Last change of the contact. |

**Which fields appear in `data`** depends on your installation: administrators define the fields under *Settings → Fields* and can export their definitions as JSON. Only fields visible to *Read only* users are included; fields restricted to maintainers or admins never appear in the API.

## Field values by type

The same types are used when writing. Kartei also accepts a few lenient inputs and stores the normalized form: phone numbers in national form (normalized if enabled), decimals as numbers or strings with `,` or `.`.

| Field type | Value in `data` | Example |
|---|---|---|
| Text, long text | string | `"Buchhaltung"` |
| Phone | string, normalized to international form if enabled | `"+49 511 1000-11"` |
| Email, URL | string | `"info@example.com"`, `"https://example.com"` |
| Integer | number | `42` |
| Decimal | string (exact decimal, `.` as separator) | `"1234.50"` |
| Date | string `YYYY-MM-DD` | `"1994-01-01"` |
| Yes/No | boolean | `true` |
| Single select | string: the option's value | `"Herr"` |
| Multi select | array of option values | `["Kunde", "Energie"]` |
| User | string: Kartei username | `"kkramer"` |
| Users | array of usernames | `["kkramer", "mmuster"]` |
| Contact | string: UID of a person, or free text if the field allows it | `"5b1c…"` or `"Dr. Hans Beispiel"` |

## Errors

Errors return a JSON body with a machine-readable code:

```json
{ "error": "unauthenticated" }
```

| Status | `error` | When |
|---|---|---|
| 400 | `invalid_updated_since` | `updated_since` is not a valid timestamp. |
| 400 | `invalid_json` | The request body is not a JSON object. |
| 400 | `validation` | Invalid values; details per field in `fields` (see [validation errors](#validation-errors)). |
| 401 | `unauthenticated` | Token missing, unknown or revoked. The response has a `WWW-Authenticate: Bearer` header. |
| 403 | `forbidden` | Writing with a *Read only* token. |
| 404 | `not_found` | Contact unknown or in the recycle bin. |
| 405 | `method_not_allowed` | A method the endpoint doesn't support (e.g. `PUT`). |
| 409 | `version_conflict` | The contact changed since the `version` you sent; the current one is in `contact`. |
| 429 | `too_many_attempts` | Too many failed authentications from your address (see below). |

## Rate limiting

After **20 failed authentications within 15 minutes** from the same client address, further requests from that address get `429` until the window passes. Successful requests (reading and writing) are not limited. Behind a reverse proxy, Kartei uses the client address from `X-Forwarded-For`.

There's no limit on successful requests. Use the delta sync rather than fetching the full list every few seconds.

## Examples

### curl

```sh
TOKEN=kt_…
curl -H "Authorization: Bearer $TOKEN" https://kartei.example.com/api/v1/contacts
curl -H "Authorization: Bearer $TOKEN" "https://kartei.example.com/api/v1/contacts?updated_since=2026-10-24T20:30:00%2B00:00"
curl -H "Authorization: Bearer $TOKEN" https://kartei.example.com/api/v1/contacts/2148941b-9a89-4b3a-aad1-ea2bea426fba

# write token: create, change (with conflict check), delete
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"kind": "company", "name": "Beispiel GmbH", "data": {"company_phone": "030 1234567"}}' \
     https://kartei.example.com/api/v1/contacts
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H 'If-Match: "1"' \
     -d '{"data": {"website": "https://beispiel.example"}}' \
     https://kartei.example.com/api/v1/contacts/<uid>
curl -X DELETE -H "Authorization: Bearer $TOKEN" "https://kartei.example.com/api/v1/contacts/<uid>?with_persons=1"
```

### Python

```python
import requests

BASE = "https://kartei.example.com/api/v1"
session = requests.Session()
session.headers["Authorization"] = "Bearer kt_…"

def full():
    r = session.get(f"{BASE}/contacts", timeout=30)
    r.raise_for_status()
    body = r.json()
    return {c["uid"]: c for c in body["contacts"]}, body["cursor"]

def delta(contacts, cursor):
    r = session.get(f"{BASE}/contacts", params={"updated_since": cursor}, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("full"):                      # cursor too old: start over
        contacts.clear()
    for c in body["contacts"]:
        contacts[c["uid"]] = c                # insert or replace
    for uid in body.get("deleted", []):
        contacts.pop(uid, None)
    return body["cursor"]

contacts, cursor = full()
# … later, e.g. every 5 minutes:
cursor = delta(contacts, cursor)
```

### Python: writing

```python
def create_person(first, last, company_uid=None, **data):
    r = session.post(f"{BASE}/contacts", timeout=30, json={
        "kind": "person", "first_name": first, "last_name": last, "company": company_uid, "data": data})
    if r.status_code == 400:
        raise ValueError(r.json()["fields"])   # e.g. {"email": "invalid_email"}
    r.raise_for_status()
    return r.json()

def update(contact, data):
    """Change some fields; on a conflict retry once on the current state."""
    for _ in range(2):
        r = session.patch(f"{BASE}/contacts/{contact['uid']}", timeout=30,
                          json={"version": contact["version"], "data": data})
        if r.status_code != 409:
            break
        contact = r.json()["contact"]          # someone else changed it: decide again on fresh data
    r.raise_for_status()
    return r.json()

p = create_person("Anna", "Schmidt", job_title="Einkauf", email="anna.schmidt@musterfirma.example")
p = update(p, {"job_title": "Leitung Einkauf", "mobile": None})   # None clears the field
session.delete(f"{BASE}/contacts/{p['uid']}", timeout=30).raise_for_status()   # to the recycle bin
```

### Looking up a caller by phone number

Phone numbers are stored as typed (or in international form if normalization is on), so compare digits:

```python
import re

def digits(s):
    d = re.sub(r"\D", "", s or "")
    return "0" + d[2:] if d.startswith("49") else d   # +49 511 … and 0511 … compare equal

index = {}
for c in contacts.values():
    for key, value in c["data"].items():
        if isinstance(value, str) and re.fullmatch(r"[+\d][\d\s()/-]{4,}", value):
            index[digits(value)] = c

caller = index.get(digits("0511 1000-11"))
print(caller["display_name"] if caller else "unknown")
```

## Recommended sync pattern

1. Fetch the full list once and store each contact by `uid`, together with the `cursor`.
2. Every few minutes, call `?updated_since=<cursor>`:
   - If the response has `"full": true`, replace everything.
   - Otherwise insert or replace every contact in `contacts` and remove every UID in `deleted`.
   - Store the new `cursor`.
3. Join persons and companies via `company` (UID), or simply use `company_name`.
4. When writing back, send the `version` you have stored. On `409`, take the current contact from the response, re-apply your change and try again.

## Webhooks

Instead of polling, a system can be notified right away: an administrator adds a **webhook** under *Settings → API* (name, URL, events) and gets a secret, shown once. Kartei then POSTs every contact change to that URL, usually within 10 seconds.

### Events

| Event | When |
|---|---|
| `contact.created` | a person or company was created (also by import or an accepted proposal) |
| `contact.updated` | a contact was changed (form, bulk edit, import, merge, REST API, accepted proposal, restore from the history, handover to a successor) |
| `contact.deleted` | a contact was moved to the recycle bin |
| `contact.restored` | a contact was restored from the recycle bin |
| `ping` | the *Send test event* button |

A webhook without selected events receives all of them.

### Request

```http
POST /your/hook HTTP/1.1
Content-Type: application/json
User-Agent: Kartei/0.3.0
X-Kartei-Event: contact.updated
X-Kartei-Delivery: 4711
X-Kartei-Timestamp: 1793000000
X-Kartei-Signature: sha256=5d41402abc4b2a76b9719d911017c592…

{"id": 4711, "event": "contact.updated", "occurred_at": "2026-10-25T09:14:03.120000+00:00",
 "uid": "8f0c…", "contact": { …the contact object… }}
```

- `contact` is [the contact object](#the-contact-object) as `GET /api/v1/contacts/<uid>` returns it, with the fields visible to *Everyone*, **in its state when the event is sent**. It is `null` if the contact is no longer live (e.g. for `contact.deleted`). Treat the event as "this contact changed" and the content as its latest state.
- `id` (also in `X-Kartei-Delivery`) identifies the delivery; a retry sends the same `id`, so you can ignore duplicates.
- Events are sent in the order they happened; after a failure, later events are not held back, so check `occurred_at` or compare the `version` if order matters.

### Verifying the signature

`X-Kartei-Signature` is `sha256=` followed by the hex HMAC-SHA256 of `"<X-Kartei-Timestamp>.<raw body>"` with the webhook's secret. Check it on the raw bytes, before parsing the JSON, and reject old timestamps to block replays:

```python
import hashlib, hmac, time

def verify(secret: str, headers, body: bytes, max_age=300) -> bool:
    ts = headers["X-Kartei-Timestamp"]
    expected = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers["X-Kartei-Signature"]) and abs(time.time() - int(ts)) < max_age
```

### Answers and retries

- Any `2xx` answer counts as delivered; answer quickly (within 5 seconds) and do the work afterwards. Redirects are not followed and count as failures, so give the final URL.
- Anything else (error status, timeout, no connection) is retried after 1, 5, 30, 120, 360 and 720 minutes; after the 7th failed attempt the delivery is given up. *Settings → API* shows the last result and the number of waiting and given-up deliveries.
- Deliveries are kept for 30 days. If a receiver was down for longer than the retries, reconcile with the [delta sync](#changes-since-the-last-call-delta-sync).

## User provisioning (SCIM 2.0)

Identity providers (Entra ID, Okta, Authentik, …) create, change and deactivate Kartei users and push groups through SCIM 2.0 ([RFC 7643](https://www.rfc-editor.org/rfc/rfc7643), [RFC 7644](https://www.rfc-editor.org/rfc/rfc7644)). This is separate from the contact API: it has its own token, which never reads contacts, and API tokens never reach SCIM.

- **Base URL:** `https://kartei.example.com/scim/v2`
- **Authentication:** `Authorization: Bearer <SCIM token>`. An admin generates the token under *Settings → Single sign-on*; it is shown once, and Kartei stores only its SHA-256. 20 failed attempts from one address block it for 15 minutes.
- **Content type:** `application/scim+json` both ways. Errors use the SCIM error format (`schemas`, `status`, `detail`, `scimType`).

| Endpoint | Methods |
|---|---|
| `/Users` | `GET` (filter `userName eq "…"` or `externalId eq "…"`, `startIndex`, `count` up to 200), `POST` |
| `/Users/{id}` | `GET`, `PUT`, `PATCH`, `DELETE` |
| `/Groups` | `GET` (filter `displayName eq "…"` or `externalId eq "…"`, `excludedAttributes=members`), `POST` |
| `/Groups/{id}` | `GET`, `PUT`, `PATCH`, `DELETE` |
| `/ServiceProviderConfig`, `/ResourceTypes`, `/Schemas` | `GET` |

User attributes: `userName`, `externalId`, `name.givenName`, `name.familyName`, `emails` (the primary or first value), `active`; anything else is ignored. Group attributes: `displayName`, `externalId`, `members` (user ids).

Notes:

- `PATCH` takes `add`, `replace` and `remove`, in any case, with or without `path`. This includes paths like `emails[type eq "work"].value`, `active` as `"False"` and `members[value eq "<id>"]`.
- `DELETE /Users/{id}` and `"active": false` both **deactivate** the user. Users are never deleted, so the history keeps their names.
- `DELETE /Groups/{id}` deletes the group.
- A user is active in Kartei when `active` is true and one of its groups is mapped to a role; the highest role wins.
- SCIM sees only users it created. A `userName` that already exists in Kartei answers `409` with `scimType: uniqueness`.

```sh
curl -H "Authorization: Bearer $SCIM_TOKEN" -H "Content-Type: application/scim+json" \
  -d '{"schemas":["urn:ietf:params:scim:schemas:core:2.0:User"],"userName":"alice@example.com",
       "name":{"givenName":"Alice","familyName":"Example"},"emails":[{"value":"alice@example.com","primary":true}],"active":true}' \
  https://kartei.example.com/scim/v2/Users
```

