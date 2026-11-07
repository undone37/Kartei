"""Saved filters evaluated on the server: which contacts a list state shows, exactly like the list in the browser
(frontend/src/lib/search.ts, advanced.ts, listfilter.ts). Used for Outlook folders and CardDAV address books made
from saved filters. Both sides run the same cases (frontend/tests/filter-cases.json), so they can't drift apart.

Records are plain dicts shaped like the browser's (`row()`): uid, kind, first_name, last_name, name, legacy_id,
company (uid), data (only the fields the viewer may see), created_at/updated_at/reviewed_at (ISO), updated_by."""
import re
import unicodedata
from datetime import date, datetime, timedelta

from django.utils import timezone

CHOICE = ("select", "multiselect", "user", "users")
EXPAND = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
OPS = {
    "text": ("contains", "not_contains", "eq", "ne", "starts", "empty", "not_empty"),
    "number": ("eq", "ne", "lt", "le", "gt", "ge", "between", "empty", "not_empty"),
    "date": ("on", "not_on", "before", "on_before", "after", "on_after", "between", "last", "older", "empty", "not_empty"),
    "choice": ("in", "not_in", "empty", "not_empty"),
    "multi": ("any", "all", "none", "empty", "not_empty"),
    "bool": ("yes", "no"),
}
NAN = float("nan")


# ---------------------------------------------------------------- search (search.ts)

def fold(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub("[̀-ͯ]", "", s).replace("ß", "ss")


def expand(s):
    return re.sub("[äöüß]", lambda m: EXPAND[m.group()], s.lower())


def digits(s):
    d = re.sub(r"[^0-9+]", "", s)
    if d.startswith("+49"):
        d = "0" + d[3:]
    elif d.startswith("0049"):
        d = "0" + d[4:]
    return d.replace("+", "00")


def display_name(r):
    return r["name"] if r["kind"] == "company" else f"{r['first_name']} {r['last_name']}".strip()


def _js_str(v):
    """String(v) as JavaScript writes it, for the values that occur in contact data."""
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, list):
        return ",".join(_js_str(x) for x in v)
    return "" if v is None else str(v)


def index(r, fields, by_uid):
    """(hay, tel) of one record: what the search matches against."""
    parts = [r["first_name"], r["last_name"], r["name"], r["legacy_id"]]
    if r["company"]:
        parts.append(by_uid[r["company"]]["name"] if r["company"] in by_uid else "")
    tel = []
    for f in fields:
        if not f["searchable"] or f["archived"]:
            continue
        v = r["data"].get(f["key"])
        if v is None or v == "":
            continue
        if f["type"] == "phone":
            tel.append(digits(_js_str(v)))
        if f["type"] == "contact":
            linked = by_uid.get(v) if isinstance(v, str) else None
            parts.append(display_name(linked) if linked else _js_str(v))
            continue
        if f["type"] in CHOICE:
            for x in v if isinstance(v, list) else [v]:
                o = next((o for o in f.get("options") or [] if o.get("value") == x), None)
                parts += [_js_str(x), (o or {}).get("de", ""), (o or {}).get("en", "")]
        else:
            parts.append(_js_str(v))
    text = " ".join(p or "" for p in parts)
    return fold(text) + " " + expand(text), " ".join(tel)


def matcher(query):
    tokens = query.strip().split()
    prepared = [(fold(t), digits(t) if re.fullmatch(r"[0-9+()/-]{3,}", t) else "") for t in tokens]
    return lambda hay, tel: all(text in hay or (d and d in tel) for text, d in prepared)


# ---------------------------------------------------------------- advanced filter (advanced.ts)

def family(t):
    if t in ("integer", "decimal"):
        return "number"
    if t == "date":
        return "date"
    if t in ("select", "user", "contact"):
        return "choice"
    if t in ("multiselect", "users"):
        return "multi"
    return "bool" if t == "checkbox" else "text"


def _day(iso):
    """Local calendar day of a timestamp, like the browser shows it."""
    if not iso:
        return ""
    return timezone.localtime(datetime.fromisoformat(iso.replace("Z", "+00:00"))).date().isoformat()


CORE = {
    "@kind": ("select", lambda r: r["kind"]),
    "@first_name": ("text", lambda r: r["first_name"]),
    "@last_name": ("text", lambda r: r["last_name"]),
    "@name": ("text", lambda r: r["name"]),
    "@company": ("contact", lambda r: r["company"]),
    "@legacy_id": ("text", lambda r: r["legacy_id"]),
    "@created_at": ("date", lambda r: _day(r["created_at"])),
    "@updated_at": ("date", lambda r: _day(r["updated_at"])),
    "@reviewed_at": ("date", lambda r: _day(r["reviewed_at"])),
    "@updated_by": ("user", lambda r: r["updated_by"]),
}


def defs(fields):
    d = dict(CORE)
    for f in fields:
        if not f["archived"]:
            d[f["key"]] = (f["type"], lambda r, k=f["key"]: r["data"].get(k))
    return d


def _blank(v):
    return v is None or (len(v) == 0 if isinstance(v, list) else _js_str(v).strip() == "")


def _num(v):
    if _blank(v):
        return NAN
    try:
        return float(_js_str(v).strip().replace(",", ".", 1))
    except ValueError:
        return NAN


def _is_day(v):
    return isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) is not None


def leaf(c, d, today):
    if not d or not isinstance(c, dict) or not isinstance(c.get("op"), str):
        return None
    typ, get = d
    fam = family(typ)
    op, value = c["op"], c.get("value")
    if op not in OPS[fam]:
        return None
    if op == "empty":
        return lambda r: _blank(get(r))
    if op == "not_empty":
        return lambda r: not _blank(get(r))
    if op == "yes":
        return lambda r: bool(get(r))
    if op == "no":
        return lambda r: not get(r)

    def neg(t):
        return t and (lambda r: not t(r))

    if fam == "text":
        if _blank(value):
            return None
        if op == "ne":
            return neg(leaf({**c, "op": "eq"}, d, today))
        if op == "not_contains":
            return neg(leaf({**c, "op": "contains"}, d, today))
        cmp = {"eq": lambda a, b: a == b, "contains": lambda a, b: b in a, "starts": lambda a, b: a.startswith(b)}[op]
        n = _js_str(value)
        nf = (fold(n), expand(n))
        nd = digits(n) if typ == "phone" else ""

        def t(r):
            v = get(r)
            if _blank(v):
                return False
            if nd:
                return cmp(digits(_js_str(v)), nd)
            s = _js_str(v)
            return cmp(fold(s), nf[0]) or cmp(expand(s), nf[1])
        return t

    if fam in ("number", "date"):
        if fam == "number":
            val, ok, parse = (lambda r: _num(get(r))), (lambda x: x == x), _num  # x == x: not NaN
        else:
            val, ok, parse = (lambda r: get(r) or ""), (lambda x: x != ""), (lambda v: v if _is_day(v) else "")
        if op in ("last", "older"):
            m = re.match(r"\s*([+-]?\d+)", _js_str(value))
            n = int(m[1]) if m else -1
            if n < 0:
                return None
            now, frm = today.isoformat(), (today - timedelta(days=n)).isoformat()
            if op == "last":
                return lambda r: ok(x := val(r)) and frm <= x <= now
            return lambda r: ok(x := val(r)) and x < frm
        if op == "between":
            lo, hi = [parse(v) for v in value[:2]] if isinstance(value, list) and len(value) >= 2 else (parse(""), parse(""))
            if not ok(lo) and not ok(hi):
                return None
            return lambda r: ok(x := val(r)) and (not ok(lo) or x >= lo) and (not ok(hi) or x <= hi)
        n = parse(value)
        if not ok(n):
            return None
        base = {"ne": "eq", "not_on": "on"}.get(op, op)
        cmp = {"eq": lambda x: x == n, "on": lambda x: x == n, "lt": lambda x: x < n, "before": lambda x: x < n,
               "le": lambda x: x <= n, "on_before": lambda x: x <= n, "gt": lambda x: x > n, "after": lambda x: x > n,
               "ge": lambda x: x >= n, "on_after": lambda x: x >= n}[base]
        t = lambda r: ok(x := val(r)) and cmp(x)
        return neg(t) if op in ("ne", "not_on") else t

    # choice / multi: a list of option values (usernames, record uids)
    wanted = {_js_str(x) for x in value} if isinstance(value, list) else set()
    if not wanted:
        return None
    lst = lambda r: [] if _blank(v := get(r)) else v if isinstance(v, list) else [v]
    hit = lambda r: any(isinstance(x, str) and x in wanted for x in lst(r))
    if op in ("in", "any"):
        return hit
    if op in ("not_in", "none"):
        return neg(hit)
    return lambda r: wanted <= {x for x in lst(r) if isinstance(x, str)}  # all


def compile_group(g, dfs, today):
    items = g.get("items") if isinstance(g, dict) else None
    tests = []
    for x in items if isinstance(items, list) else []:
        t = compile_group(x, dfs, today) if isinstance(x, dict) and "items" in x else \
            leaf(x, dfs.get(x.get("field")) if isinstance(x, dict) else None, today)
        if t:
            tests.append(t)
    if not tests:
        return None
    if g.get("mode") == "any":
        return lambda r: any(t(r) for t in tests)
    if g.get("mode") == "none":
        return lambda r: not any(t(r) for t in tests)
    return lambda r: all(t(r) for t in tests)


# ---------------------------------------------------------------- the list (listfilter.ts)

def _as_list(v):
    return v if isinstance(v, list) else [v]


def scope_keys(fields):
    return {"responsible": [f["key"] for f in fields if f["type"] == "user" and not f["archived"]],
            "internal": [f["key"] for f in fields if f["type"] == "users" and not f["archived"]]}


def match(state, records, fields, me, today=None, indexed=None):
    """The uids the list shows for this state. review/proposals scopes depend on the viewer's open work: never here.
    indexed: {uid: (hay, tel)} to reuse across calls; built only when the state has a search text."""
    today = today or timezone.localdate()
    by_uid = {r["uid"]: r for r in records}
    q = str(state.get("q") or "")
    found = matcher(q)
    if q.split() and indexed is not None and not indexed:
        indexed.update({r["uid"]: index(r, fields, by_uid) for r in records})
    at = compile_group(state.get("adv") or {}, defs(fields), today)
    keys = scope_keys(fields)
    scope, kind = state.get("scope") or "all", state.get("kind") or "all"
    quick = [(k, v) for k, v in (state.get("filters") or {}).items() if isinstance(v, list) and v]
    out = []
    for r in records:
        if kind != "all" and r["kind"] != kind:
            continue
        if scope in ("review", "proposals"):
            continue
        if scope in keys and not any(me in _as_list(r["data"].get(k)) for k in keys[scope]):
            continue
        if at and not at(r):
            continue
        if any(not any(y in vals for y in _as_list(r["data"].get(k))) for k, vals in quick):
            continue
        if q.split() and not found(*(indexed[r["uid"]] if indexed else index(r, fields, by_uid))):
            continue
        out.append(r["uid"])
    return out


def field_dicts(fields):
    return [{"key": f.key, "type": f.type, "searchable": f.searchable, "archived": f.archived, "options": f.options}
            for f in fields]


def row(r, visible_keys):
    """A Record as the browser has it: data only with the fields the viewer may see."""
    iso = lambda t: t.isoformat() if t else None
    return {"uid": str(r.uid), "kind": r.kind, "first_name": r.first_name, "last_name": r.last_name, "name": r.name,
            "legacy_id": r.legacy_id, "company": str(r.company.uid) if r.company_id and r.company else None,
            "data": {k: v for k, v in r.data.items() if k in visible_keys}, "created_at": iso(r.created_at),
            "updated_at": iso(r.updated_at), "reviewed_at": iso(r.reviewed_at),
            "updated_by": r.updated_by.username if r.updated_by_id and r.updated_by else None}
