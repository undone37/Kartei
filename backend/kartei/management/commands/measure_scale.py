"""Measures the heavy server operations on the current data (e.g. after seed_scale): time, response size and the
process's peak memory after each. Read-only apart from one login session."""
import gzip
import json
import time
import resource
from unittest import mock

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.test import Client

from kartei import exports, graph
from kartei.models import (ExportProfile, FieldDef, Record, Settings, default_csv_options, default_xlsx_options,
                           ref_names)
from kartei.vcard import render


class Command(BaseCommand):
    help = "Time the heavy operations (full sync, delta sync, CardDAV, exports, Outlook preparation) on this data"

    def add_arguments(self, parser):
        parser.add_argument("--user", default=None, help="user whose view is measured (default: the first admin)")

    def measure(self, name, fn):
        started = time.perf_counter()
        result = fn()
        seconds = time.perf_counter() - started
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # ponytail: process peak so far, not per step
        size = ""
        if isinstance(result, (bytes, bytearray)):
            size = f"{len(result) / 1e6:7.1f} MB raw, {len(gzip.compress(result, 6)) / 1e6:6.1f} MB gzip"
        self.stdout.write(f"{name:<34}{seconds:7.2f} s   RSS peak {peak / 1e6:6.0f} MB   {size}")
        return result

    def handle(self, *args, user=None, **opts):
        u = User.objects.get(username=user) if user else User.objects.filter(is_superuser=True).first()
        n = Record.objects.filter(deleted_at__isnull=True).count()
        photos = Record.objects.exclude(image_type="").count()
        self.stdout.write(f"{n} contacts ({photos} with photo), user {u.username}\n")
        c = Client(HTTP_HOST="localhost")
        c.force_login(u)
        boot = self.measure("bootstrap (full sync)", lambda: c.get("/api/bootstrap").content)
        cursor = json.loads(boot)["cursor"]
        self.measure("changes (delta, nothing new)", lambda: c.get("/api/changes", {"since": cursor}).content)

        s = Settings.get()
        fields = list(FieldDef.objects.filter(archived=False, visible_to="read"))
        names = ref_names()
        self.measure("CardDAV: render all cards", lambda: "".join(  # what a phone's first full sync costs the server
            render(r, fields, "ios", s.base_url, names) for r in
            Record.objects.filter(deleted_at__isnull=True).select_related("company").iterator(chunk_size=500)).encode())

        p = ExportProfile(name="measure", format="csv", path="/tmp/kartei-measure.csv", kinds="both", columns=[
            {"header": f.label_de, "person": f"field:{f.key}", "company": f"field:{f.key}"} for f in fields[:25]]
            + [{"header": "Name", "person": "calc:display_name", "company": "calc:display_name"}])
        header, rows = self.measure("export: build rows", lambda: exports.build_rows(p))
        self.measure("export: CSV", lambda: exports.render_csv(header, rows, default_csv_options()))
        self.measure("export: Excel", lambda: exports.render_xlsx(header, rows, default_xlsx_options()))

        class NoMailboxes(graph.Client):  # stops right after preparing all contacts, before any network call
            def __init__(self, s):
                pass
        with mock.patch.object(graph, "Client", NoMailboxes), mock.patch.object(graph, "mailboxes", return_value={}):
            def outlook():
                try:
                    graph._sync(s)
                except graph.GraphError:
                    pass
            self.measure("Outlook: prepare all contacts", outlook)
