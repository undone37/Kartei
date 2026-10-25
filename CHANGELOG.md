# Changelog

All notable changes to Kartei are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). When a version is released, its section becomes the text of the GitHub release.

## [Unreleased]

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

[Unreleased]: https://github.com/undone37/Kartei/compare/v0.3.1-beta...HEAD
[0.3.1-beta]: https://github.com/undone37/Kartei/compare/v0.3.0-beta...v0.3.1-beta
[0.3.0-beta]: https://github.com/undone37/Kartei/compare/v0.2.0-beta...v0.3.0-beta
[0.2.0-beta]: https://github.com/undone37/Kartei/compare/v0.1.0-beta...v0.2.0-beta
[0.1.0-beta]: https://github.com/undone37/Kartei/releases/tag/v0.1.0-beta
