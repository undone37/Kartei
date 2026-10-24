import json

from django.core.management.base import BaseCommand

from kartei.importer import import_csv


class Command(BaseCommand):
    help = "Import contacts from a CSV file (columns mapped by suggestion, overridable by a mapping JSON)."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--mapping", help="mapping JSON as downloaded under Settings → Import")
        parser.add_argument("--commit", action="store_true", help="write changes (default: dry run)")

    def handle(self, file, mapping=None, commit=False, **opts):
        m = None
        if mapping:
            with open(mapping, encoding="utf-8") as fh:
                m = json.load(fh)
        with open(file, "rb") as fh:
            result = import_csv(fh.read(), mapping=m, dry_run=not commit)
        self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
