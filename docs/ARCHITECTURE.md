# Kartei – architecture

## Overview

```
browser (Svelte SPA, PWA) ──JSON/session──▶ web (Django + gunicorn) ──▶ PostgreSQL
phones (CardDAV) ─────────────Basic auth──▶ web
other systems (REST API) ─────Bearer token▶ web
                                            exporter (same image) ──▶ export files, Active Directory, Microsoft Graph, SMTP
                                               │
                         internal network      │ HTTPS POST /push, Bearer push token (optional)
  ─────────────────────────────────────────────┼──────────────────────────────────────────────
                         DMZ                   ▼
phones (CardDAV) ─────────────Basic auth──▶ carddav-relay (same image, target relay; own SQLite)
```

- **`web`** serves the single-page app, the JSON API (`/api/…`), the token API (`/api/v1/…`) and CardDAV (`/carddav/`).
- **`exporter`** runs the periodic jobs at the export interval set in the UI. It also checks every 10 s for "sync now" requests.
  - exports
  - recycle-bin purge
  - Outlook and AD syncs
  - daily AD user import
  - review scheduling and notification emails
  - webhook deliveries (every 10 s)
- **`carddav-relay`** (optional, separate host in the DMZ, `compose.relay.yaml`) serves the same read-only CardDAV from cards Kartei pushes to it. It runs `config.relay_settings`: only the `relay` app, no Kartei app, admin, sessions or static files, its own SQLite file. It never opens a connection; the `exporter` pushes at the export interval or on "sync now".
- **Configuration:** everything except bootstrap values (database URL, secret key, hosts, initial admin) lives in the database and is edited in the UI. Secrets such as bind passwords and client secrets are stored encrypted with a key derived from `SECRET_KEY`.

## Backend (`backend/`)

The Django project is `config`; the main app is `kartei`. The DMZ relay is the app `relay` with its own settings (`config/relay_settings.py`, `config/relay_urls.py`).

| Module | Purpose |
|---|---|
| `models.py` | `Record` (person or company; core columns plus a JSON `data` for all admin-defined fields), `FieldDef`, `FieldSection`, `Settings` (singleton), `Profile` (role, language), `Review`, `Proposal`, `SavedFilter`, `ApiToken`, `ExportProfile`, `AuditEntry`, `NotDuplicate` |
| `api.py` | JSON API for the SPA: session auth with CSRF, role checks (`needs`), error codes instead of texts |
| `validation.py` | per-type validation and normalization of field values (incl. phone numbers) |
| `audit.py` | append-only audit log with `{key: [old, new]}` diffs, secrets masked |
| `vcard.py`, `dav.py`, `carddav.py` | vCard 3.0 rendering (iOS and Android flavours); the storage-independent read-only CardDAV protocol incl. `sync-collection` (`dav.py`, also used by the relay) and the built-in server on the Kartei database (`carddav.py`) |
| `relaypush.py` | push to the DMZ relay: fetch the relay's `{uid: etag}`, send changed cards (both flavours), deletions and the CardDAV login; guards for 0 contacts and too many deletions |
| `graph.py` | Microsoft Graph client: Outlook contact-folder sync and the Microsoft 365 mail backend |
| `adsync.py`, `ldapusers.py`, `auth.py` | AD contact objects in one OU, importing role-group members, LDAP sign-in configured from the database |
| `exports.py` | CSV/XLSX exports with column mapping, atomic writes and a shrink guard |
| `importer.py` | CSV import with a column mapping (JSON) and kind rules |
| `reviews.py` | review scheduling, digests, reminders, proposal emails and email templates |
| `quality.py`, `batch.py`, `dashboard.py` | data quality and duplicates, company-to-person batch changes, dashboard/saved filters/list export/bulk edit |
| `api_v1.py` | REST API with bearer tokens (read, or read and write per token); admin endpoints for tokens and webhooks |
| `webhooks.py` | webhooks: every contact change in the audit log queues an event per webhook (same transaction); the `exporter` sends them every 10 s, HMAC-signed, with retries |
| `scim.py`, `oidc.py` | SCIM 2.0 server for user and group provisioning (roles from mapped groups, never deletes users); OpenID Connect sign-in with discovery and PKCE, bound to issuer + subject |
| `relay/` (separate app) | DMZ relay: `Card` (uid, etag, iOS and Android vCard), `Book` (ctag, CardDAV username and password hash); `GET/POST /push` with a bearer token checked against `RELAY_PUSH_TOKEN_SHA256` in constant time; CardDAV via `kartei.dav` |

Text stored for the UI, such as export status or import warnings, is an encoded message code (`msg.py`) that the frontend translates.

## Frontend (`frontend/`)

Svelte 5 with runes, Vite and TypeScript.

- **Data:** after sign-in, `/api/bootstrap` delivers all records and fields the user may see, plus the field sections. They're kept in memory and cached in IndexedDB. `/api/changes?since=` brings only the changes, every 30 s and when the window regains focus. Search, filters and lists therefore run locally without round trips.
- **Code layout:**
  - `src/lib/`: store, search, advanced filter, validation, formatting, i18n, router
  - `src/components/`: lists, views and forms
  - `src/settings/`: the admin area, loaded lazily
- **Translations:** every UI string exists in German and English (`src/i18n/`). A test checks parity and every key the code uses.

## Data model notes

- **Persons and companies** share one table, so search, sync and CardDAV work on one list. A person links to its company, which means a renamed company is reflected everywhere.
- **Admin-defined fields** live in `Record.data` and are described by `FieldDef`:
  - type
  - options
  - validation
  - visibility and editability per role
  - vCard target
  - copy-from-company source
  - import aliases
  - section: a `FieldSection` (key, DE/EN label, order) or none ("Other"); the SPA groups fields by section order, then field order
- **Conflicts:** records carry a `version` for optimistic locking.
- **Deletion:** deleting is a soft delete (recycle bin); purging is permanent. A company can take its live persons along (`DELETE /api/records/<uid>?with_persons=1`, bulk `with_persons`); `api.delete_with_persons()` does it in one transaction and marks each person's audit entry `with_company`. In the SPA, every destructive action asks first through one `<dialog>` (`components/ConfirmDialog.svelte`, `confirmDialog()` in `lib/confirm.svelte.ts`).
- **Reviews and proposals:**
  - Reviews go to the user in the record's first single-user field.
  - Proposals store the proposed values together with the values they were based on, so the decision screen can show what changed since.

## Tests

- **Backend:** Django tests in `backend/kartei/test*.py` and `backend/relay/tests.py` (`manage.py test kartei relay`; the test run installs the relay app next to Kartei). They include vCard reference cards and fake LDAP and Graph servers, and run on SQLite and PostgreSQL in CI.
- **Frontend:** node:test unit tests in `frontend/tests/` for search, the advanced filter, validation, selection and translations.
