<img src="logo.svg" alt="Kartei logo" width="96" />

# Kartei

Kartei is a contact directory for persons and companies. It suits organizations that want one well-kept source of contact data for people, phones, email clients and other systems.

- **Your own fields:** admins define the fields: types, options, validation, visibility per role and vCard mapping. Field sets and import mappings are plain JSON files.
- **Fast:**
  - the whole visible directory is held in the browser
  - search covers names, companies, phone numbers in any format and all searchable fields
  - an advanced filter with nested AND/OR/NOT groups, saved filters, favorites, list export and bulk edit
- **Kept up to date:** every contact has a responsible colleague who reviews it regularly, with emailed reminders. Read-only users propose changes or deletions, and maintainers apply, adjust or reject them. Every change is audited, and deleted contacts go to a recycle bin.
- **Data quality:** duplicates are detected and merged, phone numbers are normalized, and a data-quality page lists what needs attention.
- **Distribution:**
  - contacts on iPhone and Android through the Outlook app (Microsoft Graph sync into each Exchange Online mailbox)
  - read-only CardDAV for phones without a mailbox, optionally through a relay in the DMZ
  - AD contact objects
  - configurable CSV/XLSX exports
  - a REST API with tokens (read only, or read and write)
- **Sign-in:** LDAP/Active Directory with role groups, plus local accounts.
- **Email:** via SMTP or Microsoft 365 (OAuth2), with editable texts.
- **Interface:** German and English, light and dark theme, and it can be installed as an app (PWA).

## Documentation

| | English | Deutsch |
|---|---|---|
| User manual (Read only, Maintainer) | [manuals/en/user.md](manuals/en/user.md) | [manuals/de/user.md](manuals/de/user.md) |
| Administrator manual | [manuals/en/admin.md](manuals/en/admin.md) | [manuals/de/admin.md](manuals/de/admin.md) |
| REST API (read and write, for other systems) | [docs/API.md](docs/API.md), [docs/openapi.yaml](docs/openapi.yaml) | |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | |

The `manuals/` folder can be published with GitHub Pages: see the *Documentation* workflow in `.github/workflows/pages.yml`. Every [release](https://github.com/undone37/Kartei/releases) has the manuals attached as PDF; `cd frontend && npm run manuals-pdf` builds them locally into `dist/` (needs pandoc and poppler-utils).

## Quick start with Docker

```sh
cp .env.example .env        # set SECRET_KEY, POSTGRES_PASSWORD, ADMIN_USERNAME/ADMIN_PASSWORD, hosts, EXPORT_HOST_DIR
docker compose up -d --build
```

Instead of building, you can use the released images: set `KARTEI_IMAGE=ghcr.io/undone37/kartei:0.1.0-beta` in `.env`, then `docker compose pull && docker compose up -d --no-build` (relay: `RELAY_IMAGE=ghcr.io/undone37/kartei-relay:0.1.0-beta`).

To use a dedicated PostgreSQL server or cluster instead of the bundled database container, set `DATABASE_URL` and use `compose.external-db.yaml`; the administrator manual (Installation) has the details.

Kartei listens on port 8000; put a TLS reverse proxy in front of it. On the first start it creates the database, a few starter fields (`examples/fields-default.json`) and the admin account from `.env`. Everything else is configured in the browser under *Settings*; the administrator manual walks through it.

### Optional: CardDAV relay in the DMZ

If phones must not reach the internal network, a small read-only CardDAV relay runs on a separate host in the DMZ. Kartei pushes the rendered vCards and the CardDAV login (username and password hash) to it over HTTPS; the relay never opens a connection and holds nothing else. On the DMZ host:

```sh
cp .env.relay.example .env.relay   # SECRET_KEY, ALLOWED_HOSTS, RELAY_PUSH_TOKEN_SHA256 (shown in Kartei → Settings → CardDAV)
docker compose -f compose.relay.yaml up -d --build   # port 8080, own SQLite volume, no frontend build
```

Then enter the relay URL in Kartei under *Settings → CardDAV*. The administrator manual (CardDAV chapter) has the firewall rule, TLS and troubleshooting.

To try Kartei with sample data, seed an empty installation:

```sh
docker compose exec web python manage.py seed_demo --password demo12345
```

This loads the example field set and creates fictional companies and persons, demo users (`mmuster`, `tbauer`: Maintainer; `kkramer`, `lschmidt`: Read only), open reviews, proposals, saved filters, sample exports and a few data-quality cases. It refuses to run if contacts already exist.

## Development

```sh
uv venv .venv -p 3.14 && uv pip install -p .venv -r backend/requirements.txt
cd backend
export DEBUG=1                                   # SQLite, insecure development key
../.venv/bin/python manage.py migrate
ADMIN_USERNAME=admin ADMIN_PASSWORD=admin12345 ../.venv/bin/python manage.py init_app
../.venv/bin/python manage.py seed_demo --password demo12345    # optional sample data
../.venv/bin/python manage.py runserver

cd ../frontend && nvm use && npm ci && npm run dev   # http://localhost:5173, proxies /api to :8000
```

Without the Vite dev server, `npm run build` lets Django serve the app at http://localhost:8000/.

### Tests and CI

```sh
cd backend && DEBUG=1 ../.venv/bin/python manage.py test kartei relay
cd frontend && npm test && npm run check
cd frontend && npm run test:e2e   # browser tests against a running server with seed_demo data (once: npx playwright install chromium)
```

GitHub Actions runs the backend tests on SQLite and PostgreSQL 18, the frontend checks, the browser tests and the Docker build on every push, keeps SBOMs (SPDX and CycloneDX) of the source tree and both images as a build artifact, and scans both images for known vulnerabilities (Grype; results under *Security → Code scanning*; a critical vulnerability with an available fix fails the build). The images of the latest release are scanned again every day. Dependabot proposes weekly updates for Python, npm, the Docker base images and the actions; it stays on the Django LTS and on the newest Python that Django supports.

### Releases

Move the *Unreleased* entries in `CHANGELOG.md` under a new version heading (`## [1.2.0] – date`), then push a tag such as `v1.2.0`. The *Release* workflow publishes `ghcr.io/undone37/kartei` and `ghcr.io/undone37/kartei-relay` for amd64 and arm64 (tags `1.2.0`, `1.2`, `1`, with SBOM and provenance attestations; a tag like `v1.2.0-beta` becomes a pre-release with only the `1.2.0-beta` image tag) and creates the GitHub release – its text is that version's changelog section plus GitHub's generated notes – with the manuals as PDF, the OpenAPI description (`openapi.yaml`) and the SBOM files.

### Screenshots for the manuals

With a development server on port 8000 on a fresh, seeded database (`seed_demo --password demo12345`, and `EXPORT_ROOT=/export` for neutral paths), `cd frontend && npm run screenshots` regenerates all screenshots in `manuals/img/` in German and English (Playwright; run `npx playwright install chromium` once).

## Keyboard shortcuts

| Key | Action |
|---|---|
| `/` | search |
| `↑` `↓` | move through results |
| `Enter` | open the first or selected result |
| `E` | edit |
| `N` / `Shift+N` | new person / company |
| `Ctrl+S` | save |
| `Esc` | cancel |

## Contributing and license

Contributions are welcome – see [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md); changes are listed in the [changelog](CHANGELOG.md). Kartei is free software under the [GNU Affero General Public License v3.0](LICENSE): if you run a modified version for others over a network, you must offer them its source code.
