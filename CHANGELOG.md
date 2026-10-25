# Changelog

All notable changes to Kartei are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). When a version is released, its section becomes the text of the GitHub release.

## [Unreleased]

### Added

- Two-factor sign-in (TOTP, RFC 6238) for local and LDAP users: set up under *My account* with a QR code, 8 one-time recovery codes, no reuse of a code; admins can reset it for a user. Switching it on needs the password; an active key can only be replaced after switching off; 5 wrong codes block the second factor for 15 minutes.
- CardDAV `sync-collection` (RFC 6578), in Kartei and the DMZ relay: phones fetch only what changed since their last sync.
- Webhooks: contact changes are POSTed to other systems within seconds, signed with HMAC-SHA256, retried for about a day (*Settings → API*).
- Phone list: the current list (with search and filters) as a printable phone list, by company or by name, with selectable phone and email columns; the browser saves it as PDF.

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

[Unreleased]: https://github.com/undone37/Kartei/compare/v0.2.0-beta...HEAD
[0.2.0-beta]: https://github.com/undone37/Kartei/compare/v0.1.0-beta...v0.2.0-beta
[0.1.0-beta]: https://github.com/undone37/Kartei/releases/tag/v0.1.0-beta
