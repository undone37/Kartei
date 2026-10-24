"""Contact CSV import with a column mapping. Idempotent where a legacy ID is mapped: upserts on legacy_id.

Mapping document (also what the SPA downloads/uploads):
  {"format": "kartei-import-mapping", "version": 1,
   "columns": {header: {"person": target, "company": target}},
   "kind": {"column": header or "", "company_prefix": "", "person_prefix": ""}}
Targets: "" (ignore), "core:legacy_id", "core:first_name", "core:last_name", "core:company" (person: link by
company name), "core:name" (company name), "field:<key>", "new" (create a text field named after the header).
Columns missing in a mapping get the suggestion (core aliases, field key, labels, import aliases).
"""
import csv
import io
import re
import unicodedata

from django.contrib.auth.models import User
from django.db import transaction
from django.utils.text import slugify

from . import audit
from .msg import msg
from .models import USER_TYPES, FieldDef, Record
from .validation import clean_value

FORMAT = "kartei-import-mapping"
SIDES = ("person", "company")
CORE = {  # normalized header names -> core target per side
    "core:legacy_id": {"uid", "id", "legacyid", "altid"},
    "core:first_name": {"firstname", "vorname", "givenname"},
    "core:last_name": {"lastname", "nachname", "surname", "familyname"},
    "company": {"company", "companyname", "firma", "firmenname", "unternehmen", "organization", "organisation"},
}
CORE_TARGETS = {"person": {"core:legacy_id", "core:first_name", "core:last_name", "core:company"},
                "company": {"core:legacy_id", "core:name"}}
KIND_HEADERS = {"kind", "type", "typ", "art", "kontaktart"}
KIND_VALUES = {"person": "person", "kontakt": "person", "contact": "person", "p": "person",
               "company": "company", "firma": "company", "unternehmen": "company", "organization": "company",
               "organisation": "company", "account": "company", "c": "company", "f": "company"}


class ImportError_(Exception):
    pass


def norm(s):
    """Case/accent/punctuation-insensitive form for matching headers and kind values."""
    s = unicodedata.normalize("NFKD", str(s).casefold()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s)


def _decode(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_(msg("import_encoding"))


def read_csv(raw):
    text = _decode(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = list(reader)
    if not rows:
        raise ImportError_(msg("import_empty"))
    return list(reader.fieldnames), rows


def suggest(headers, fields):
    """Suggested mapping: core targets first, then the first live field matching key, label or import alias."""
    names = [(f, {norm(x) for x in (f.key, f.label_de, f.label_en, *f.import_aliases)}) for f in fields if not f.archived]
    columns = {}
    for h in headers:
        n = norm(h)
        pair = {}
        for side in SIDES:
            core = next((t for t, aliases in CORE.items() if n in aliases), "")
            if core == "company":
                core = "core:company" if side == "person" else "core:name"
            if core not in CORE_TARGETS[side]:
                core = ""
            pair[side] = core or next((f"field:{f.key}" for f, ns in names if f.applies(side) and n in ns), "")
        columns[h] = pair
    kind_col = next((h for h in headers if norm(h) in KIND_HEADERS), "")
    return {"format": FORMAT, "version": 1, "columns": columns,
            "kind": {"column": kind_col, "company_prefix": "", "person_prefix": ""}}


def preview(raw, fields):
    headers, rows = read_csv(raw)
    return {"headers": headers, "samples": [[r.get(h) or "" for h in headers] for r in rows[:5]], "rows": len(rows),
            "mapping": suggest(headers, fields)}


def _resolve(headers, fields, mapping):
    """Suggestion overlaid with the admin's mapping; raises on targets that don't exist."""
    m = suggest(headers, fields.values())
    mapping = mapping if isinstance(mapping, dict) else {}
    given = mapping.get("columns") if isinstance(mapping.get("columns"), dict) else {}
    for h, pair in given.items():
        if h in m["columns"] and isinstance(pair, dict):
            m["columns"][h].update({s: str(pair.get(s) or "") for s in SIDES if s in pair})
    if isinstance(mapping.get("kind"), dict):
        m["kind"].update({k: str(v or "") for k, v in mapping["kind"].items() if k in m["kind"]})
    for h, pair in m["columns"].items():
        for side in SIDES:
            t = pair[side]
            ok = t in ("", "new") or t in CORE_TARGETS[side] or (
                t.startswith("field:") and t[6:] in fields and fields[t[6:]].applies(side))
            if not ok:
                raise ImportError_(msg("import_bad_target", column=h, target=t))
    if m["kind"]["column"] and m["kind"]["column"] not in headers:
        raise ImportError_(msg("import_bad_target", column=m["kind"]["column"], target="kind"))
    return m


def _new_fields(m, fields, user):
    """'new' targets: one text field per header, applying to the sides that chose it."""
    for h, pair in m["columns"].items():
        sides = [s for s in SIDES if pair[s] == "new"]
        if not sides:
            continue
        base = slugify(h).replace("-", "_")[:50] or "field"
        key, i = base, 2
        while key in fields:
            key, i = f"{base}_{i}", i + 1
        order = (FieldDef.objects.order_by("-order").values_list("order", flat=True).first() or 0) + 10
        f = FieldDef.objects.create(key=key, label_de=h[:100] or key, label_en=h[:100] or key, order=order,
                                    applies_to=sides[0] if len(sides) == 1 else "both", import_aliases=[h])
        fields[key] = f
        audit.log(user, "create", "field", f.id, f.label_de, {"key": [None, key], "label_de": [None, f.label_de]})
        for s in sides:
            pair[s] = f"field:{key}"


def _split_multi(v):
    return [p.strip() for p in re.split(r"\s*\|##\|\s*|\s*[,;]\s*", v) if p.strip()]


def user_lookup():
    """{lowercased username / full name / unique initials: username} over active users."""
    out, initials = {}, {}
    for u in User.objects.filter(is_active=True):
        out[u.username.lower()] = u.username
        if full := f"{u.first_name} {u.last_name}".strip():
            out[full.lower()] = u.username
        if u.first_name and u.last_name:
            initials.setdefault((u.first_name[0] + u.last_name[0]).lower(), []).append(u.username)
    for k, names in initials.items():
        if len(names) == 1:  # ambiguous initials are not guessed
            out.setdefault(k, names[0])
    return out


def import_csv(raw, mapping=None, user=None, dry_run=True):
    headers, rows = read_csv(raw)
    stats = {"dry_run": dry_run, "rows": len(rows), "persons_created": 0, "persons_updated": 0,
             "companies_created": 0, "companies_updated": 0, "merged_skipped": 0, "warnings": []}
    warn = lambda msg: len(stats["warnings"]) < 200 and stats["warnings"].append(msg)

    with transaction.atomic():
        fields = {f.key: f for f in FieldDef.objects.all()}
        m = _resolve(headers, fields, mapping)
        _new_fields(m, fields, user)
        cols, rule = m["columns"], m["kind"]
        cols_of = lambda side, target: [h for h in headers if cols[h][side] == target]
        id_cols = list(dict.fromkeys(cols_of("person", "core:legacy_id") + cols_of("company", "core:legacy_id")))
        last_cols = cols_of("person", "core:last_name")
        company_cols = cols_of("person", "core:company") + cols_of("company", "core:name")
        first = lambda row, hs: next((v.strip() for h in hs if (v := row.get(h)) and v.strip()), "")

        def kind_of(line, row):
            if rule["column"] and (v := (row.get(rule["column"]) or "").strip()):
                if k := KIND_VALUES.get(norm(v)):
                    return k
                warn(msg("import_kind_unknown", line=line, id=first(row, id_cols), value=v))
            legacy = first(row, id_cols)
            for k in SIDES:
                if (prefix := rule[f"{k}_prefix"]) and legacy.startswith(prefix):
                    return k
            # ponytail: a last name makes a person; without one, a company name makes a company
            return "company" if not first(row, last_cols) and first(row, company_cols) else "person"

        companies = {r.name.lower(): r for r in Record.objects.filter(kind="company", deleted_at__isnull=True)}
        # merged-away contacts: their rows are skipped, their company names lead to the company they were merged into
        merged = {lid: r for r in Record.objects.filter(deleted_at__isnull=True).exclude(merged_legacy_ids=[])
                  for lid in r.merged_legacy_ids}
        for r in Record.objects.filter(kind="company", merged_into__isnull=False, merged_into__deleted_at__isnull=True).select_related("merged_into"):
            companies.setdefault(r.name.lower(), r.merged_into)
        users = user_lookup()

        # companies first so persons can link to them
        kinds = [(line, row, kind_of(line, row)) for line, row in enumerate(rows, 2)]
        for line, row, kind in sorted(kinds, key=lambda x: x[2] != "company"):
            legacy = first(row, cols_of(kind, "core:legacy_id"))
            if legacy in merged:
                stats["merged_skipped"] += 1
                warn(msg("import_merged", line=line, id=legacy, name=merged[legacy].display_name))
                continue
            r = Record.objects.filter(legacy_id=legacy, kind=kind).first() if legacy else None
            created = r is None
            if created:
                r = Record(kind=kind, legacy_id=legacy, updated_by=user)
            before = {"first_name": r.first_name, "last_name": r.last_name, "name": r.name, **r.data}
            company_name = ""
            for header, value in row.items():
                if header not in cols or value is None:
                    continue
                value = value.strip()
                k, _, arg = cols[header][kind].partition(":")
                if k == "core" and arg == "company":
                    company_name = company_name or value
                elif k == "core" and arg != "legacy_id":
                    setattr(r, arg, " ".join(value.split()))
                elif k == "field" and value:
                    f = fields[arg]
                    if f.type in USER_TYPES:
                        names = _split_multi(value)
                        if missing := [n for n in names if n.lower() not in users]:
                            warn(msg("import_unknown_user", line=line, id=legacy, column=header, users=", ".join(missing)))
                        found = list(dict.fromkeys(users[n.lower()] for n in names if n.lower() in users))
                        if not found:
                            continue
                        value = found if f.type == "users" else found[0]
                    elif f.type == "multiselect":
                        value = _split_multi(value)
                        known = {o["value"] for o in f.options}
                        new = [v for v in value if v not in known]
                        if new:
                            f.options += [{"value": v, "de": v, "en": v} for v in new]
                            f.save(update_fields=["options"])
                    elif f.type == "select" and value not in {o["value"] for o in f.options}:
                        f.options += [{"value": value, "de": value, "en": value}]
                        f.save(update_fields=["options"])
                    try:
                        r.data[arg] = clean_value(f, value)
                    except ValueError as e:
                        warn(msg("import_invalid", line=line, id=legacy, column=header, value=value, error=str(e)))
            if kind == "company" and not r.name:
                warn(msg("import_company_no_name", line=line, id=legacy))
                continue
            if kind == "person":
                if not (r.first_name or r.last_name):
                    warn(msg("import_person_no_name", line=line, id=legacy))
                    continue
                if company_name:
                    c = companies.get(company_name.lower())
                    if c is None:
                        c = Record.objects.create(kind="company", name=company_name, updated_by=user)
                        companies[company_name.lower()] = c
                        stats["companies_created"] += 1
                        audit.log(user, "import", "record", c.uid, c.name, {"name": [None, c.name]})
                    r.company = c
            after = {"first_name": r.first_name, "last_name": r.last_name, "name": r.name, **r.data}
            change = audit.diff(before, after)
            if created or change:
                if not created:
                    r.version += 1
                r.save()
                if kind == "company":
                    companies[r.name.lower()] = r
                stats[f"{'persons' if kind == 'person' else 'companies'}_{'created' if created else 'updated'}"] += 1
                audit.log(user, "import", "record", r.uid, r.display_name, change)
        if dry_run:
            transaction.set_rollback(True)
    return stats
