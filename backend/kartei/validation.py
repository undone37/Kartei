"""Server-side validation for core fields and admin-defined fields. Errors are codes; the UI translates them."""
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, URLValidator

PHONE_RE = re.compile(r"^\+?[0-9 ()/\-]{3,40}$")
REGEX_TYPES = ("text", "longtext", "phone", "email", "url")
EMPTY = (None, "", [])
_email, _url = EmailValidator(), URLValidator(schemes=["http", "https"])


def _num(value, decimals=None):
    if isinstance(value, bool):
        raise ValueError
    s = str(value).strip().replace(" ", "")
    if "," in s:  # german input: 1.234,56
        s = s.replace(".", "").replace(",", ".")
    d = Decimal(s)
    if not d.is_finite():
        raise ValueError
    return d if decimals is None else d.quantize(Decimal(1).scaleb(-decimals))


def phone_cc():
    """The default country code phone numbers are normalized to, or '' when normalization is off."""
    from .models import Settings
    s = Settings.objects.filter(pk=1).values_list("phone_normalize", "phone_country_code").first()
    return "+49" if s is None else s[1] if s[0] else ""


def normalize_phone(v, cc):
    """National numbers to international form, keeping the user's grouping: '(0511) 1000-12' -> '+49 511 1000-12',
    '0049 511 1000' / '+49 (0)511 1000' -> '+49 511 1000'. Numbers without a leading 0 or + (extensions) stay as typed.
    ponytail: no numbering plan, so digits are never regrouped and the trunk prefix is assumed to be 0 (not Italy)."""
    if not cc:
        return v
    s = v.replace("(0)", " ")
    s = re.sub(r"\s*-\s*", "-", re.sub(r"[()/]", " ", s))
    s = " ".join(s.split())
    if s.startswith("00"):
        s = "+" + s[2:].lstrip(" -")
    elif s.startswith("0"):
        s = f"{cc} {s[1:].lstrip(' -')}"
    elif not s.startswith("+"):
        return v
    if s.startswith(cc) and s[len(cc):len(cc) + 1] not in ("", " "):  # +49511 / +49-511 -> +49 511
        s = f"{cc} {s[len(cc):].lstrip('-')}"
    if s.startswith(cc + " 0"):  # +49 0511 -> +49 511
        s = f"{cc} {s[len(cc) + 2:].lstrip(' -')}"
    return s


def clean_value(f, value, old=None, cc=None):
    """Return the normalized value or raise ValueError(code). Applies the field's admin-defined regex.
    `old` is the stored value: user fields may keep users that were deactivated since.
    `cc`: phone country code ('' = keep numbers as typed), read from the settings if None."""
    v = _clean(f, value, old, cc)
    # ponytail: admin-supplied pattern on <=20k chars; a pathological regex could be slow, admins are trusted
    if f.regex and f.type in REGEX_TYPES and not re.fullmatch(f.regex, v):
        raise ValueError("pattern_mismatch")
    return v


def _option(f, value):
    """An existing option value; on open fields also a new one (an existing option with the same text wins)."""
    if any(o["value"] == value for o in f.options):
        return value
    if not f.open_options or not isinstance(value, str):
        raise ValueError("invalid_option")
    v = " ".join(value.split())
    if not v or len(v) > 100:
        raise ValueError("invalid_option")
    for o in f.options:
        if v.lower() in (o["value"].lower(), (o.get("de") or "").lower(), (o.get("en") or "").lower()):
            return o["value"]
    return v


def _person(value):
    # ponytail: any live person; the UI offers the persons of the record's company, which can change later anyway
    from .models import Record
    try:
        return Record.objects.filter(uid=uuid.UUID(value), kind="person", deleted_at__isnull=True).exists()
    except ValueError:
        return False


def _active(username):
    return isinstance(username, str) and User.objects.filter(username=username, is_active=True).exists()


def _clean(f, value, old=None, cc=None):
    t = f.type
    if t == "user":
        if value != old and not _active(value):
            raise ValueError("invalid_user")
        return value
    if t == "contact":
        if not isinstance(value, str):
            raise ValueError("invalid_contact")
        if value == old or _person(value):
            return value
        if not f.open_options:
            raise ValueError("invalid_contact")
        v = " ".join(value.split())
        if not v or len(v) > 200:
            raise ValueError("invalid_contact")
        return v
    if t == "users":
        keep = old if isinstance(old, list) else []
        if not isinstance(value, list) or any(v not in keep and not _active(v) for v in value):
            raise ValueError("invalid_user")
        return list(dict.fromkeys(value))
    if t in ("text", "longtext"):
        if not isinstance(value, str):
            raise ValueError("invalid")
        v = value.strip() if t == "longtext" else " ".join(value.split())
        if len(v) > (20000 if t == "longtext" else 1000):
            raise ValueError("too_long")
        return v
    if t in ("integer", "decimal"):
        try:
            d = _num(value, f.decimals if t == "decimal" else None)
        except (InvalidOperation, ValueError):
            raise ValueError("invalid_number")
        if t == "integer" and d != d.to_integral_value():
            raise ValueError("invalid_integer")
        if f.min_value is not None and d < f.min_value:
            raise ValueError("too_small")
        if f.max_value is not None and d > f.max_value:
            raise ValueError("too_large")
        return int(d) if t == "integer" else str(d)  # ponytail: decimals as exact strings, UI formats via Intl
    if t == "select":
        return _option(f, value)
    if t == "multiselect":
        if not isinstance(value, list):
            raise ValueError("invalid_option")
        return list(dict.fromkeys(_option(f, v) for v in value))
    if t == "phone":
        v = " ".join(str(value).split())
        if not PHONE_RE.match(v):
            raise ValueError("invalid_phone")
        return normalize_phone(v, phone_cc() if cc is None else cc)
    if t == "email":
        v = str(value).strip()
        try:
            _email(v)
        except ValidationError:
            raise ValueError("invalid_email")
        return v
    if t == "url":
        v = str(value).strip()
        if "://" not in v:
            v = "https://" + v
        try:
            _url(v)
        except ValidationError:
            raise ValueError("invalid_url")
        return v
    if t == "date":
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise ValueError("invalid_date")
    if t == "checkbox":
        if not isinstance(value, bool):
            raise ValueError("invalid")
        return value
    raise ValueError("invalid")


def merge_data(kind, existing, changes, fields, rank):
    """Apply `changes` ({key: value}) onto `existing` data. Returns (data, errors)."""
    by_key = {f.key: f for f in fields if f.applies(kind) and not f.archived}
    data, errors = dict(existing), {}
    for key, value in changes.items():
        f = by_key.get(key)
        if f is None or not f.visible(rank):
            errors[key] = "unknown_field"
            continue
        if not f.editable(rank):
            if data.get(key) != value and not (value in EMPTY and key not in data):
                errors[key] = "forbidden"
            continue
        if value in EMPTY:
            data.pop(key, None)
            continue
        try:
            data[key] = clean_value(f, value, data.get(key))
        except ValueError as e:
            errors[key] = str(e)
    for f in by_key.values():
        if f.required and f.editable(rank) and data.get(f.key) in EMPTY and f.key not in errors:
            errors[f.key] = "required"
    return data, errors


def clean_core(kind, payload):
    """Core columns. Returns (values, errors)."""
    out, errors = {}, {}
    names = ["first_name", "last_name"] if kind == "person" else ["name"]
    for n in names:
        if n in payload:
            v = " ".join(str(payload[n] or "").split())
            if len(v) > (200 if n == "name" else 100):
                errors[n] = "too_long"
            out[n] = v
    return out, errors
