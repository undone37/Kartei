## What and why

<!-- What does this change, and which problem does it solve? Link the issue: "Closes #123". -->

## How to test

<!-- Steps a reviewer can follow, e.g. with `manage.py seed_demo` data. -->

## Checklist

- [ ] Tests added or updated; `manage.py test kartei relay`, `npm run check` and `npm test` pass
- [ ] Model changes come with a new migration (released migrations are not edited)
- [ ] New UI strings exist in German and English
- [ ] Manuals (`manuals/en` and `manuals/de`) and, for API changes, `docs/API.md` / `docs/openapi.yaml` updated
- [ ] Screenshots regenerated if a documented screen changed
- [ ] `CHANGELOG.md` updated under *Unreleased* (for changes users or administrators notice)
- [ ] No real contact data, credentials or installation-specific names in code, tests or docs
