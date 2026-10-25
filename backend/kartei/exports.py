"""Admin-defined CSV/XLSX exports with a guard against empty/shrunken output (an empty export once wiped contacts downstream)."""
import csv
import hashlib
import io
import json
import logging
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings as dj_settings
from django.utils import timezone

from .msg import msg
from .models import FieldDef, Record, ref_names

log = logging.getLogger(__name__)
EXPORT_ROOT = os.environ.get("EXPORT_ROOT", str(Path(dj_settings.BASE_DIR).parent / "export_out"))
CORE = ["first_name", "last_name", "name"]
CALC = ["uid", "legacy_id", "legacy_or_uid", "display_name", "company_name", "kind", "created_at", "updated_at"]
QUOTING = {"minimal": csv.QUOTE_MINIMAL, "all": csv.QUOTE_ALL, "nonnumeric": csv.QUOTE_NONNUMERIC}
ENCODINGS = ["utf-8", "utf-8-sig", "cp1252"]


class GuardError(Exception):
    pass


def available_sources():
    return {"core": CORE, "calc": CALC,
            "fields": [{"key": f.key, "label": {"de": f.label_de, "en": f.label_en}, "applies_to": f.applies_to,
                        "type": f.type} for f in FieldDef.objects.filter(archived=False)]}


def target_path(p):
    return p.path.replace("{date}", date.today().isoformat())


def _inside_root(path):
    root = os.path.realpath(EXPORT_ROOT)
    return os.path.realpath(path).startswith(root + os.sep)


def validate_profile(p, check_path=True):
    errors = {}
    if check_path and not (p.name or "").strip():
        errors["name"] = "required"
    if p.format not in ("csv", "xlsx"):
        errors["format"] = "invalid"
    if p.kinds not in ("person", "company", "both") or p.schedule not in ("auto", "manual"):
        errors["kinds"] = "invalid"
    if check_path:
        if not p.path or not os.path.isabs(p.path):
            errors["path"] = "must_be_absolute"
        elif not _inside_root(target_path(p)):
            errors["path"] = "outside_export_root"
        elif p.format == "csv" and not p.path.lower().endswith(".csv") or \
                p.format == "xlsx" and not p.path.lower().endswith(".xlsx"):
            errors["path"] = "wrong_extension"
    keys = set(FieldDef.objects.values_list("key", flat=True))
    if not isinstance(p.columns, list) or not p.columns:
        errors["columns"] = "required"
    else:
        for c in p.columns:
            if not isinstance(c, dict) or not str(c.get("header", "")).strip():
                errors["columns"] = "invalid"
                break
            for side in ("person", "company"):
                src = c.get(side) or ""
                kind, _, arg = src.partition(":")
                if src and not ((kind == "core" and arg in CORE) or (kind == "calc" and arg in CALC)
                                or (kind == "field" and arg in keys) or kind == "const"):
                    errors["columns"] = f"invalid_source:{src}"
    o = p.effective_options()
    if p.format == "csv":
        if len(o["delimiter"]) != 1 or len(o["quotechar"]) != 1 or o["quoting"] not in QUOTING \
                or o["encoding"] not in ENCODINGS or o["line_ending"] not in ("crlf", "lf") \
                or o["newlines"] not in ("keep", "space"):
            errors["options"] = "invalid"
    if not isinstance(p.filter_values, list):
        errors["filter_values"] = "invalid"
    if not isinstance(p.max_shrink_percent, int) or not 0 <= p.max_shrink_percent <= 100:
        errors["max_shrink_percent"] = "invalid"
    return errors


def included(p, r):
    """Does export profile p contain record r (kind and filter field)?"""
    if p.kinds != "both" and r.kind != p.kinds:
        return False
    if p.filter_field_id and p.filter_values:
        v = r.data.get(p.filter_field.key)
        vals = v if isinstance(v, list) else [v]
        return bool(set(map(str, vals)) & set(map(str, p.filter_values)))
    return True


def _records(p):
    qs = Record.objects.filter(deleted_at__isnull=True).select_related("company").defer("image")
    if p.kinds != "both":
        qs = qs.filter(kind=p.kinds)
    out = [r for r in qs if included(p, r)]
    out.sort(key=lambda r: (r.kind != "company", r.display_name.lower()))
    return out


def resolve(r, src, fields):
    """Raw typed value of a column source for a record."""
    kind, _, arg = (src or "").partition(":")
    if kind == "const":
        return arg
    if kind == "core":
        return getattr(r, arg, "")
    if kind == "field":
        f = fields.get(arg)
        return r.data.get(arg) if f and f.applies(r.kind) else None
    if kind == "calc":
        return {
            "uid": lambda: str(r.uid), "legacy_id": lambda: r.legacy_id,
            "legacy_or_uid": lambda: r.legacy_id or str(r.uid), "display_name": lambda: r.display_name,
            "company_name": lambda: r.company.name if r.company and not r.company.deleted_at else "",
            "kind": lambda: r.kind, "created_at": lambda: timezone.localtime(r.created_at).replace(tzinfo=None),
            "updated_at": lambda: timezone.localtime(r.updated_at).replace(tzinfo=None),
        }[arg]()
    return None


def _typed(value, src, fields, names):
    """Normalize JSON storage into python types (Decimal, date, user names) for formatting."""
    kind, _, arg = (src or "").partition(":")
    f = fields.get(arg) if kind == "field" else None
    if value in (None, "") or f is None:
        return value
    if f.type == "decimal":
        return Decimal(value)
    if f.type == "date":
        return date.fromisoformat(value)
    if f.type in ("user", "contact"):
        return names.get(value, value)
    if f.type == "users":
        return [names.get(v, v) for v in value]
    return value


def build_rows(p):
    """-> (header, rows) with typed cell values."""
    fields = {f.key: f for f in FieldDef.objects.all()}
    names = ref_names()
    header = [c["header"] for c in p.columns]
    rows = []
    for r in _records(p):
        row = []
        for c in p.columns:
            src = c.get(r.kind) or ""
            row.append(_typed(resolve(r, src, fields), src, fields, names))
        rows.append(row)
    return header, rows


def _jsonable(v):
    if isinstance(v, (date, Decimal)):
        return str(v)
    return v


def _csv_text(v, o):
    if v is None:
        return ""
    if isinstance(v, bool):
        return o.get("bool_true", "Ja") if v else o.get("bool_false", "Nein")
    if isinstance(v, list):
        v = o["multi_sep"].join(map(str, v))
    elif hasattr(v, "strftime"):
        v = v.strftime(o["date_format"])
    elif isinstance(v, Decimal):
        v = str(v).replace(".", o["decimal_sep"])
    v = str(v)
    if o["newlines"] == "space":
        v = " ".join(v.split())
    return v


def render_csv(header, rows, o):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=o["delimiter"], quotechar=o["quotechar"], quoting=QUOTING[o["quoting"]],
                   lineterminator="\r\n" if o["line_ending"] == "crlf" else "\n")
    if o["header"]:
        w.writerow(header)
    for row in rows:
        w.writerow([_csv_text(v, o) for v in row])
    return buf.getvalue().encode(o["encoding"], errors="replace")


def render_xlsx(header, rows, o):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = (o["sheet_name"] or "Export")[:31]
    if o["header"]:
        ws.append(header)
        if o["bold_header"]:
            for cell in ws[1]:
                cell.font = Font(bold=True)
    for row in rows:
        ws.append([", ".join(map(str, v)) if isinstance(v, list) else (float(v) if isinstance(v, Decimal) else v)
                   for v in row])
    first = 2 if o["header"] else 1
    for row in ws.iter_rows(min_row=first):
        for cell in row:
            if isinstance(cell.value, date):
                cell.number_format = o["date_format"]
            elif isinstance(cell.value, float):
                cell.number_format = o["number_format"]
    if o["header"] and o["autofilter"] and rows:
        ws.auto_filter.ref = ws.dimensions
    if o["header"] and o["freeze_header"]:
        ws.freeze_panes = "A2"
    if o["autowidth"]:
        for i, col in enumerate(ws.iter_cols(), 1):
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _existing_rows(path, p):
    """Best-effort row count of the file currently on disk (first run only)."""
    try:
        if p.format == "xlsx":
            from openpyxl import load_workbook
            ws = load_workbook(path, read_only=True).active
            n = ws.max_row or 0
        else:
            o = p.effective_options()
            with open(path, encoding=o["encoding"], errors="replace", newline="") as fh:
                n = sum(1 for _ in csv.reader(fh, delimiter=o["delimiter"], quotechar=o["quotechar"]))
        return max(n - (1 if p.effective_options()["header"] else 0), 0)
    except (OSError, ValueError, KeyError):
        return None


def guard(p, path, count, force=False):
    if force:
        return
    if count == 0:
        raise GuardError(msg("export_empty"))
    previous = p.last_rows if p.last_status == "ok" and p.last_rows else (
        _existing_rows(path, p) if os.path.exists(path) else None)
    if previous and count < previous * (100 - p.max_shrink_percent) / 100:
        raise GuardError(msg("export_dropped", before=previous, after=count, limit=p.max_shrink_percent))


def atomic_write(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)  # the path was checked to be below EXPORT_ROOT
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".kartei-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; downstream readers need access
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def run(p, force=False, user=None):
    """Write one profile. Never raises; result is stored on the profile."""
    path = target_path(p)
    p.last_run_at = timezone.now()
    try:
        if errors := validate_profile(p):
            raise GuardError(msg("export_invalid", fields=", ".join(errors)))
        header, rows = build_rows(p)
        o = p.effective_options()
        digest = hashlib.sha256(json.dumps([p.format, o, header, [[_jsonable(v) for v in r] for r in rows]],
                                           default=str).encode()).hexdigest()
        if digest == p.last_hash and os.path.exists(path) and not force:
            p.last_status, p.last_message = "skipped", msg("export_unchanged")
        else:
            guard(p, path, len(rows), force)
            data = render_csv(header, rows, o) if p.format == "csv" else render_xlsx(header, rows, o)
            atomic_write(path, data)
            p.last_status, p.last_message, p.last_rows, p.last_hash = "ok", msg("export_rows", n=len(rows)), len(rows), digest
    except (GuardError, OSError) as e:
        log.error("export %s failed: %s", p.name, e)
        p.last_status, p.last_message = "error", str(e)
    p.save(update_fields=["last_run_at", "last_status", "last_message", "last_rows", "last_hash"])
    return p.last_status
