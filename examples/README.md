# Examples

Starting points for configuring Kartei. All files can be edited, or exported again from a configured Kartei.

| File | Use |
|---|---|
| `fields-default.json` | The few fields of a fresh install (`init_app` loads it; env `INITIAL_FIELDS` points to another file, empty = no fields). |
| `fields-example.json` | A richer field set to start from: person details (salutation, academic title, job title, department, phones, private contact data, assistant/manager), company details (short name, main phone/email/fax, managing director), business address copied from the company, internal contact(s), keywords, customer/contract number and notes – with German/English labels, vCard targets and common German/English CSV column names as import column names. |
| `ad-mapping.json` | AD attribute mapping for the AD contact sync, using the fields of `fields-example.json`. |

## Fields

Field files have the format `kartei-fields`, version 2: a `sections` list (stable `key`, German/English `label`, in
display order) and a `fields` list (in field order) whose `section` names a section key (`null` = "Other"). The
section with the key `person` / `company` is shown in the header block of the person / company form. Version 1 files
(with `section: {"de", "en"}` per field) can still be imported; sections are then found by label or created.

```json
{"format": "kartei-fields", "version": 2,
 "sections": [{"key": "communication", "label": {"de": "Kommunikation", "en": "Communication"}}],
 "fields": [{"key": "email", "label": {"de": "E-Mail", "en": "Email"}, "section": "communication", "...": "..."}]}
```

*Settings → Fields → Import fields*: choose `fields-example.json`, check the preview (new / changed / unchanged per
field), *Apply*. Fields not in the file stay untouched; remove or archive what you don't need afterwards.

## CSV import

*Settings → Import*: upload a CSV file (`;`, `,` or tab separated, UTF-8 or Windows-1252). Kartei suggests a
target for every column from the field keys, labels and import column names (e.g. `Vorname`/`First name`,
`Firma`/`Company`, `E-Mail`/`Email`, `Telefon`/`Phone`, `Straße`/`Street`, `PLZ`/`Postal code`), separately for
persons and companies. Adjust the mapping, run the dry run, check the warnings, then import.

- A kind column (`Art`/`Type` with values like `Person`/`Firma`/`Company`) decides person or company; otherwise an
  ID prefix rule, otherwise rows without a last name but with a company name become companies.
- A mapped ID column (`ID`) is stored as legacy ID: importing the same file again updates those contacts.
- *Export mapping* saves the mapping as JSON; *Import mapping* loads it again. On the command line:
  `python manage.py import_csv contacts.csv --mapping mapping.json` (dry run), add `--commit` to write.

## Active Directory

*Settings → Active Directory → Import mapping*: choose `ad-mapping.json`, adjust, then save.
