# Changelog

All notable changes to Kartei are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). When a version is released, its section becomes the text of the GitHub release.

## [Unreleased]

### Added

- **Data quality over time:** the data-quality page shows a trend chart of the last two years: the share of contacts reviewed within the interval, or the count of any area (e.g. invalid values). The exporter records the numbers once a day; a table view lists them. Monitoring reports `reviewed_ok_percent`.
- **Retention rules:** with *Settings → General → Retention (months)*, contacts nobody has changed or reviewed for that long appear under *Data quality → Retention expired*. Maintainers keep them (counts as reviewed) or move them to the recycle bin. Nothing is deleted automatically; off by default. Monitoring reports `retention_due`.

## [0.6.1-beta] – 2026-11-07

Dependency updates only; nothing to configure. Pull the new image or rebuild; there is no database migration.

### Changed

- **Dependencies:** Django 5.2.19, psycopg 3.3.8, Lucide icons 1.68.0, svelte-check 4.7.8, and the build actions anchore/sbom-action 0.24.3 and anchore/scan-action 7.4.2.

## [0.6.0-beta] – 2026-11-07

The release before 1.0: a full security and code review with its fixes, built-in database backups with a restore test, contacts shared as QR code or vCard, saved filters shared with roles or colleagues, and a map link next to addresses. Renamed users keep their contacts, and large installations (tested with 55 000 contacts) export much faster.

**Upgrading:**
- **Before:** make a backup.
- **Update:** pull the new image or rebuild, and take the new `compose.yaml` (backup volume, read-only containers). Five database migrations (`0009` to `0013`) run automatically when the container starts.
- **Check these before starting:**
  - `SECRET_KEY` must not be the example value, or Kartei won't start.
  - A reverse proxy on another host than Kartei: add its address to `TRUSTED_PROXIES` in `.env`. Otherwise sign-in limits and the audit log see the proxy's address instead of the client's.
  - `/django-admin/` is off; set `DJANGO_ADMIN=1` only if you need it.
- **Backups** start automatically every day at 02:30 into the `backups` volume (or `BACKUP_HOST_DIR`); see *Settings → Backup*.

### Added

- **Input survives an expired session:** if the session expires while a contact is being edited, the input is kept in the browser tab, and after signing in again the form opens with it. Signing out on purpose removes it.
- **`manage.py reset_2fa <user>`:** switches off a user's two-factor sign-in, e.g. for the only admin after losing the authenticator.
- **Export warning:** CSV exports in Windows-1252 report how many values hold characters the encoding can't represent (written as `?`).
- **Nightly security scan:** OWASP ZAP scans a running Kartei every night: the web app signed in as a read-only user (passive), and the REST API with a read token (active). High-risk findings fail the run, and the reports are attached. `.zap/scan.sh` runs it locally.
- **Share a contact:** a QR-code button in the contact header opens a window with the contact as a QR code (iPhone or Android flavour, without photo) to scan with a phone's camera, and *Download vCard*. It replaces the download icon. In the Android QR code, multi-line text (e.g. a description) is written on one line with " · " between the lines, because Android's scanner shows vCard line breaks as a literal \n.
- **Map link:** a pin next to a street opens the address in a map service. The link template is a setting under *General* (default Google Maps; empty = off). Kartei only builds the link.
- **Share saved filters with roles or people:** besides *everyone*, a maintainer can share a saved filter with one or more roles and individual colleagues. The choice is made when saving (*Share with*, default *Only me*) and can be changed later from the dashboard. Each user sees their own filters and those shared with them, their role or everyone.
- **Built-in backups:** the exporter backs up the database every day (default 02:30, kept 14 days) to its own `/backup` volume (`BACKUP_HOST_DIR`, never the export share). Each file is checked with `pg_restore --list`. *Settings → Backup* has *Back up now*, the list of backups, and *Test restore*, which restores the newest backup into a scratch database and compares the row counts. Monitoring reports missing or failed backups. Restoring is a single documented command. The Kartei image now includes the PostgreSQL 18 client tools.
- **Nightly images:** `ghcr.io/undone37/kartei:nightly` and `kartei-relay:nightly` are built from `main` every night when it has changed, plus `:sha-<commit>` per build, for amd64 and arm64. The user menu shows the version as `nightly-<date>-<commit>`. They are for testing only, not releases.

### Changed

- **Renamed users keep their contacts:**
  - A user renamed by the identity provider (SCIM `userName`) keeps their contacts: *Ansprechpartner intern*, *Kontakte intern* and other user fields follow the new name.
  - LDAP/AD users are recognised by their directory id (`objectGUID`/`entryUUID`), so a renamed account stays the same Kartei user and its contacts follow too. Matching by name remains as fallback.
- **CardDAV and API lockout:** the same wrong CardDAV login or API token repeated counts only once towards the lockout, so one phone with an old password no longer locks out everybody behind the same address.
- **Faster with many contacts:**
  - Excel exports no longer slow down with every extra row. With 55 000 contacts an export takes about 10 s; before, it took well over 10 minutes.
  - A phone's first CardDAV sync of all contacts is twice as fast.

### Security

- **Pre-1.0 security review, fixes:**
  - **Django admin:** `/django-admin/` is off unless `DJANGO_ADMIN=1`. It signed in without the second factor, lockout or audit entry.
  - **LDAP:** an LDAP sign-in can no longer take over a local account that has no profile yet (e.g. created with `createsuperuser`).
  - **Client address:** `X-Forwarded-For`/`-Proto` count only from `TRUSTED_PROXIES` (default: loopback and Docker networks). Before, anyone reaching port 8000 directly could fake their address and get around the rate limits and the monitoring allowlist.
  - **Shared rate limits:** sign-in, API, CardDAV and SCIM limits are counted across all server processes (shared cache).
  - **Numbers:** a number like `1e999999999` no longer freezes a server process. Numbers are limited to 40 characters and 30 digits of magnitude.
  - **Formula injection:** Excel exports always write formulas as text. CSV exports put `'` before values Excel would run as a formula (new option, on by default); phone numbers and numbers are unchanged.
  - **Background jobs:** one failing step (an export, a sync) no longer stops the others, and unexpected errors show in the job's status and the monitoring.
  - **Control characters** are removed from text on input, and vCards can no longer be broken up by line breaks in a value.
  - **No hidden data:**
    - The company-to-persons preview, other users' shared filters and proposals by admins no longer reveal fields the user may not see.
    - The history and photo of trashed contacts are hidden from read-only users.
  - **Open redirect:** fixed in the old `/crm/` links.
  - **OIDC:** an email the identity provider marks as unverified can't bind an account.
  - **Example secrets:** Kartei refuses to start with the example `SECRET_KEY` and won't create the first admin with the example password.
  - **Mail:** one rejected address no longer stops review and proposal mails to everyone else.
  - **LDAP user import:**
    - It stops before deactivating more than a set share of directory users (default 20 %).
    - LDAP operations time out after 30 s.
  - **Syslog:** oversized events are shortened for UDP instead of blocking the sender.
  - **Import:** rows of contacts in the recycle bin are skipped, and too-long names skip the row instead of failing the import.
  - **Browser:**
    - Contact data is no longer cached by the browser (`Cache-Control: no-store` on the API).
    - A sign-out during a background sync no longer leaves data in the browser.
    - The offline cache is shown only for 24 h without the server.
    - Background sync now also starts after a normal sign-in.
  - **Containers and workflows:**
    - The `web` and `exporter` containers run read-only without capabilities.
    - Fluent Bit has its own network.
    - The request log no longer contains query strings.
    - GitHub Actions are pinned to commit SHAs, and CI runs with a read-only token.
- **Security headers on every response, static files included:**
  - Content-Security-Policy: scripts only from Kartei itself (the one inline theme script allowed by its hash), no framing, no plugins.
  - Permissions-Policy: no camera, microphone or location.
  - Cross-Origin-Resource-Policy: `same-origin`.
- **Static files:** no longer sent with `Access-Control-Allow-Origin: *`.

## [0.5.0-beta] – 2026-11-06

Kartei can now be monitored and audited like any other production service. There are health and status endpoints for Checkmk, Zabbix and PRTG, sign-ins appear in the audit log, logs are JSON, and audit events and container logs can go to a SIEM via syslog. In the contact view, a click on a tag filters the list.

**Upgrading:**
- **Before:** make a backup.
- **Update:** pull the new image or rebuild, and also take the new `compose.yaml`, whose healthcheck now uses `/healthz`. One database migration (`0008_observability`) runs automatically when the container starts.
- **Defaults:** nothing needs to be configured. Monitoring access, syslog and the Fluent Bit overlay stay off until you set them up.
- **Two things change by default:**
  - Logs are JSON lines; set `LOG_FORMAT=text` if a tool expects plain lines.
  - Sign-in entries in the audit log are deleted after 90 days (*Settings → Monitoring & logging*).

### Added

- **Click to filter:** a click on a tag in a contact's details (multiple selections such as keywords, the internal contact, internal contacts) filters the list for every contact with that value; the contact stays open. Ctrl/⌘-click adds the value to the current filters. The field filters are part of the address (`?f.<field>=<value>`): a filtered list can be bookmarked or shared, and Back undoes the last filter. The active filter chip shows the value instead of a count.
- **Monitoring endpoints:**
  - `/healthz` and `/readyz` (HTTP 503 when the database is unreachable or not migrated).
  - `/api/monitoring/status` reports:
    - the database
    - the exporter heartbeat
    - every enabled export, sync and webhook
    - the syslog sender and free space on `/export`
    - metrics such as contacts, users, open reviews, sign-ins and failed sign-ins
  - The status endpoint needs a monitoring token *and* an allowed client address.
  - It answers as JSON for Checkmk and Zabbix, or with `?format=prtg` for PRTG.
- **New tab *Settings → Monitoring & logging*:** live status, token, allowed addresses, syslog and sign-in retention.
- **Sign-ins in the audit log:**
  - sign-in with its method (password, LDAP, single sign-on)
  - sign-out
  - failed sign-in with its reason
  - refused CardDAV and API access, logged once per address and 15 minutes
  - denied access to admin and maintainer functions
  - New area filter *Sign-ins*.
  - Every audit entry now records the client IP; only admins see it.
  - Sign-in entries are deleted after 90 days (configurable; 0 = keep).
- **Syslog to the SIEM:**
  - Kartei sends every audit event as RFC 5424 syslog over UDP, TCP or TLS, with the JSON log line as message.
  - Contacts: only the names of the changed fields.
  - Failures have severity *warning*.
  - Optionally also application warnings and errors.
  - Configured in the web UI, with a test event.
- **Container logs to the SIEM:** the optional overlay `compose.logging.yaml` runs Fluent Bit and forwards the logs of web, exporter and db as syslog. It's configured in `.env` and skips the audit events Kartei already sends.

### Changed

- **JSON logs:** the application and gunicorn's request log write one JSON object per line. `LOG_FORMAT=text` restores plain lines.
- **Healthchecks:** the compose healthchecks use `/healthz`, and the relay has its own.
- **Contrast:** red badges have more contrast (WCAG AA).

## [0.4.0-beta] – 2026-10-28

Outlook gets personal contact folders, and the CSV import needs much less manual mapping. It suggests fields from column values and creates new fields in the regular field editor.

**Upgrading:** make a backup, then pull the new image or rebuild. One database migration (`0007_graph_personal_folders`) runs automatically when the container starts. Nothing needs to be configured: the personal Outlook folders stay off until you name them in *Settings → Outlook / Exchange*.

### Added

- **Personal Outlook folders:** besides the folder with all contacts, each user can get two folders of their own in their mailbox: contacts they are responsible for, and contacts listing them as internal contact. Turn them on by naming them in *Settings → Outlook / Exchange*.
- **CSV import, matching by content:** columns whose header matches no field get a field picked from their values: email, phone, web address, date, select options or Kartei users. These suggestions are marked *by content* so you can check them.
- **CSV import, new fields:** *New field …* opens the regular field editor next to the mapping, prefilled with the column header and a type suggested from the values (with options for repeating values). Section, visibility and everything else are set there; the field is created on save and becomes the column's target. Saved mappings with the old "new" target still work and now get the suggested type too.

### Changed

- **CSV import, kind column:** a column named *Type*/*Art* is preselected only if at least half of its values are person/company kinds; otherwise any column holding them is picked.

## [0.3.1-beta] – 2026-10-25

Bug-fix release: the CSV import works with real-world files and accepts drag and drop, and server errors are logged again.

**Upgrading:** pull the new image or rebuild. There are no database migrations and nothing to configure.

### Fixed

- **CSV import, failures on real-world files:**
  - Mac line endings (CR only, Excel's "CSV (Macintosh)") and fields over 128 KB no longer end in an error.
  - UTF-16 files (Excel's "Unicode text") are read correctly.
  - An Excel file gets a clear message.
  - Uploads over 10 MB work, up to the reverse proxy's limit.
- **CSV import, drag and drop:** dropping a file on the dashed area now works.
- **Error messages:** server errors (500) and uploads rejected by the reverse proxy (413) say where to look instead of "Something went wrong".
- **Logging:**
  - Server errors now appear with a traceback in `docker compose logs web`; Django's request logger was switched off.
  - gunicorn no longer logs `Control server error: Permission denied: '/home/kartei'`, because its control socket is unused and now off.

## [0.3.0-beta] – 2026-10-25

Third beta, focused on sign-in and people:
- **Sign-in:** single sign-on with any OpenID Connect provider, with users and roles provisioned in advance via SCIM 2.0, and two-factor sign-in that admins can require.
- **People:** a handover for people who leave, and data-protection reports.
- **Contacts:** vCard import, undo from the history, a printable phone list, webhooks and incremental CardDAV sync.

**Upgrading:** make a backup, then pull the new image or rebuild. Three database migrations run automatically when the container starts. Nothing needs to be configured, and new features stay off or voluntary until an admin switches them on. The one exception: emptying the recycle bin now also anonymises the history of the purged contacts (*Settings → General*, on by default).

### Added

- Handover when someone leaves: the user list marks people who left but are still named in contacts; *Hand over …* puts a successor in their place in all user fields (responsible, internal contacts), open reviews follow, every change is in the contacts' history. Users still named in contacts can't be deleted; review mails no longer go to deactivated users.
- Two-factor sign-in (TOTP, RFC 6238) for local and LDAP users: set up under *My account* with a QR code, 8 one-time recovery codes, no reuse of a code; admins can reset it for a user. Switching it on needs the password; an active key can only be replaced after switching off; 5 wrong codes block the second factor for 15 minutes. Admins can require it for administrators or for everyone (*Settings → General*); affected users set it up right after signing in.
- vCard import (*New → Import from vCard*): each card of a `.vcf` file (vCard 2.1, 3.0, 4.0) opens as a pre-filled new-contact form, mapped through the fields' vCard targets incl. photo and company link; read-only users propose instead.
- Undo from the history: maintainers set the fields of a change back to their previous values (*History → Restore*), with a preview and the usual validation and conflict check.
- Data protection: an access report per contact for admins (GDPR Art. 15: all data, history, proposals, reviews and the systems the data goes to; print or PDF), and on permanent deletion the contact's history and audit entries lose name and values (Art. 17, setting *Anonymise the history when deleting permanently*, on by default).
- Single sign-on (*Settings → Single sign-on*): SCIM 2.0 provisioning creates, updates and deactivates users and groups from the identity provider (Entra ID, Okta, Authentik, …) before anyone signs in, with roles from mapped groups; users then sign in with any OpenID Connect provider (discovery, authorization code with PKCE). Only active SCIM or LDAP users can sign in this way, matched once by a chosen claim and then bound to the account's issuer and subject. Kartei's two-factor code is still asked after single sign-on, unless the admin lets the provider's multi-factor authentication count.
- CardDAV `sync-collection` (RFC 6578), in Kartei and the DMZ relay: phones fetch only what changed since their last sync.
- Webhooks: contact changes are POSTed to other systems within seconds, signed with HMAC-SHA256, retried for about a day (*Settings → API*).
- Phone list: the current list (with search and filters) as a printable phone list, by company or by name, with selectable phone and email columns; the browser saves it as PDF.

### Changed

- Accessibility: grey text meets WCAG AA contrast (4.5:1) in the light and dark theme, form controls in the user list and account page have labels; a browser test checks the main screens with axe-core in both themes.

### Fixed

- A user deactivated by the LDAP user import lost access only when their session expired (up to 14 days); now on their next request.

## [0.2.0-beta] – 2026-10-25

Second beta: read-only users can propose new contacts, Kartei can use a dedicated PostgreSQL server or cluster, images are also built for ARM64, and large directories load faster.

**Updating from 0.1.0-beta:** back up the database, then either set `KARTEI_IMAGE=ghcr.io/undone37/kartei:0.2.0-beta` and run `docker compose pull && docker compose up -d --no-build`, or `git pull && docker compose up -d --build`. The database is migrated automatically on start; nothing else has to be changed.

### Added

- The user menu shows the running version and a link to the source code (`KARTEI_SOURCE_URL` for modified versions).
- An upgrade test in CI: the latest release's image with sample data, then this version's migrations; the data must stay unchanged.
- Read-only users can propose new persons and companies (*New → Propose new person/company*); maintainers create, adjust or reject them from the list *Proposals*. Included in the proposal emails and the audit log.
- Support for a dedicated PostgreSQL server or cluster instead of the bundled database container (`compose.external-db.yaml`), documented in the administrator manual with TLS, cluster, PgBouncer and migration notes.
- End-to-end browser tests (Playwright) that run in CI on every push and pull request.
- Vulnerability scanning of both images in CI and a daily scan of the latest release's images; results under *Security → Code scanning*.
- Code of conduct and this changelog.
- Images for ARM64 (`linux/arm64`) besides `linux/amd64`, e.g. for ARM servers and Raspberry Pi 4/5.

### Changed

- Administrators are no longer offered in user fields such as *Internal contact* (nor matched by the CSV import); values set earlier stay.
- Faster for large directories: the initial data load takes about half the time (11,000 contacts: 0.8 s → 0.4 s), and CardDAV lists its cards about five times faster.
- A successful CardDAV sign-in is remembered for five minutes instead of checking the password hash on every request of a phone sync.
- Database connections are checked before reuse, so Kartei recovers cleanly after a database failover.
- CI runs on Ubuntu 26.04.
- Proposal boxes have a full tinted border instead of a coloured stripe on the left.

## [0.1.0-beta] – 2026-10-24

First public beta.

- Contact directory for persons and companies with admin-defined fields, sections, validation and per-role visibility.
- Search over names, companies, phone numbers in any format and all searchable fields; quick filter, advanced filter with nested groups, saved filters, favorites, list export and bulk edit.
- Reviews by the responsible colleague, change and deletion proposals by read-only users, audit log and recycle bin.
- Duplicate detection and merging, phone number normalization, data-quality overview.
- Distribution to phones through Outlook / Exchange (Microsoft Graph) and read-only CardDAV with an optional DMZ relay, Active Directory contact objects, CSV/XLSX exports and a REST API with read-only or read-write tokens.
- LDAP / Active Directory sign-in with role groups and local accounts; email via SMTP or Microsoft 365.
- German and English, light and dark theme, installable as an app.
- Images on the GitHub container registry, manuals as PDF, SBOMs and the OpenAPI description attached to the release.

[Unreleased]: https://github.com/undone37/Kartei/compare/v0.6.1-beta...HEAD
[0.6.1-beta]: https://github.com/undone37/Kartei/compare/v0.6.0-beta...v0.6.1-beta
[0.6.0-beta]: https://github.com/undone37/Kartei/compare/v0.5.0-beta...v0.6.0-beta
[0.5.0-beta]: https://github.com/undone37/Kartei/compare/v0.4.0-beta...v0.5.0-beta
[0.4.0-beta]: https://github.com/undone37/Kartei/compare/v0.3.1-beta...v0.4.0-beta
[0.3.1-beta]: https://github.com/undone37/Kartei/compare/v0.3.0-beta...v0.3.1-beta
[0.3.0-beta]: https://github.com/undone37/Kartei/compare/v0.2.0-beta...v0.3.0-beta
[0.2.0-beta]: https://github.com/undone37/Kartei/compare/v0.1.0-beta...v0.2.0-beta
[0.1.0-beta]: https://github.com/undone37/Kartei/releases/tag/v0.1.0-beta
