"""Sign-up notification e-mail: a new access request mails ACCESS_REQUEST_NOTIFY_TO through the configured SMTP server;
without SMTP, or with the server down, the sign-up still succeeds. Uses a local capturing SMTP server - nothing is sent
anywhere."""
import asyncore
import email
import email.policy
import smtpd
import socket
import threading
import time
import warnings

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import signup as signup_module
from app.database import SessionLocal
from app.main import app
from app.services.mailer import send_mail

PW = "Kestrel-Harbour-2026x"


class Capture(smtpd.SMTPServer):
    def __init__(self, port):
        super().__init__(("127.0.0.1", port), None, decode_data=False)
        self.messages = []

    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        self.messages.append({"from": mailfrom, "to": rcpttos, "msg": email.message_from_bytes(data, policy=email.policy.default)})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def smtp():
    warnings.simplefilter("ignore", DeprecationWarning)
    server = Capture(free_port())
    t = threading.Thread(target=asyncore.loop, kwargs={"timeout": 0.1}, daemon=True)
    t.start()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def cleanup():
    signup_module._recent.clear()  # the per-IP sign-up limit is process-wide
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM battery_users.access_request WHERE email LIKE 'pytest.mail.%'"))
        db.execute(text("DELETE FROM battery_users.auth_audit WHERE email LIKE 'pytest.mail.%'"))
        db.commit()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def signup(client, who: str):
    return client.post("/api/auth/signup", json={
        "full_name": "Pytest <Mail> User", "email": f"pytest.mail.{who}@bess.local", "organisation": "QA & Test",
        "reason": "Needs read access to the\nfleet dashboards for testing.", "password": PW})


def configure(monkeypatch, port):
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(port))
    monkeypatch.setenv("SMTP_SECURITY", "none")
    monkeypatch.setenv("SMTP_FROM", "bess-noreply@bess.local")
    monkeypatch.setenv("ACCESS_REQUEST_NOTIFY_TO", "reviewer.one@bess.local; reviewer.two@bess.local")
    monkeypatch.setenv("APP_BASE_URL", "https://bess.example.test/")


def test_signup_mails_the_configured_reviewers(client, smtp, monkeypatch):
    configure(monkeypatch, smtp.socket.getsockname()[1])
    r = signup(client, "ok")
    assert r.status_code == 202, r.text
    for _ in range(50):
        if smtp.messages:
            break
        time.sleep(0.1)
    assert len(smtp.messages) == 1
    m = smtp.messages[0]
    assert sorted(m["to"]) == ["reviewer.one@bess.local", "reviewer.two@bess.local"]
    assert m["from"] == "bess-noreply@bess.local"
    msg = m["msg"]
    assert msg["Subject"] == "BESS access request: Pytest <Mail> User"
    plain = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    assert "pytest.mail.ok@bess.local" in plain and "QA & Test" in plain and "fleet dashboards" in plain
    assert "https://bess.example.test/admin/access-requests" in plain
    assert "Pytest &lt;Mail&gt; User" in html and "<Mail>" not in html  # user text is escaped in the HTML part
    assert PW not in plain and PW not in html  # never the password


def test_signup_works_without_smtp(client, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "")
    assert signup(client, "nosmtp").status_code == 202
    assert send_mail(["x@bess.local"], "s", "t") is False


def test_signup_works_when_the_mail_server_is_down(client, monkeypatch):
    configure(monkeypatch, free_port())  # nothing listens there
    monkeypatch.setenv("SMTP_TIMEOUT_S", "2")
    assert signup(client, "down").status_code == 202
    with SessionLocal() as db:
        assert db.execute(text("SELECT status FROM battery_users.access_request WHERE email = 'pytest.mail.down@bess.local'")
                          ).scalar() == "PENDING"
