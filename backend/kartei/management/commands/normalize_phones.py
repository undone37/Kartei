import json

from django.core.management.base import BaseCommand

from kartei.quality import normalize_phones


class Command(BaseCommand):
    help = "Bring stored phone numbers into the international form (see Settings.phone_country_code)"

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="write changes (default: dry run)")

    def handle(self, commit=False, **opts):
        self.stdout.write(json.dumps(normalize_phones(dry_run=not commit), indent=2, ensure_ascii=False))
