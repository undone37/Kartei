# Changelog

All notable changes to Kartei are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). When a version is released, its section becomes the text of the GitHub release.

## [Unreleased]

### Added

- Support for a dedicated PostgreSQL server or cluster instead of the bundled database container (`compose.external-db.yaml`), documented in the administrator manual with TLS, cluster, PgBouncer and migration notes.
- End-to-end browser tests (Playwright) that run in CI on every push and pull request.
- Vulnerability scanning of both images in CI and a daily scan of the latest release's images; results under *Security → Code scanning*.
- Code of conduct and this changelog.
- Images for ARM64 (`linux/arm64`) besides `linux/amd64`, e.g. for ARM servers and Raspberry Pi 4/5.

### Changed

- Faster for large directories: the initial data load takes about half the time (11,000 contacts: 0.8 s → 0.4 s), and CardDAV lists its cards about five times faster.
- A successful CardDAV sign-in is remembered for five minutes instead of checking the password hash on every request of a phone sync.
- Database connections are checked before reuse, so Kartei recovers cleanly after a database failover.
- CI runs on Ubuntu 26.04.

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

[Unreleased]: https://github.com/undone37/Kartei/compare/v0.1.0-beta...HEAD
[0.1.0-beta]: https://github.com/undone37/Kartei/releases/tag/v0.1.0-beta
