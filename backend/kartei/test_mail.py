from unittest import mock

from django.core import mail
from django.test import TestCase

from . import graph, reviews
from .models import Settings
from .tests import ApiTestBase


class TemplateTests(TestCase):
    def test_custom_template_and_fallback(self):
        s = Settings.get()
        self.assertEqual(reviews.render_mail(s, "review", "en", n=2, name="Kim", items="- A", url="u")[0],
                         "Kartei: 2 contact(s) to review")
        s.mail_templates = {"review": {"de": {"subject": "{n} neue Prüfungen", "body": "Hallo {name}\n{items}\n{url}"}}}
        self.assertEqual(reviews.render_mail(s, "review", "de", n=3, name="Kim", items="- A", url="u"),
                         ("3 neue Prüfungen", "Hallo Kim\n- A\nu"))
        s.mail_templates = {"review": {"de": {"subject": "{unbekannt} {", "body": ""}}}  # broken: default is used
        self.assertEqual(reviews.render_mail(s, "review", "de", n=1, name="Kim", items="", url="u")[0],
                         "Kartei: 1 Kontakt(e) zu prüfen")

    def test_check_templates(self):
        self.assertIsNone(reviews.check_templates({"reminder": {"en": {"subject": "{n} left", "body": "{items}"}}}))
        self.assertEqual(reviews.check_templates({"review": {"de": {"subject": "{foo}"}}}), "invalid_template")
        self.assertEqual(reviews.check_templates({"spam": {}}), "invalid")


class TemplateApiTests(ApiTestBase):
    def test_settings_roundtrip(self):
        self.as_("admin")
        bad = self.j("put", "/api/admin/settings", {"mail_templates": {"review": {"de": {"subject": "{x}"}}}}, status=400)
        self.assertEqual(bad["fields"]["mail_templates"], "invalid_template")
        s = self.j("put", "/api/admin/settings", {"mail_templates": {"review": {"de": {"subject": "{n} offen", "body": "{items}"}}}})
        self.assertEqual(s["mail_templates"]["review"]["de"]["subject"], "{n} offen")
        self.assertIn("reminder", s["mail_template_defaults"])


class GraphMailTests(TestCase):
    def test_send_through_microsoft_365(self):
        s = Settings.get()
        s.mail_transport, s.mail_graph_sender = "graph", "kartei@firma.de"
        s.graph_tenant_id, s.graph_client_id, s.graph_client_secret = "t", "c", "secret"
        s.save()
        self.assertTrue(reviews.mail_ready(s))
        calls = []

        def fake(method, url, body=None, token=None, form=None, ctype=None):
            calls.append((method, url, body, form))
            return {"access_token": "tok"} if form else {}
        with mock.patch.object(graph, "http", fake), reviews.mail_connection(s) as conn:
            mail.EmailMessage("Betreff", "Text", reviews.mail_from(s), ["a@b.de"], connection=conn).send()
        token, send = calls
        self.assertEqual(token[3]["grant_type"], "client_credentials")  # OAuth2, no password auth
        self.assertTrue(send[1].endswith("/users/kartei%40firma.de/sendMail"))
        self.assertEqual(send[2]["message"]["toRecipients"], [{"emailAddress": {"address": "a@b.de"}}])
        self.assertEqual(send[2]["message"]["body"], {"contentType": "Text", "content": "Text"})
        s.mail_graph_sender = ""
        self.assertFalse(reviews.mail_ready(s))
