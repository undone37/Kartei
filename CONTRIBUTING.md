# Contributing to Kartei

Thanks for helping! Bug reports, ideas, documentation fixes and code are all welcome.

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).

## Before you start

- **Bugs and ideas:** open an [issue](https://github.com/undone37/Kartei/issues/new/choose) using the bug report or feature request form. Never post real contact data, passwords, tokens or internal host names.
- **Security issues:** don't open a public issue. Report them privately via [GitHub security advisories](https://github.com/undone37/Kartei/security/advisories/new).
- **Larger changes:** open an issue first so we can agree on the approach before you spend time on it.

## Development setup

The [README](README.md#development) has the full setup. In short: Python 3.14 with the packages from `backend/requirements.txt`, Node 26 (`nvm use`) for the frontend, SQLite in development (`DEBUG=1`). `manage.py seed_demo --password demo12345` fills an empty database with sample data.

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
   npm run test:e2e   # browser tests: needs a running server with fresh seed_demo data, see the README
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
- **Documentation:** user-facing changes update the manuals in `manuals/en` *and* `manuals/de`; API changes update `docs/API.md` and `docs/openapi.yaml`. If a screen changes, regenerate the screenshots (see the README, *Screenshots for the manuals*).

## Commit messages

Write a short summary line in the imperative ("Add CardDAV relay push guard"), optionally followed by a blank line and a few lines on the why.

## License

Kartei is licensed under the [GNU Affero General Public License v3.0](LICENSE). By contributing, you agree that your contribution is licensed under the same terms.
