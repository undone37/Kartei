"""Sample data for trying Kartei and for the manual screenshots: fictional companies, persons, users, reviews,
proposals, favorites and saved filters. Deterministic (fixed random seed), refuses to run when contacts exist."""
import json
import random
import secrets
from datetime import timedelta
from pathlib import Path

from django.conf import settings as dj
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from kartei import audit, exports, reviews
from kartei.api import delete_tree, import_fields
from kartei.models import ExportProfile, FieldDef, Profile, Proposal, Record, Role, SavedFilter, Settings

FIELDS = Path(dj.BASE_DIR).parent / "examples" / "fields-example.json"

USERS = [  # username, first, last, role
    ("mmuster", "Max", "Muster", Role.MAINTAINER),
    ("kkramer", "Kim", "Kramer", Role.READ),
    ("lschmidt", "Lena", "Schmidt", Role.READ),
    ("tbauer", "Tom", "Bauer", Role.MAINTAINER),
]

COMPANIES = [  # name, short, city, zip, street, area code, keywords
    ("Musterfirma Energie AG", "Musterfirma", "Hannover", "30159", "Testallee 2", "511", ["Kunde", "Energie"]),
    ("Beispielwerke Nord GmbH", "Beispielwerke", "Hamburg", "20095", "Musterweg 1", "40", ["Lieferant"]),
    ("Demo Netz GmbH", "Demo Netz", "Essen", "45127", "Probestraße 3", "201", ["Kunde", "Netz"]),
    ("Fiktiv Software KG", "Fiktiv", "Leipzig", "04109", "Codegasse 8", "341", ["Partner", "IT"]),
    ("Platzhalter Logistik GmbH", "Platzhalter", "Stuttgart", "70173", "Hafenstraße 12", "711", ["Lieferant", "Logistik"]),
    ("Beispiel Stiftung", "Stiftung", "Freiburg", "79098", "Am Park 4", "761", []),  # no persons: data quality case
]
FIRST = ["Anna", "Ben", "Clara", "David", "Emma", "Felix", "Greta", "Hannes", "Ida", "Jonas", "Klara", "Lukas",
         "Mia", "Noah", "Ole", "Paula", "Sophie", "Tim"]
LAST = ["Becker", "Fischer", "Hoffmann", "Koch", "Meyer", "Müller", "Richter", "Schmidt", "Schneider", "Schulz",
        "Wagner", "Weber"]
JOBS = [("Geschäftsführung", "Leitung"), ("Einkauf", "Einkauf"), ("Vertrieb", "Vertrieb"), ("IT", "IT"),
        ("Netzbetrieb", "Technik"), ("Buchhaltung", "Finanzen")]


class Command(BaseCommand):
    help = "Create fictional demo data (contacts, users, reviews, proposals) in an empty Kartei"

    def add_arguments(self, parser):
        parser.add_argument("--password", help="password for all demo users (default: random, printed once)")

    def handle(self, *args, password=None, **opts):
        if Record.objects.exists():
            raise CommandError("Kartei already contains contacts; seed_demo only runs on an empty installation.")
        rnd = random.Random(42)
        res = import_fields(json.loads(FIELDS.read_text(encoding="utf-8")), apply=True)["fields"]
        self.stdout.write(f"fields: {sum(r['status'] == 'new' for r in res)} new")
        password = password or secrets.token_urlsafe(9)
        users = {}
        for username, first, last, role in USERS:
            u, _ = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last,
                                                                           "email": f"{username}@example.com"})
            u.set_password(password)
            u.save()
            Profile.objects.update_or_create(user=u, defaults={"role": role, "source": "local"})
            users[username] = u
        names = list(users)
        known = set(FieldDef.objects.values_list("key", flat=True))
        data = lambda **kw: {k: v for k, v in kw.items() if k in known and v not in (None, "", [])}

        companies = []
        for i, (name, short, city, zip_, street, area, keywords) in enumerate(COMPANIES):
            domain = short.lower().replace(" ", "-") + ".example"
            c = Record.objects.create(kind="company", name=name, data=data(
                short_name=short, company_phone=f"+49 {area} {1000 + i * 111}", company_email=f"info@{domain}",
                website=f"https://{domain}", work_street=street, work_zip=zip_, work_city=city,
                work_country="Deutschland", keywords=keywords, internal_contact=names[i % 2],
                internal_contacts=[names[(i + 1) % len(names)], names[(i + 2) % len(names)]],
                customer_no=f"K-{20000 + i * 37}"))
            audit.log(None, "create", "record", c.uid, c.name, {"name": [None, c.name]})
            companies.append((c, domain))

        persons, ext = [], 10
        for c, domain in companies[:-1]:
            for _ in range(rnd.randint(8, 13)):
                first, last = rnd.choice(FIRST), rnd.choice(LAST)
                job, dept = rnd.choice(JOBS)
                ext += 1
                p = Record.objects.create(kind="person", first_name=first, last_name=last, company=c, data=data(
                    salutation="Frau" if first in ("Anna", "Clara", "Emma", "Greta", "Ida", "Klara", "Mia", "Paula",
                                                   "Sophie") else "Herr",
                    job_title=job, department=dept,
                    email=f"{first.lower()}.{last.lower().replace('ü', 'ue')}@{domain}",
                    phone_work=f"{c.data['company_phone']}-{ext}", mobile=f"+49 170 {rnd.randint(1000000, 9999999)}",
                    work_street=c.data["work_street"], work_zip=c.data["work_zip"], work_city=c.data["work_city"],
                    work_country="Deutschland", keywords=c.data.get("keywords", [])[:1],
                    internal_contact=rnd.choice(names), internal_contacts=rnd.sample(names, rnd.randint(0, 2))))
                persons.append(p)
            ceo = next((p for p in persons if p.company_id == c.id and p.data.get("job_title") == "Geschäftsführung"), None)
            if ceo and "ceo" in known:
                c.data["ceo"] = str(ceo.uid)
                c.save(update_fields=["data"])
        # data quality cases: a duplicate pair, a person without company, an invalid email
        twin = persons[3]
        persons.append(Record.objects.create(kind="person", first_name=twin.first_name, last_name=twin.last_name,
                                             company=twin.company, data=data(job_title="Vertrieb",
                                                                             internal_contact="mmuster")))
        persons.append(Record.objects.create(kind="person", first_name="Ida", last_name="Freiberuflich",
                                             data=data(email="ida@freiberuflich.example", internal_contact="kkramer")))
        for p in persons:
            audit.log(None, "create", "record", p.uid, p.display_name, {"last_name": [None, p.last_name]})
        # values written directly become options, like saving through the app does for open choice fields
        for f in FieldDef.objects.filter(type__in=("select", "multiselect")):
            known = {o["value"] for o in f.options}
            used = {v for r in Record.objects.filter(data__has_key=f.key)
                    for v in (r.data[f.key] if isinstance(r.data[f.key], list) else [r.data[f.key]])}
            if new := sorted(used - known):
                f.options = f.options + [{"value": v, "de": v, "en": v} for v in new]
                f.save(update_fields=["options"])

        # some contacts were reviewed a while ago, the reviewers get open reviews
        Record.objects.filter(pk__in=[p.pk for p in persons[::4]]).update(
            reviewed_at=timezone.now() - timedelta(days=200), reviewed_by=users["kkramer"])
        reviews.start(Record.objects.filter(deleted_at__isnull=True), "manual")

        # proposals by the read-only reviewer
        mine = [p for p in persons if p.data.get("internal_contact") == "kkramer"]
        if len(mine) >= 2:
            p = mine[0]
            Proposal.objects.create(record=p, kind="change", changes={"core": {}, "data": {"job_title": "Teamleitung Einkauf"}},
                                    base={"core": {}, "data": {"job_title": p.data.get("job_title")}},
                                    comment="Laut E-Mail-Signatur befördert", proposer=users["kkramer"],
                                    proposer_name="kkramer")
            Proposal.objects.create(record=mine[1], kind="delete", reason="left", comment="Nicht mehr im Unternehmen",
                                    proposer=users["kkramer"], proposer_name="kkramer")
        Proposal.objects.create(record=companies[2][0], kind="delete", reason="company_gone",
                                comment="Firma laut Handelsregister aufgelöst", proposer=users["kkramer"],
                                proposer_name="kkramer")
        c0 = companies[0][0]  # a new colleague at a customer, proposed by the read-only user
        Proposal.objects.create(kind="create", record_kind="person", proposer=users["kkramer"], proposer_name="kkramer",
                                comment="Neue Ansprechpartnerin laut Telefonat",
                                changes={"core": {"first_name": "Nina", "last_name": "Neumann", "company": str(c0.uid)},
                                         "data": data(salutation="Frau", job_title="Einkauf", department="Einkauf",
                                                      email=f"nina.neumann@{companies[0][1]}",
                                                      phone_work=f"{c0.data['company_phone']}-77",
                                                      internal_contact="kkramer")})

        # dashboard: recently viewed, favorites, saved filters
        for username in ("mmuster", "kkramer"):
            prof = users[username].profile
            prof.recent = [str(p.uid) for p in rnd.sample(persons, 6)]
            prof.favorites = [str(p.uid) for p in rnd.sample(persons, 3)]
            prof.save(update_fields=["recent", "favorites"])
        SavedFilter.objects.create(owner=users["mmuster"], name="Firmen", shared=True,
                                   state={"q": "", "scope": "all", "kind": "company", "filters": {}})
        SavedFilter.objects.create(owner=users["mmuster"], name="Einkauf", state={"q": "einkauf", "scope": "all",
                                                                                  "kind": "person", "filters": {}})
        # two sample exports, disabled until someone checks path and columns
        cols = [{"header": h, "person": pp, "company": cc} for h, pp, cc in [
            ("ID", "calc:uid", "calc:uid"), ("Name", "calc:display_name", "calc:display_name"),
            ("Firma", "calc:company_name", "core:name"), ("Telefon", "field:phone_work", "field:company_phone"),
            ("E-Mail", "field:email", "field:company_email"), ("Ort", "field:work_city", "field:work_city")]]
        for name, fmt, file in [("Kontakte (CSV)", "csv", "kontakte.csv"), ("Kontakte (Excel)", "xlsx", "kontakte.xlsx")]:
            ExportProfile.objects.create(name=name, format=fmt, enabled=False, path=f"{exports.EXPORT_ROOT}/{file}", columns=cols)
        Settings.objects.filter(pk=1).update(review_mode="rolling", review_interval_months=12)
        # a few contacts in the recycle bin, deleted by the maintainers over the last days
        for (first, last, job), (c, domain), who, days in zip(
                [("Lea", "Vogel", "Einkauf"), ("Jan", "Krüger", "Vertrieb"), ("Sara", "Lindner", "Buchhaltung")],
                companies, ("mmuster", "tbauer", "mmuster"), (1, 4, 9)):
            r = Record.objects.create(kind="person", first_name=first, last_name=last, company=c, data=data(
                job_title=job, email=f"{first.lower()}.{last.lower().replace('ü', 'ue')}@{domain}",
                internal_contact=who))
            audit.log(None, "create", "record", r.uid, r.display_name, {"last_name": [None, last]})
            delete_tree(users[who], r)
            Record.objects.filter(pk=r.pk).update(deleted_at=timezone.now() - timedelta(days=days, hours=3 * days))
        self.stdout.write(self.style.SUCCESS(
            f"{len(companies)} companies, {len(persons)} persons, users {', '.join(names)} (password: {password})"))
