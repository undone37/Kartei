# After the upgrade test's migrations: the new code serves the old data (python manage.py shell < upgrade-smoke.py)
from django.test import Client

c = Client(HTTP_HOST="localhost")
assert c.post("/api/login", {"username": "mmuster", "password": "demo12345"}, content_type="application/json").status_code == 200
b = c.get("/api/bootstrap").json()
assert len(b["records"]) > 50 and len(b["proposals"]) >= 3, (len(b["records"]), len(b["proposals"]))
assert c.get(f"/api/records/{b['records'][0]['uid']}").status_code == 200
print("SMOKE OK", len(b["records"]), "records", len(b["proposals"]), "proposals")
