import base64
import json
import logging
import socket
import ssl
import threading
from datetime import timedelta
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase
from django.utils import timezone

from . import logs, monitoring, syslog
from .management.commands import export_loop
from .models import AuditEntry, ExportProfile, Settings
from .tests import ApiTestBase


def session_log():
    return list(AuditEntry.objects.filter(target_type="session").order_by("id").values_list("action", "target_label", "changes", "ip"))


class SigninAuditTests(ApiTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def login(self, username, password, status, **extra):
        r = self.client.post("/api/login", json.dumps({"username": username, "password": password}),
                             content_type="application/json", REMOTE_ADDR="10.0.0.7", **extra)
        self.assertEqual(r.status_code, status, r.content)

    def test_login_logout_and_failures(self):
        self.login("read", "wrong", 401)
        self.login("nobody", "x", 401)
        self.login("read", "pw-readreadread", 200)
        self.client.post("/api/logout", REMOTE_ADDR="10.0.0.7")
        self.assertEqual(session_log(), [
            ("login_failed", "read", {"reason": [None, "invalid_credentials"]}, "10.0.0.7"),
            ("login_failed", "nobody", {"reason": [None, "invalid_credentials"]}, "10.0.0.7"),
            ("login", "read", {"method": [None, "password"]}, "10.0.0.7"),
            ("logout", "read", {}, "10.0.0.7"),
        ])
        entry = AuditEntry.objects.get(action="login_failed", target_label="nobody")
        self.assertEqual((entry.username, entry.user_id), ("nobody", None))

    def test_lockout_is_logged_once(self):
        for _ in range(13):
            self.login("read", "wrong", 401 if _ < 10 else 429)
        actions = [(a, c["reason"][1]) for a, _, c, _ in session_log()]
        self.assertEqual(actions.count(("login_failed", "too_many_attempts")), 1)

    def test_denied_and_ip_on_every_entry(self):
        self.as_("read")
        self.client.get("/api/admin/fields", REMOTE_ADDR="10.0.0.8")
        self.assertEqual(session_log()[-1][0::3], ("denied", "10.0.0.8"))
        self.as_("maintainer")
        self.client.post("/api/records", json.dumps({"kind": "company", "name": "X"}), content_type="application/json",
                         REMOTE_ADDR="2001:db8::1")
        self.assertEqual(AuditEntry.objects.get(action="create", target_type="record").ip, "2001:db8::1")

    def test_carddav_and_api_failures_are_throttled(self):
        s = Settings.get()
        s.carddav_enabled, s.carddav_username, s.carddav_password_hash = True, "phone", make_password("right")
        s.save()
        bad = "Basic " + base64.b64encode(b"phone:wrong").decode()
        for _ in range(3):
            self.client.generic("PROPFIND", "/carddav/kontakte/", HTTP_AUTHORIZATION=bad, HTTP_DEPTH="0")
            self.client.get("/api/v1/contacts", HTTP_AUTHORIZATION="Bearer nope")
        self.assertEqual([(a, c["channel"][1]) for a, _, c, _ in session_log()], [("auth_failed", "carddav"), ("auth_failed", "api")])

    def test_retention(self):
        self.login("read", "wrong", 401)
        AuditEntry.objects.filter(target_type="session").update(at=timezone.now() - timedelta(days=91))
        self.login("read", "wrong", 401)
        AuditEntry.objects.create(action="update", target_type="settings", target_id="1")
        AuditEntry.objects.filter(target_type="settings").update(at=timezone.now() - timedelta(days=400))
        with mock.patch.object(export_loop, "graph"), mock.patch.object(export_loop, "adsync"), \
                mock.patch.object(export_loop, "relaypush"):
            export_loop.tick()
        self.assertEqual(len(session_log()), 1)  # the old sign-in entry is gone, the fresh one stays
        self.assertTrue(AuditEntry.objects.filter(target_type="settings").exists())  # changes are kept
        self.assertIsNotNone(Settings.get().exporter_seen_at)


class MonitoringTests(ApiTestBase):
    def status(self, token="", ip="10.1.2.3", query=""):
        return self.client.get("/api/monitoring/status" + query, REMOTE_ADDR=ip,
                               **({"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}))

    def test_probes_are_open(self):
        self.client.logout()
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/readyz").json(), {"status": "ok"})
        with mock.patch.object(monitoring, "_pending_migrations", return_value=2):
            self.assertEqual(self.client.get("/readyz").status_code, 503)

    def test_token_and_allowlist(self):
        self.as_("admin")
        token = self.j("post", "/api/admin/monitoring/token")["token"]
        self.client.logout()
        self.assertEqual(self.status().status_code, 401)
        self.assertEqual(self.status("kmon_wrong").status_code, 401)
        self.assertEqual(self.status(token).status_code, 403)  # empty allowlist: nobody
        self.as_("admin")
        self.j("put", "/api/admin/settings", {"monitoring_allowlist": ["10.1.0.0/16", " ::1 "]})
        r = self.j("put", "/api/admin/settings", {"monitoring_allowlist": ["10.1.0.0/16", "intranet"]}, status=400)
        self.assertIn("intranet", r["fields"]["monitoring_allowlist"])
        self.client.logout()
        self.assertEqual(self.status(token, ip="10.2.0.1").status_code, 403)
        data = self.status(token).json()
        self.assertIn(data["status"], ("ok", "warn", "crit"))
        self.assertEqual({c["name"] for c in data["checks"]} >= {"database", "exporter"}, True)
        self.assertGreater(data["metrics"]["persons"] + data["metrics"]["companies"], -1)
        prtg = self.status(token, query="?format=prtg").json()["prtg"]
        self.assertEqual(prtg["result"][0]["channel"], "status")

    def test_check_states(self):
        s = Settings.get()
        by = lambda: {c["name"]: c for c in monitoring.checks(Settings.get())}
        self.assertEqual(by()["exporter"]["status"], "crit")  # never seen
        Settings.objects.filter(pk=1).update(exporter_seen_at=timezone.now())
        self.assertEqual(by()["exporter"]["status"], "ok")
        Settings.objects.filter(pk=1).update(exporter_seen_at=timezone.now() - timedelta(minutes=2.5 * s.export_interval_minutes))
        self.assertEqual(by()["exporter"]["status"], "warn")
        ExportProfile.objects.create(name="Telefonbuch", path="/export/x.csv", last_status="error", last_message="guard",
                                     last_run_at=timezone.now())
        self.assertEqual((by()["export:Telefonbuch"]["status"], by()["export:Telefonbuch"]["detail"]), ("crit", "guard"))
        Settings.objects.filter(pk=1).update(graph_enabled=True, graph_status={"at": timezone.now().isoformat(), "error": "401"})
        self.assertEqual(by()["outlook"]["status"], "crit")
        self.assertEqual(monitoring.collect()["status"], "crit")
        self.as_("admin")
        self.assertEqual(self.j("get", "/api/admin/monitoring/status")["status"], "crit")


class LogFormatTests(SimpleTestCase):
    def record(self, name="kartei.audit", level=logging.INFO, **extra):
        r = logging.LogRecord(name, level, __file__, 1, "hello %s", ("world",), None)
        r.__dict__.update(extra)
        return r

    def test_json_formatter(self):
        out = json.loads(logs.JsonFormatter().format(self.record(audit={"event": "login", "ip": "10.0.0.1"})))
        self.assertEqual((out["msg"], out["logger"], out["audit"]["event"]), ("hello world", "kartei.audit", "login"))

    def test_rfc5424_line_and_framing(self):
        rec = logs.record_dict(self.record(audit={"event": "login"}))
        line = syslog.line(rec, "local0").decode()
        self.assertTrue(line.startswith(f"<134>1 {rec['ts']} "), line)  # local0 (16) * 8 + info (6)
        self.assertIn(" kartei ", line)
        self.assertIn(" audit - {", line)
        self.assertEqual(json.loads(line.split(" - ", 1)[1])["audit"]["event"], "login")
        self.assertEqual(syslog.frame(b"abc", "tcp"), b"3 abc")
        self.assertEqual(syslog.frame(b"abc", "udp"), b"abc")

    def test_sender_filters_and_drops_when_full(self):
        sender = syslog.Sender()
        sender.cfg = {"enabled": True, "content": "audit"}
        self.assertTrue(sender.wants(self.record()))
        self.assertFalse(sender.wants(self.record(name="django", level=logging.ERROR)))
        sender.cfg["content"] = "audit_and_app"
        self.assertTrue(sender.wants(self.record(name="django", level=logging.ERROR)))
        self.assertFalse(sender.wants(self.record(name="django.request", level=logging.WARNING, status_code=404)))
        self.assertFalse(sender.wants(self.record(name="kartei.syslog", level=logging.ERROR)))
        sender.cfg["enabled"] = False
        self.assertFalse(sender.wants(self.record()))
        with mock.patch.object(syslog, "QUEUE_MAX", 2):
            small = syslog.Sender()
        for _ in range(5):
            small.put({})
        self.assertEqual(small.dropped, 3)


class SyslogSocketTests(SimpleTestCase):
    """send_test against real sockets on localhost: UDP, TCP (octet counting) and TLS (self-signed)."""
    def settings(self, protocol, port, ca=""):
        return Settings(syslog_host="127.0.0.1", syslog_port=port, syslog_protocol=protocol, syslog_ca_cert=ca,
                        syslog_tls_verify=bool(ca), syslog_facility="auth")

    def test_udp(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.bind(("127.0.0.1", 0))
        srv.settimeout(5)
        self.addCleanup(srv.close)
        self.assertIsNone(syslog.send_test(self.settings("udp", srv.getsockname()[1])))
        data = srv.recv(65535).decode()
        self.assertTrue(data.startswith("<38>1 "), data)  # auth (4) * 8 + info (6)

    def _tcp_server(self, wrap=None):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        srv.settimeout(5)
        self.addCleanup(srv.close)
        got = {}

        def accept():
            conn, _ = srv.accept()
            if wrap:
                conn = wrap(conn)
            with conn:
                got["data"] = conn.recv(65535)
        t = threading.Thread(target=accept)
        t.start()
        return srv.getsockname()[1], t, got

    def test_tcp(self):
        port, t, got = self._tcp_server()
        self.assertIsNone(syslog.send_test(self.settings("tcp", port)))
        t.join(5)
        size, _, rest = got["data"].partition(b" ")
        self.assertEqual(int(size), len(rest))

    def test_tls_with_own_ca_and_refused_port(self):
        import tempfile
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import datetime as dt
        import ipaddress
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "siem")])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(1).not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                .sign(key, hashes.SHA256()))
        pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as f:
            f.write(pem.encode() + key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(f.name)
        port, t, got = self._tcp_server(lambda c: ctx.wrap_socket(c, server_side=True))
        self.assertIsNone(syslog.send_test(self.settings("tls", port, ca=pem)))
        t.join(5)
        self.assertIn(b" kartei ", got["data"])
        # nothing listening: the error is reported, not raised
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        closed = free.getsockname()[1]
        free.close()
        self.assertTrue(syslog.send_test(self.settings("tcp", closed)))
        self.assertEqual(syslog.send_test(Settings(syslog_host="")), "syslog_no_host")
