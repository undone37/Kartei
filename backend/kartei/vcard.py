"""vCard 3.0 rendering in two flavours (iOS / Android), matching the reference cards in tests.py.

Admin-defined fields pick a target from TARGETS; the renderer turns collected
values into flavour-specific lines. Pure functions, no DB access.
"""
import base64
from collections import defaultdict

_ADR_PARTS = ["pobox", "extra", "street", "city", "state", "zip", "country"]  # vCard ADR order

TARGETS = [
    "n_prefix", "n_middle", "n_suffix", "nickname",
    "phonetic_first", "phonetic_middle", "phonetic_last",
    "title", "department", "bday", "url",
    "email_work", "email_home", "email_custom",
    "tel_work", "tel_cell", "tel_home", "tel_fax_work", "tel_fax_home", "tel_assistant",
    "tel_custom", "tel_fax_custom",
    *[f"adr_work_{p}" for p in _ADR_PARTS], *[f"adr_home_{p}" for p in _ADR_PARTS],
    "related_assistant", "related_manager", "related_custom",
    "note", "note_labeled", "categories",
]

IOS_AGENTS = ("iOS/", "macOS/", "Mac OS X/", "dataaccessd", "AddressBook", "iPhone", "CFNetwork")


def flavour_for(user_agent):
    return "ios" if any(a in (user_agent or "") for a in IOS_AGENTS) else "android"


def esc(value):
    return (str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))


def fold(line):
    """Fold at 75 octets without splitting UTF-8 sequences (RFC 6350 3.2)."""
    out, cur, size, limit = [], [], 0, 75
    for ch in line:
        n = len(ch.encode())
        if size + n > limit:
            out.append("".join(cur))
            cur, size, limit = [" "], 1, 75
        cur.append(ch)
        size += n
    out.append("".join(cur))
    return "\r\n".join(out)


def _text(value):
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    return str(value)


def collect(record_data, fields, names=None):
    """-> {target: [(text, label)]} for every field with a vCard target and a value.
    names: {username: display name} for user fields."""
    got = defaultdict(list)
    for f in fields:
        v = record_data.get(f.key)
        if not f.vcard or v in (None, "", []):
            continue
        if f.type in ("user", "users", "contact") and names is not None:
            v = [names.get(x, x) for x in v] if isinstance(v, list) else names.get(v, v)
        got[f.vcard].append((v if f.vcard == "categories" else _text(v), f.vcard_label or f.label_de))
    return got


def render(record, fields, flavour, base_url="", names=None):
    """record: kartei.Record (or duck-type); fields: FieldDefs visible to the CardDAV user."""
    ios = flavour == "ios"
    g = collect(record.data or {}, fields, names)
    one = lambda t: " ".join(v for v, _ in g.get(t, []))
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"UID:urn:uuid:{record.uid}"]
    item = 0

    def labeled(prop, value, label):
        nonlocal item
        item += 1
        lines.append(f"item{item}.{prop}:{value}")
        lines.append(f"item{item}.X-ABLabel:{label}")

    company = record.kind == "company"
    if company:
        lines += [f"N:{'' if ios else esc(record.name)};;;;", f"FN:{esc(record.name)}", f"ORG:{esc(record.name)}"]
    else:
        prefix, middle, suffix = one("n_prefix"), one("n_middle"), one("n_suffix")
        lines.append("N:" + ";".join(esc(p) for p in [record.last_name, record.first_name, middle, prefix, suffix]))
        fn = " ".join(p for p in [prefix, record.first_name, record.last_name] if p)
        lines.append("FN:" + esc(f"{fn}, {suffix}" if suffix else fn))
    if nick := one("nickname"):
        lines.append(f"NICKNAME:{esc(nick)}")
    for part, prop in [("first", "FIRST"), ("middle", "MIDDLE"), ("last", "LAST")]:
        if v := one(f"phonetic_{part}"):
            lines.append(f"X-PHONETIC-{prop}-NAME:{esc(v)}")
            if ios and part != "middle":
                lines.append(f"X-PRONUNCIATION-{prop}-NAME:{esc(v)}")
    if v := one("title"):
        lines.append(f"TITLE:{esc(v)}")
    if record.image:
        prop = "LOGO" if company else "PHOTO"
        typ = "PNG" if record.image_type == "png" else "JPEG"
        lines.append(f"{prop};ENCODING=BASE64;TYPE={typ}:{base64.b64encode(bytes(record.image)).decode()}")

    department = one("department")
    if not company:
        org = record.company.name if getattr(record, "company", None) and not record.company.deleted_at else ""
        if ios and org:
            lines.append(f"ORG:{esc(org)}" + (f";{esc(department)}" if department else ""))
        elif org:
            lines.append(f"ORG:{esc(org)}")
        if department and not ios:
            lines.append(f"ROLE:{esc(department)}")

    # --- email: pref goes to the first work address, else the first custom one
    pref_email = "email_work" if g.get("email_work") else "email_custom"
    for target, typ in [("email_work", "WORK"), ("email_home", "HOME"), ("email_custom", None)]:
        for i, (v, label) in enumerate(g.get(target, [])):
            t = typ or esc(label)
            pref = ios and target == pref_email and i == 0
            lines.append(f"EMAIL;type={t}{';type=pref' if pref else ''}:{v}" if ios else f"EMAIL;{t}:{v}")

    # --- phones
    pref_tel = "tel_work" if g.get("tel_work") else "tel_custom"
    for target, android, ios_types in [
        ("tel_cell", "CELL", "CELL;type=VOICE"), ("tel_home", "HOME", "HOME;type=VOICE"),
        ("tel_work", "WORK", "WORK;type=VOICE"), ("tel_custom", None, None),
        ("tel_fax_work", "WORK;FAX", "WORK;type=FAX"), ("tel_fax_home", "HOME;FAX", "HOME;type=FAX"),
        ("tel_fax_custom", "FAX", "FAX"),
    ]:
        for i, (v, label) in enumerate(g.get(target, [])):
            if ios:
                t = ios_types or f"{esc(label)};type=VOICE"
                if target == "tel_fax_custom":
                    t = f"{esc(label)};type=FAX"
                pref = ";type=pref" if target == pref_tel and i == 0 else ""
                lines.append(f"TEL;type={t}{pref}:{v}")
            else:
                t = android or esc(label)
                if target == "tel_fax_custom":
                    t = f"{esc(label)};FAX"
                lines.append(f"TEL;{t}:{v}")
    for v, _ in g.get("tel_assistant", []):
        if ios:
            labeled("TEL", v, "_$!<AssistantPhone>!$_")
        else:
            lines.append(f"TEL;X-Assistenz:{v}")

    for v, _ in g.get("url", []):
        if ios:
            labeled("URL;type=pref", v, "_$!<HomePage>!$_")
        else:
            lines.append(f"URL:{v}")
    if v := one("bday"):
        lines.append(f"BDAY:{v}")
    if base_url:
        lines.append(f"SOURCE:{base_url.rstrip('/')}/{record.kind}/{record.uid}.vcf")

    for where in ("work", "home"):
        parts = [one(f"adr_{where}_{p}") for p in _ADR_PARTS]
        if any(parts):
            lines.append(f"ADR;{where.upper()}:" + ";".join(esc(p) for p in parts))

    rel = [(v, "_$!<Assistant>!$_", 1, "") for v, _ in g.get("related_assistant", [])]
    rel += [(v, "_$!<Manager>!$_", 7, "") for v, _ in g.get("related_manager", [])]
    rel += [(v, esc(label), 0, label) for v, label in g.get("related_custom", [])]
    for name, ios_label, android_type, custom in rel:
        if ios:
            labeled("X-ABRELATEDNAMES;type=pref", esc(name), ios_label)
        else:
            fields15 = [name, str(android_type), custom] + [""] * 12
            lines.append("X-ANDROID-CUSTOM:vnd.android.cursor.item/relation;" + ";".join(esc(f) for f in fields15))

    if cats := [c for v, _ in g.get("categories", []) for c in (v if isinstance(v, list) else [v])]:
        lines.append("CATEGORIES:" + ",".join(esc(c) for c in cats))

    note = [v for v, _ in g.get("note", [])]
    if department and not ios and not company:
        note.append(f"Abteilung: {department}")
    extra = [f"{label}: {v}" for v, label in g.get("note_labeled", [])]
    if extra:
        note = note + [""] + extra if note else extra
    if note:
        lines.append("NOTE:" + esc("\n".join(note)))

    lines.append("END:VCARD")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"
