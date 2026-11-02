"""Security hardening: proxy password encrypted and never synced, plain-text secrets
wiped from the file, salted folder passwords, {#http} blocked from private hosts,
single instance."""
import hashlib
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from phraseforge import net
from phraseforge.cloud.sync import CloudSync, FolderRemote
from phraseforge.db import SECRET_SETTINGS, Store, hash_password, needs_rehash, verify_password
from phraseforge.models import Phrase

KEY = "sk-test-0123456789abcdefSECRET"
PROXY_PW = "pr0xyPW!-test"
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


def _raw(store, key):
    return store.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0]


# ---------------------------------------------------------------- secrets
def test_proxy_password_is_a_secret():
    assert "net.proxy_password" in SECRET_SETTINGS


@windows_only
def test_proxy_password_is_encrypted_in_db():
    s = Store(":memory:")
    s.set_setting("net.proxy_password", PROXY_PW)
    assert _raw(s, "net.proxy_password").startswith("dpapi:") and PROXY_PW not in _raw(s, "net.proxy_password")
    assert s.setting("net.proxy_password") == PROXY_PW
    assert s.settings()["net.proxy_password"] == PROXY_PW


@windows_only
def test_plaintext_secrets_are_sealed_and_erased_from_the_file(tmp_path):
    db = tmp_path / "phrases.db"
    Store(db).close()
    con = sqlite3.connect(db)          # a database written by an older version
    with con:
        con.execute("UPDATE settings SET value=? WHERE key='ai.anthropic_key'", (KEY,))
        con.execute("INSERT OR REPLACE INTO settings VALUES ('net.proxy_password', ?)", (PROXY_PW,))
    con.close()
    s = Store(db)
    assert s.setting("ai.anthropic_key") == KEY and s.setting("net.proxy_password") == PROXY_PW
    assert _raw(s, "ai.anthropic_key").startswith("dpapi:") and _raw(s, "net.proxy_password").startswith("dpapi:")
    s.close()
    for f in tmp_path.iterdir():                      # db, -wal, -shm: no plain value left anywhere
        data = f.read_bytes()
        assert KEY.encode() not in data and PROXY_PW.encode() not in data, f.name


@windows_only
def test_restoring_an_old_backup_seals_its_secrets(tmp_path):
    old = tmp_path / "old.db"
    Store(old).close()
    con = sqlite3.connect(old)
    with con:
        con.execute("UPDATE settings SET value=? WHERE key='ai.openai_key'", (KEY,))
    con.close()
    s = Store(tmp_path / "live.db")
    s.restore_from(old)
    assert _raw(s, "ai.openai_key").startswith("dpapi:") and s.setting("ai.openai_key") == KEY


@windows_only
def test_proxy_password_never_leaves_the_pc_through_sync(tmp_path):
    remote = tmp_path / "cloud"
    a, b = Store(tmp_path / "A.db"), Store(tmp_path / "B.db")
    sa, sb = CloudSync(a, FolderRemote(remote), "A"), CloudSync(b, FolderRemote(remote), "B")
    a.set_setting("net.proxy_password", PROXY_PW)
    b.set_setting("net.proxy_password", "b-own-pw")
    a.add_phrase(Phrase("P", "p"))
    assert sa.sync().action == "pushed"
    sa.backup_now()
    for f in remote.rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            assert PROXY_PW.encode() not in data and b"dpapi:" not in data, f.name
    r = sb.sync()
    assert r.action == "pulled"
    sb.apply_pull(r.pulled_file, r.remote_rev)
    assert [p.description for p in b.phrases()] == ["P"]
    assert b.setting("net.proxy_password") == "b-own-pw"          # B keeps its own


# ---------------------------------------------------------------- folder passwords
def test_password_hash_is_salted_scrypt():
    h1, h2 = hash_password("pw"), hash_password("pw")
    assert h1.startswith("scrypt$") and h1 != h2
    assert verify_password("pw", h1) and not verify_password("PW", h1)
    assert not needs_rehash(h1)
    assert hash_password("") == "" and verify_password("anything", "")


def test_old_sha256_hash_verifies_and_needs_rehash():
    legacy = hashlib.sha256(b"phraseforge:pw").hexdigest()
    assert verify_password("pw", legacy) and not verify_password("x", legacy)
    assert needs_rehash(legacy)
    assert not verify_password("pw", "scrypt$broken")


# ---------------------------------------------------------------- {#http} private hosts
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.1.2.3", "192.168.1.1", "172.16.0.5",
                                  "169.254.169.254", "::1", "0.0.0.0", "[::ffff:127.0.0.1]"])
def test_private_hosts_detected(host):
    assert net.is_private_host(host)


def test_public_ip_is_not_private():
    assert not net.is_private_host("8.8.8.8")


def test_http_macro_blocks_private_hosts_by_default():
    net.configure({})
    with pytest.raises(net.NetError, match="blocked"):
        net.http_request("GET", "http://127.0.0.1:9/")


def _mock_client(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(net.httpx, "Client",
                        lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler)}))


def test_http_redirect_to_private_host_is_blocked(monkeypatch):
    """A public URL that redirects to a LAN address is stopped at the redirect."""
    net.configure({})
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "8.8.8.8":
            return httpx.Response(302, headers={"Location": "http://192.168.0.1/admin"})
        return httpx.Response(200, text="LAN")

    _mock_client(monkeypatch, handler)
    with pytest.raises(net.NetError, match="192.168.0.1"):
        net.http_request("GET", "http://8.8.8.8/")
    assert seen == ["8.8.8.8"]


def test_http_private_hosts_allowed_by_setting(monkeypatch):
    net.configure({"net.allow_private_hosts": "1"})
    _mock_client(monkeypatch, lambda r: httpx.Response(200, text="ok"))
    try:
        assert net.http_request("GET", "http://127.0.0.1/") == "ok"
    finally:
        net.configure({})


class _LocalServer:
    """A tiny HTTP server on 127.0.0.1 that records the Host header of each request."""

    def __init__(self):
        import http.server
        import threading
        hosts = self.hosts = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hosts.append(self.headers.get("Host"))
                body = b"local secret"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def local_server():
    srv = _LocalServer()
    yield srv
    srv.close()


def _rebinding_dns(monkeypatch, name, first, then):
    """getaddrinfo answers `first` for `name` on the first lookup and `then` afterwards."""
    real = net.socket.getaddrinfo
    calls = []

    def fake(host, port, *a, **kw):
        if host != name:
            return real(host, port, *a, **kw)
        calls.append(host)
        ip = first if len(calls) == 1 else then
        return [(net.socket.AF_INET, net.socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(net.socket, "getaddrinfo", fake)
    return calls


def test_dns_rebinding_cannot_reach_this_pc(monkeypatch, local_server):
    """G-34 / FR-SEC-06: the name check sees a public address, the second lookup answers
    127.0.0.1. The request must be stopped and the local server must see nothing."""
    net.configure({})
    calls = _rebinding_dns(monkeypatch, "rebind.example", "93.184.216.34", "127.0.0.1")
    with pytest.raises(net.NetError, match="blocked"):
        net.http_request("GET", f"http://rebind.example:{local_server.port}/", timeout_s=5)
    assert local_server.hosts == []
    assert len(calls) == 2            # name check, then the lookup the connection really uses


def test_connection_uses_the_checked_address_without_a_new_lookup(local_server):
    """The pinned transport connects to the address its resolver returned (never resolving
    again) and still sends the original host name."""
    looked_up = []

    def resolve(host, port):
        looked_up.append(host)
        return [(net.socket.AF_INET, net.socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    with httpx.Client(transport=net.pinned_transport(resolve=resolve), timeout=5) as c:
        r = c.get(f"http://checked.example:{local_server.port}/")
    assert r.text == "local secret"
    assert looked_up == ["checked.example"]
    assert local_server.hosts == [f"checked.example:{local_server.port}"]


def _self_signed(tmp_path, name):
    crypto = pytest.importorskip("cryptography")  # noqa: F841
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cf, kf = tmp_path / "cert.pem", tmp_path / "key.pem"
    cf.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kf.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    return cf, kf


def test_https_still_checks_the_certificate_against_the_host_name(tmp_path, local_server):
    """Connecting to a pinned IP must not weaken TLS: the certificate is checked against the
    URL's host name, so the right name passes and a wrong name fails."""
    import ssl
    cf, kf = _self_signed(tmp_path, "pinned.example")
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    server_ctx.load_cert_chain(cf, kf)
    local_server.httpd.socket = server_ctx.wrap_socket(local_server.httpd.socket, server_side=True)
    client_ctx = ssl.create_default_context(cafile=str(cf))

    def resolve(host, port):
        return [(net.socket.AF_INET, net.socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    with httpx.Client(transport=net.pinned_transport(resolve=resolve, verify=client_ctx), timeout=5) as c:
        assert c.get(f"https://pinned.example:{local_server.port}/").text == "local secret"
        with pytest.raises(httpx.ConnectError):
            c.get(f"https://other.example:{local_server.port}/")


def test_public_addresses_rejects_any_private_answer(monkeypatch):
    def fake(host, port, *a, **kw):
        return [(net.socket.AF_INET, net.socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                (net.socket.AF_INET, net.socket.SOCK_STREAM, 6, "", ("10.0.0.1", port))]
    monkeypatch.setattr(net.socket, "getaddrinfo", fake)
    with pytest.raises(net.NetError, match="blocked"):
        net.public_addresses("mixed.example", 80)


def test_allow_private_setting_also_lifts_the_pinned_check(local_server):
    net.configure({"net.allow_private_hosts": "1"})
    try:
        assert net.http_request("GET", f"http://127.0.0.1:{local_server.port}/", timeout_s=5) == "local secret"
    finally:
        net.configure({})


# ---------------------------------------------------------------- single instance
def test_single_instance_forwards_argv(tmp_path):
    from PySide6.QtCore import QCoreApplication, QDeadlineTimer
    from PySide6.QtWidgets import QApplication
    assert QApplication.instance() or QApplication([])
    from phraseforge.single_instance import SingleInstance, instance_name
    name = instance_name(str(tmp_path))
    assert name != instance_name(str(tmp_path / "other"))
    first = SingleInstance(name)
    assert first.acquire()
    got = []
    first.message.connect(got.append)
    # the later launch is a real second process, as in practice
    code = ("import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
            "from phraseforge.single_instance import SingleInstance; s = SingleInstance(sys.argv[1]);"
            "sys.exit(10 if s.acquire() else (0 if s.forward(['--minimized', 'x']) else 11))")
    child = subprocess.Popen([sys.executable, "-c", code, name], cwd=str(Path(__file__).parent.parent))
    try:
        timer = QDeadlineTimer(15000)
        while (not got or child.poll() is None) and not timer.hasExpired():
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert child.wait(5) == 0
        assert got == [["--minimized", "x"]]
    finally:
        if child.poll() is None:
            child.kill()
        first.release()
    again = SingleInstance(name)          # released: a new process may start
    assert again.acquire()
    again.release()


_DESTROY_SCENARIO = r'''
import os, subprocess, sys, time
from PySide6.QtCore import QCoreApplication, QDeadlineTimer
app = QCoreApplication([])
from phraseforge.single_instance import SingleInstance

def run(name, release):
    first = SingleInstance(name)
    assert first.acquire()
    got = []
    first.message.connect(got.append)
    code = ("import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
            "from phraseforge.single_instance import SingleInstance; s = SingleInstance(sys.argv[1]);"
            "sys.exit(10 if s.acquire() else (0 if s.forward(['x']) else 11))")
    child = subprocess.Popen([sys.executable, "-c", code, name])
    t = QDeadlineTimer(15000)
    while (not got or child.poll() is None) and not t.hasExpired():
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert child.wait(5) == 0 and got == [["x"]], (child.returncode, got)
    if release:
        first.release()

for i, release in enumerate((False, True)):
    run(sys.argv[1] + str(i), release)          # the instance object is gone after this call
    for _ in range(20):
        QCoreApplication.processEvents()        # crashed here before the fix
        time.sleep(0.01)
print("ok")
'''


def test_destroyed_single_instance_leaves_nothing_that_crashes_later(tmp_path):
    """Regression: after a later launch connected, deleting the SingleInstance (with or
    without release()) left a queued socket delete with Python slots attached; the next
    event-loop pass crashed the process. In the test suite that was an access violation
    in an unrelated later test (test_sticky_notes_ui) on the Windows runner."""
    from phraseforge.single_instance import instance_name
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", _DESTROY_SCENARIO, instance_name(str(tmp_path))],
                       cwd=str(Path(__file__).parent.parent), env=env, capture_output=True, text=True,
                       timeout=90)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), (r.returncode, r.stdout[-500:], r.stderr[-2000:])
