"""Google sign-in: only verified Google Workspace accounts on the company
domain get in; the PIN keeps working as a backup."""

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from webapp import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    data, uploads = tmp_path / "data", tmp_path / "uploads"
    data.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(server, "DATA_DIR", str(data))
    monkeypatch.setattr(server, "UPLOADS", str(uploads))
    monkeypatch.setattr(server, "PROJECTS_FILE", str(data / "projects.json"))
    monkeypatch.setattr(server, "LEGACY_DATA_FILE", str(data / "visit.json"))
    monkeypatch.setattr(server, "GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(server, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(server, "GOOGLE_DOMAIN", "gfdseng.com")
    server._fails.clear()
    return server.app.test_client()


def _token(**claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{body}.sig"


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


def _google_says(monkeypatch, sent, **overrides):
    """Google's token endpoint answering with an ID token for these claims."""
    def post(url, data=None, timeout=None):
        assert url == server.GOOGLE_TOKEN_URL and data["client_secret"] == "test-secret"
        sent.update(data)
        nonce = overrides.pop("nonce", None) or _google_says.nonce
        claims = {"iss": "https://accounts.google.com", "aud": server.GOOGLE_CLIENT_ID,
                  "exp": time.time() + 600, "nonce": nonce, "email": "sarbic@gfdseng.com",
                  "email_verified": True, "hd": "gfdseng.com", "name": "Sean Arbic"}
        claims.update(overrides)
        return _Resp(200, {"id_token": _token(**claims)})
    monkeypatch.setattr(requests, "post", post)


def _start(client, nxt="/projects"):
    r = client.get(f"/auth/google?next={nxt}")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["Location"]).query)
    assert q["hd"] == ["gfdseng.com"] and q["client_id"] == [server.GOOGLE_CLIENT_ID]
    _google_says.nonce = q["nonce"][0]
    return q["state"][0]


def test_login_page_offers_google_and_the_pin(client):
    html = client.get("/login").get_data(as_text=True)
    assert "Sign in with Google" in html and "Use the PIN instead" in html


def test_company_account_gets_in_and_lands_where_it_was_going(client, monkeypatch):
    sent = {}
    _google_says(monkeypatch, sent)
    state = _start(client)
    r = client.get(f"/auth/google/callback?state={state}&code=abc")
    assert r.status_code == 302 and r.headers["Location"].endswith("/projects")
    assert sent["code"] == "abc" and sent["redirect_uri"].endswith("/auth/google/callback")
    assert client.get("/api/jobs").status_code == 200
    page = client.get("/settings").get_data(as_text=True)
    assert "Signed in as Sean Arbic (sarbic@gfdseng.com)" in page


@pytest.mark.parametrize("claims", [
    {"email": "someone@gmail.com", "hd": None},                 # personal Gmail
    {"email": "x@otherfirm.com", "hd": "otherfirm.com"},         # another company's Workspace
    {"email_verified": False},
    {"aud": "someone-elses-client"},
    {"exp": time.time() - 10},
    {"nonce": "replayed"},
])
def test_others_are_turned_away(client, monkeypatch, claims):
    _google_says(monkeypatch, {}, **claims)
    state = _start(client)
    r = client.get(f"/auth/google/callback?state={state}&code=abc")
    assert r.status_code in (400, 403)
    assert client.get("/api/jobs").status_code == 401


def test_a_forged_or_stale_callback_is_refused(client, monkeypatch):
    _google_says(monkeypatch, {})
    _start(client)
    assert client.get("/auth/google/callback?state=wrong&code=abc").status_code == 400
    assert client.get("/api/jobs").status_code == 401


def test_next_never_leaves_the_site(client, monkeypatch):
    _google_says(monkeypatch, {})
    state = _start(client, nxt="//evil.example.com/x")
    r = client.get(f"/auth/google/callback?state={state}&code=abc")
    assert urlparse(r.headers["Location"]).path == "/"
    r = client.post("/login?next=https://evil.example.com", data={"pin": server.PIN})
    assert urlparse(r.headers["Location"]).netloc in ("", "localhost")


def test_pin_still_works_as_a_backup(client):
    assert client.post("/login", data={"pin": server.PIN}).status_code == 302
    assert client.get("/api/jobs").status_code == 200
    assert "Signed in with the PIN" in client.get("/settings").get_data(as_text=True)


def test_without_google_set_up_the_login_is_the_pin(client, monkeypatch):
    monkeypatch.setattr(server, "GOOGLE_CLIENT_ID", "")
    html = client.get("/login").get_data(as_text=True)
    assert "Sign in with Google" not in html and 'name=pin' in html
    assert client.get("/auth/google").headers["Location"].endswith("/login")
