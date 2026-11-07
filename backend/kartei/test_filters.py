import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from . import filters

CASES = Path(settings.BASE_DIR).parent / "frontend" / "tests" / "filter-cases.json"


@override_settings(TIME_ZONE="Europe/Berlin")
class FilterParityTests(SimpleTestCase):
    """The server evaluates saved filters exactly like the list in the browser: same cases, same contacts."""

    def test_same_contacts_as_the_browser(self):
        doc = json.loads(CASES.read_text(encoding="utf-8"))
        today = date.fromisoformat(doc["today"])
        for c in doc["cases"]:
            with self.subTest(c["name"]):
                got = sorted(filters.match(c["state"], doc["records"], doc["fields"], doc["me"], today))
                self.assertEqual(got, c["expect"])
