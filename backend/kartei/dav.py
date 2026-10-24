"""Read-only CardDAV protocol (RFC 6352), independent of where the cards come from.

Serves one address book: /carddav/ is principal + addressbook home, /carddav/kontakte/ the book. Used by the built-in
server (carddav.py, cards rendered from the Kartei database) and by the DMZ relay (relay app, pushed cards).
No model imports here: the relay runs without the kartei app.

A book is created per request (after authentication) by `book(flavour)` and offers:
  ctag() -> str
  etags(uid=None) -> [(uid, etag)]           all cards, or the one card
  cards(uids=None) -> [(uid, etag, vcard)]   all cards, or those with these uids
"""
import base64
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.utils.crypto import salted_hmac
from django.http import HttpResponse, HttpResponseRedirect

from .net import client_ip
from .vcard import flavour_for

D, CARD, CS = "DAV:", "urn:ietf:params:xml:ns:carddav", "http://calendarserver.org/ns/"
ET.register_namespace("d", D)
ET.register_namespace("card", CARD)
ET.register_namespace("cs", CS)
ROOT, BOOK = "/carddav/", "/carddav/kontakte/"
q = lambda ns, tag: f"{{{ns}}}{tag}"


def unauthorized():
    r = HttpResponse("Unauthorized", status=401)
    r["WWW-Authenticate"] = 'Basic realm="Kartei CardDAV", charset="UTF-8"'
    return r


def authorized(request, username, password_hash):
    """Basic auth against one user; 20 failures per client address lock it out for 15 minutes."""
    key = f"carddav-fail:{client_ip(request)}"
    if cache.get(key, 0) >= 20:
        return False
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            user, pw = "", ""
        # a phone sync makes several requests, each would pay the deliberately slow password hash (~0.2 s CPU):
        # remember a successful check for 5 minutes; a new password means a new hash and so a new key
        ok = "carddav-ok:" + salted_hmac("kartei.carddav", f"{password_hash}\0{user}\0{pw}").hexdigest()
        if password_hash and user == username and (cache.get(ok) or check_password(pw, password_hash)):
            cache.set(ok, True, 5 * 60)
            return True
        cache.set(key, cache.get(key, 0) + 1, 15 * 60)
    return False


def _requested(body):
    """Requested property tags from a PROPFIND/REPORT body; None = allprop."""
    if not body:
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    prop = root.find(q(D, "prop"))
    return None if prop is None else [child.tag for child in prop]


def _response(ms, href, props, requested):
    resp = ET.SubElement(ms, q(D, "response"))
    ET.SubElement(resp, q(D, "href")).text = href
    found, missing = [], []
    for tag in (requested if requested is not None else props.keys()):
        (found if tag in props else missing).append(tag)
    for tags, status in ((found, "200 OK"), (missing, "404 Not Found")):
        if not tags:
            continue
        ps = ET.SubElement(resp, q(D, "propstat"))
        p = ET.SubElement(ps, q(D, "prop"))
        for tag in tags:
            el = ET.SubElement(p, tag)
            props.get(tag, lambda e: None)(el)
        ET.SubElement(ps, q(D, "status")).text = f"HTTP/1.1 {status}"


def _multistatus(ms):
    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(ms)
    return HttpResponse(body, status=207, content_type="application/xml; charset=utf-8")


def _href(el, url):
    ET.SubElement(el, q(D, "href")).text = url


def _text(value):
    def fill(el):
        el.text = value
    return fill


def _root_props():
    return {
        q(D, "resourcetype"): lambda e: ET.SubElement(e, q(D, "collection")),
        q(D, "displayname"): _text("Kartei"),
        q(D, "current-user-principal"): lambda e: _href(e, ROOT),
        q(D, "principal-URL"): lambda e: _href(e, ROOT),
        q(CARD, "addressbook-home-set"): lambda e: _href(e, ROOT),
    }


def _book_props(ctag):
    def resourcetype(e):
        ET.SubElement(e, q(D, "collection"))
        ET.SubElement(e, q(CARD, "addressbook"))

    def reports(e):
        for name in ("addressbook-multiget", "addressbook-query"):
            ET.SubElement(ET.SubElement(ET.SubElement(e, q(D, "supported-report")), q(D, "report")), q(CARD, name))

    def privileges(e):
        ET.SubElement(ET.SubElement(e, q(D, "privilege")), q(D, "read"))

    def address_data(e):
        ET.SubElement(e, q(CARD, "address-data-type"), {"content-type": "text/vcard", "version": "3.0"})

    return {
        q(D, "resourcetype"): resourcetype,
        q(D, "displayname"): _text("Kartei Kontakte"),
        q(CS, "getctag"): _text(ctag),
        q(D, "current-user-principal"): lambda e: _href(e, ROOT),
        q(D, "supported-report-set"): reports,
        q(D, "current-user-privilege-set"): privileges,
        q(CARD, "supported-address-data"): address_data,
    }


def _card_props(etag, vcf=None):
    props = {
        q(D, "getetag"): _text(etag),
        q(D, "getcontenttype"): _text("text/vcard; charset=utf-8"),
        q(D, "resourcetype"): lambda e: None,
    }
    if vcf is not None:
        props[q(CARD, "address-data")] = _text(vcf)
    return props


def well_known(request):
    return HttpResponseRedirect(ROOT)


def serve(request, uid, username, password_hash, book):
    """One CardDAV request. uid: card from the URL (validated by the URL pattern) or None for root/book."""
    if request.method == "OPTIONS":
        r = HttpResponse()
        r["DAV"] = "1, 3, addressbook"
        r["Allow"] = "OPTIONS, GET, HEAD, PROPFIND, REPORT"
        return r
    if not authorized(request, username, password_hash):
        return unauthorized()
    if request.method not in ("GET", "HEAD", "PROPFIND", "REPORT"):
        return HttpResponse("read-only", status=403)

    b = book(flavour_for(request.META.get("HTTP_USER_AGENT")))
    path = request.path

    if uid is not None:  # single card
        if request.method in ("GET", "HEAD"):
            found = b.cards([uid])
            if not found:
                return HttpResponse(status=404)
            _, etag, vcf = found[0]
            resp = HttpResponse(vcf if request.method == "GET" else b"", content_type="text/vcard; charset=utf-8")
            resp["ETag"] = etag
            return resp
        if request.method == "PROPFIND":
            found = b.etags(uid)
            if not found:
                return HttpResponse(status=404)
            ms = ET.Element(q(D, "multistatus"))
            _response(ms, path, _card_props(found[0][1]), _requested(request.body))
            return _multistatus(ms)
        return HttpResponse(status=405)

    depth = request.META.get("HTTP_DEPTH", "1")
    if request.method == "PROPFIND":
        requested = _requested(request.body)
        ms = ET.Element(q(D, "multistatus"))
        if path == ROOT:
            _response(ms, ROOT, _root_props(), requested)
            if depth != "0":
                _response(ms, BOOK, _book_props(b.ctag()), requested)
        elif path == BOOK:
            _response(ms, BOOK, _book_props(b.ctag()), requested)
            if depth != "0":
                for u, etag in b.etags():
                    _response(ms, f"{BOOK}{u}.vcf", _card_props(etag), requested)
        else:
            return HttpResponse(status=404)
        return _multistatus(ms)

    if request.method == "REPORT" and path == BOOK:
        try:
            root = ET.fromstring(request.body or b"<x/>")
        except ET.ParseError:
            return HttpResponse(status=400)
        uids = None
        if root.tag == q(CARD, "addressbook-multiget"):
            uids = []
            for h in root.iter(q(D, "href")):
                name = unquote(urlparse(h.text or "").path).rstrip("/").rsplit("/", 1)[-1]
                if name.endswith(".vcf"):
                    try:
                        uids.append(str(uuid.UUID(name[:-4])))
                    except ValueError:
                        pass
        elif root.tag != q(CARD, "addressbook-query"):
            return HttpResponse(status=403)
        # ponytail: addressbook-query filters are ignored, all cards returned (fine for a single shared book)
        requested = _requested(request.body)
        ms = ET.Element(q(D, "multistatus"))
        for u, etag, vcf in b.cards(uids):
            _response(ms, f"{BOOK}{u}.vcf", _card_props(etag, vcf), requested)
        return _multistatus(ms)

    if request.method in ("GET", "HEAD"):
        return HttpResponse("Kartei CardDAV", content_type="text/plain")
    return HttpResponse(status=405)
