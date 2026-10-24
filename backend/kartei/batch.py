"""Company changes carried over to its persons (preview, then apply what the user ticked).

Rules for a changed company field (old -> new):
- copied fields (person field with copy_from = that field): persons still holding the old value get the new one
- phone fields: person phone numbers starting with the old number get the new prefix, keeping their extension
"""
import re

from . import audit
from .msg import msg
from .models import FieldDef, Record, Settings
from .validation import clean_value, normalize_phone

MIN_PREFIX = 6  # digits; shorter numbers would match by accident


def digits(v):
    return re.sub(r"\D", "", str(v or ""))


def national(v, cc="+49"):
    """Digits in national form for the default country code plus how many raw digits that dropped:
    '+49 511' -> ('0511', 1)."""
    # ponytail: only the default country code; other country codes compare as written
    d, c = digits(v), digits(cc)
    if c and d.startswith("00" + c):
        return "0" + d[2 + len(c):], 1 + len(c)
    if c and str(v or "").lstrip().startswith("+") and d.startswith(c):
        return "0" + d[len(c):], len(c) - 1
    return d, 0


def swap_prefix(value, old, new, cc="+49"):
    """'0511 1000-12' with old '0511 1000', new '0511 4711' -> '0511 4711-12'; None if it doesn't start with old.
    '+49 511 1000 13' matches '0511 1000' too."""
    want = national(old, cc)[0]
    have, shift = national(value, cc)
    if len(want) < MIN_PREFIX or not have.startswith(want):
        return None
    seen, need = 0, len(want) + shift
    for i, ch in enumerate(value):  # cut the original string right after the prefix digits
        seen += ch.isdigit()
        if seen == need:
            return f"{new}{value[i + 1:]}"
    return None


def plan(company, changes):
    """changes: {company field key: [old, new]} -> [{uid, name, key, old, new}] proposed person updates."""
    fields = [f for f in FieldDef.objects.filter(archived=False)]
    by_key = {f.key: f for f in fields}
    person_fields = [f for f in fields if f.applies("person")]
    persons = list(company.persons.filter(deleted_at__isnull=True).order_by("last_name", "first_name"))
    s = Settings.get()
    cc, norm = s.phone_country_code, s.phone_country_code if s.phone_normalize else ""
    out = {}
    for key, pair in changes.items():
        src = by_key.get(key)
        if not src or not src.applies("company") or not isinstance(pair, list) or len(pair) != 2:
            continue
        old, new = pair
        if old in (None, "", []) or old == new:
            continue
        copies = [f for f in person_fields if f.copy_from_id == src.id]
        phones = [f for f in person_fields if f.type == "phone"] if src.type == "phone" and new else []
        for p in persons:
            for f in copies:
                if p.data.get(f.key) == old:
                    out[(p.uid, f.key)] = new
            for f in phones:
                if (p.uid, f.key) not in out and (swapped := swap_prefix(p.data.get(f.key), old, new, cc)):
                    out[(p.uid, f.key)] = normalize_phone(swapped, norm)  # as saving will store it
    names = {p.uid: p for p in persons}
    return [{"uid": str(uid), "name": names[uid].display_name, "key": key, "old": names[uid].data.get(key), "new": new}
            for (uid, key), new in out.items() if names[uid].data.get(key) != new]


def apply(company, changes, selected, user, rank):
    """Apply the planned items whose (uid, key) is in `selected`. Returns (updated persons, errors)."""
    wanted = {(s.get("uid"), s.get("key")) for s in selected if isinstance(s, dict)}
    items = [i for i in plan(company, changes) if (i["uid"], i["key"]) in wanted]
    fields = {f.key: f for f in FieldDef.objects.all()}
    per_person, errors = {}, []
    for i in items:
        per_person.setdefault(i["uid"], []).append(i)
    updated = 0
    for uid, its in per_person.items():
        r = Record.objects.select_for_update().get(uid=uid)
        change = {}
        for i in its:
            f = fields[i["key"]]
            if not f.editable(rank):
                errors.append(msg("batch_failed", name=r.display_name, field_de=f.label_de, field_en=f.label_en,
                                  error="forbidden"))
                continue
            try:
                value = None if i["new"] in (None, "", []) else clean_value(f, i["new"], r.data.get(i["key"]))
            except ValueError as e:
                errors.append(msg("batch_failed", name=r.display_name, field_de=f.label_de, field_en=f.label_en,
                                  error=str(e)))
                continue
            change[i["key"]] = [r.data.get(i["key"]), value]
            if value is None:
                r.data.pop(i["key"], None)
            else:
                r.data[i["key"]] = value
        if change:
            r.version += 1
            r.updated_by = user
            r.save()
            audit.log(user, "update", "record", r.uid, r.display_name, change | {"batch_from": [None, company.name]})
            updated += 1
    return updated, errors
