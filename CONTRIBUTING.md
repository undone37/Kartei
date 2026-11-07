# Contributing to Kartei

Thanks for helping! Bug reports, ideas, documentation fixes and code are all welcome.

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).

## Before you start

- **Bugs and ideas:** open an [issue](https://github.com/undone37/Kartei/issues/new/choose) using the bug report or feature request form. Never post real contact data, passwords, tokens or internal host names.
- **Security issues:** don't open a public issue. Report them privately via [GitHub security advisories](https://github.com/undone37/Kartei/security/advisories/new).
- **Larger changes:** open an issue first so we can agree on the approach before you spend time on it.

## Development setup

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

GitHub Actions runs the backend tests on SQLite and PostgreSQL 18, the frontend checks, the browser tests, an upgrade test (the latest release's image with sample data, then this version's migrations: the data must be unchanged) and the Docker build on every push, keeps SBOMs (SPDX and CycloneDX) of the source tree and both images as a build artifact, and scans both images for known vulnerabilities (Grype; results under *Security → Code scanning*; a critical vulnerability with an available fix fails the build). The images of the latest release are scanned again every day. Dependabot proposes weekly updates for Python, npm, the Docker base images and the actions; it stays on the Django LTS and on the newest Python that Django supports. Security fixes for known vulnerabilities arrive as Dependabot PRs right away.

Every night, a dynamic security scan (OWASP ZAP, `.github/workflows/zap.yml`) starts Kartei from `main` with demo data and scans the web app signed in as a read-only user and the REST API with a read token (active attacks). Findings of high risk fail it; the reports are attached to the run. Overrides need a reason in `.zap/rules.tsv`. Locally: `.zap/scan.sh` in a clean checkout without `.env` (Docker, curl, jq).

### Releases (maintainers)

Move the *Unreleased* entries in `CHANGELOG.md` under a new version heading (`## [1.2.0] – date`), then push a tag such as `v1.2.0`. The *Release* workflow publishes `ghcr.io/undone37/kartei` and `ghcr.io/undone37/kartei-relay` for amd64 and arm64 (tags `1.2.0`, `1.2`, `1`, with SBOM and provenance attestations; a tag like `v1.2.0-beta` becomes a pre-release with only the `1.2.0-beta` image tag) and creates the GitHub release – its text is that version's changelog section plus GitHub's generated notes – with the manuals as PDF, the OpenAPI description (`openapi.yaml`) and the SBOM files.

### Screenshots and PDF manuals

With a development server on port 8000 on a fresh, seeded database (`seed_demo --password demo12345`, and `EXPORT_ROOT=/export BACKUP_ROOT=/backup` for neutral paths), `cd frontend && npm run screenshots` regenerates all screenshots in `manuals/img/` in German and English (Playwright; run `npx playwright install chromium` once).

The manuals are published to GitHub Pages by the *Documentation* workflow (`.github/workflows/pages.yml`) with every release. `cd frontend && npm run manuals-pdf` builds the PDF versions into `dist/` (needs pandoc and poppler-utils).

## Making a change

1. Fork the repository and create a branch from `main`.
2. Keep the change focused: one topic per pull request.
3. Follow the style of the surrounding code – same naming, idioms and comment density. No new dependency for what a few lines can do.
4. Add or update tests for behaviour you change.
5. Run the checks (CI runs the same):

   ```sh
   cd backend
   DEBUG=1 ../.venv/bin/python manage.py makemigrations --check --dry-run
   DEBUG=1 ../.venv/bin/python manage.py test kartei relay
   cd ../frontend && npm run check && npm test && npm run build
   npm run test:e2e   # browser tests: needs a running server with fresh seed_demo data, see above
   ```

6. Open a pull request against `main` and describe what changed and why.

## Project conventions

- **Accessibility:** the browser tests check the main screens against WCAG 2.1 AA (axe-core, light and dark). Use the colour variables (`--muted`, `--faint`, …) for text instead of new greys, and give every form control a label or `aria-label`.
- **Two languages:** every UI string exists in German and English (`frontend/src/i18n/de.ts` and `en.ts`); a test checks that both have the same keys. The API returns error codes, the frontend translates them.
- **Configurable in the UI:** settings belong in the database and the *Settings* area, not in environment variables or code. Environment variables are only for bootstrap values (database, secret key, hosts, first admin).
- **No customer specifics:** no company names, host names, paths or field sets of a particular installation in code, examples or documentation. Field sets are JSON files in `examples/`.
- **Database migrations:** add a new migration for model changes (`manage.py makemigrations kartei`); never edit or squash migrations that are part of a release. CI's upgrade test runs them on the latest release's data.
- **Audit and safety:** every change to contacts and settings is written to the audit log; anything that deletes asks for confirmation; secrets are stored encrypted or hashed and never returned by the API.
- **Changelog:** add a line under *Unreleased* in [CHANGELOG.md](CHANGELOG.md) for every change users or administrators notice; it becomes the release text.
- **Documentation:** user-facing changes update the manuals in `manuals/en` *and* `manuals/de`; API changes update `docs/API.md` and `docs/openapi.yaml`. If a screen changes, regenerate the screenshots (see *Screenshots and PDF manuals* above).

## Commit messages

Write a short summary line in the imperative ("Add CardDAV relay push guard"), optionally followed by a blank line and a few lines on the why.

## License

Kartei is licensed under the [GNU Affero General Public License v3.0](LICENSE). By contributing, you agree that your contribution is licensed under the same terms.
