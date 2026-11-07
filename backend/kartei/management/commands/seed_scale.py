"""Many fictional contacts for measuring how Kartei behaves at scale (see measure_scale and
frontend/scripts/measure-scale.mjs). Every field of the example field set gets plausible values; some contacts have a
photo. Deterministic (fixed random seed); only on an installation without contacts. Never on production data."""
import json
import random
import zlib
from pathlib import Path

from django.conf import settings as dj
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from kartei.api import import_fields
from kartei.models import FieldDef, Profile, Record, Role

FIELDS = Path(dj.BASE_DIR).parent / "examples" / "fields-example.json"
FIRST = ["Anna", "Ben", "Clara", "David", "Emma", "Felix", "Greta", "Hannes", "Ida", "Jonas", "Klara", "Lukas", "Mia",
         "Noah", "Ole", "Paula", "Sophie", "Tim", "Łukasz", "Zoë", "Çağla", "Søren"]
LAST = ["Becker", "Fischer", "Hoffmann", "Koch", "Meyer", "Müller", "Richter", "Schmidt", "Schneider", "Schulz",
        "Wagner", "Weber", "Nowak", "Yılmaz", "Dubois"]
CITIES = [("Hannover", "30159"), ("Hamburg", "20095"), ("Essen", "45127"), ("Leipzig", "04109"), ("Stuttgart", "70173"),
          ("Freiburg", "79098"), ("Bremen", "28195"), ("Kassel", "34117")]
WORDS = "Netz Energie Wartung Vertrag Projekt Angebot Rechnung Termin Leitung Planung Service Messung".split()


def _png(size, seed):
    """A small valid PNG of noise, roughly `size` bytes (a stand-in for a photo)."""
    rnd = random.Random(seed)
    side = max(8, int((size / 3) ** 0.5))
    raw = b"".join(b"\x00" + bytes(rnd.getrandbits(8) for _ in range(side * 3)) for _ in range(side))
    chunk = lambda t, d: len(d).to_bytes(4, "big") + t + d + zlib.crc32(t + d).to_bytes(4, "big")
    ihdr = side.to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")


class Command(BaseCommand):
    help = "Create many fictional contacts in an empty Kartei, for load and performance measurements"

    def add_arguments(self, parser):
        parser.add_argument("--persons", type=int, default=50000)
        parser.add_argument("--companies", type=int, default=5000)
        parser.add_argument("--photos", type=int, default=2000, help="contacts with a photo (about 30 KB each)")
        parser.add_argument("--users", type=int, default=40, help="Kartei users named as internal contacts")
        parser.add_argument("--password", default="scale-12345", help="password of the scale users")

    def handle(self, *args, persons, companies, photos, users, password, **opts):
        if Record.objects.exists():
            raise CommandError("Kartei already contains contacts; seed_scale only runs on an empty installation.")
        rnd = random.Random(7)
        import_fields(json.loads(FIELDS.read_text(encoding="utf-8")), apply=True)
        fields = list(FieldDef.objects.filter(archived=False))
        names = []
        for i in range(users):
            u, _ = User.objects.get_or_create(username=f"scale{i:03}", defaults={
                "first_name": rnd.choice(FIRST), "last_name": rnd.choice(LAST), "email": f"scale{i:03}@example.com"})
            u.set_password(password)
            u.save()
            Profile.objects.update_or_create(user=u, defaults={"role": Role.MAINTAINER if i < 5 else Role.READ})
            names.append(u.username)
        photo = _png(30_000, 1)

        def value(f, kind, i):
            if f.type == "phone":
                return f"+49 {rnd.randint(30, 9999)} {rnd.randint(100000, 9999999)}"
            if f.type == "email":
                return f"kontakt{i}.{f.key}@example.com"
            if f.type == "url":
                return f"https://www.beispiel-{i}.example"
            if f.type == "date":
                return f"19{rnd.randint(50, 99)}-{rnd.randint(1, 12):02}-{rnd.randint(1, 28):02}"
            if f.type in ("select", "multiselect"):
                opts_ = [o["value"] for o in f.options] or WORDS[:5]
                return rnd.choice(opts_) if f.type == "select" else rnd.sample(opts_, min(len(opts_), rnd.randint(1, 3)))
            if f.type == "user":
                return rnd.choice(names)
            if f.type == "users":
                return rnd.sample(names, rnd.randint(1, 3))
            if f.type == "longtext":
                return "\n".join(" ".join(rnd.choices(WORDS, k=8)) for _ in range(rnd.randint(1, 4)))
            if f.type in ("integer", "decimal"):
                return rnd.randint(1, 9999)
            if f.type == "text":
                if "zip" in f.key:
                    return rnd.choice(CITIES)[1]
                if "city" in f.key:
                    return rnd.choice(CITIES)[0]
                return " ".join(rnd.choices(WORDS, k=rnd.randint(1, 3)))
            return None

        def data(kind, i):
            out = {}
            for f in fields:
                if f.applies(kind) and f.type not in ("checkbox", "contact") and rnd.random() < 0.6:
                    if (v := value(f, kind, i)) not in (None, "", []):
                        out[f.key] = v
            return out

        made = Record.objects.bulk_create(
            [Record(kind="company", name=f"{rnd.choice(WORDS)} {rnd.choice(LAST)} {i} GmbH", legacy_id=f"F-{i}",
                    data=data("company", i), image=photo if i < photos // 10 else None,
                    image_type="png" if i < photos // 10 else "") for i in range(companies)], batch_size=1000)
        company_ids = [c.id for c in made]
        with_photo = photos - photos // 10
        for start in range(0, persons, 2000):
            Record.objects.bulk_create(
                [Record(kind="person", first_name=rnd.choice(FIRST), last_name=rnd.choice(LAST), legacy_id=f"P-{i}",
                        company_id=rnd.choice(company_ids) if rnd.random() < 0.9 else None, data=data("person", i),
                        image=photo if i < with_photo else None, image_type="png" if i < with_photo else "")
                 for i in range(start, min(start + 2000, persons))], batch_size=1000)
            self.stdout.write(f"persons: {min(start + 2000, persons)}/{persons}", ending="\r")
        self.stdout.write(f"\n{companies} companies, {persons} persons ({photos} with photo), {users} users "
                          f"(scale000…, password {password})")
