"""The web app end to end, against a fake mailbox: no browser, no Google."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gmail_organizer import webapp
from tests.test_organizer import FakeClient, newsletter
from tests.test_rules import make_message

RULES = {
    "search": "in:inbox",
    "max_messages": 100,
    "allow_trash": False,
    "rules": [
        {
            "name": "newsletters",
            "match": {"is_list": True},
            "actions": {"add_labels": ["Newsletters"], "archive": True},
        }
    ],
}


class FakeState(webapp.AppState):
    """An AppState wired to a fake mailbox instead of the Google SDK."""

    def __init__(self, *args, mailbox, **kwargs):
        super().__init__(*args, **kwargs)
        self._fake = mailbox

    has_credentials = True
    is_connected = True

    def client(self):
        return self._fake

    def email(self):
        return "eu@exemplo.com"


@pytest.fixture()
def app(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    fake = FakeClient([newsletter("a"), newsletter("b"), make_message(message_id="c")])
    state = FakeState(
        str(rules_path),
        str(tmp_path / "cred.json"),
        str(tmp_path / "tok.json"),
        mailbox=fake,
    )

    handler = type("BoundHandler", (webapp.Handler,), {"state": state})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, payload=None, token=True):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(base + path, data=data, method="POST" if data else "GET")
        if data:
            request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("X-Organizer-Token", state.token)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        yield call, state, fake
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_index_embeds_a_fresh_token(app):
    call, state, _ = app
    status, payload = call("/api/status")
    assert status == 200
    assert payload["connected"] is True
    assert len(state.token) > 20


def test_mutating_requests_need_the_token(app):
    call, _, _ = app
    status, payload = call("/api/rules", RULES, token=False)
    assert status == 403
    assert "sessão" in payload["error"]


def test_saving_rules_writes_the_file(app):
    call, state, _ = app
    status, payload = call("/api/rules", RULES)
    assert status == 200
    assert payload["ok"] is True

    status, saved = call("/api/rules")
    assert saved["rules"][0]["name"] == "newsletters"
    assert "is_list: true" in open(state.rules_path, encoding="utf-8").read()


def test_invalid_rules_are_rejected_with_a_readable_message(app):
    call, _, _ = app
    bad = {"rules": [{"name": "Mau", "match": {"nao_existe": 1}, "actions": {"archive": True}}]}
    status, payload = call("/api/rules", bad)
    assert status == 400
    assert "unknown condition" in payload["error"]


def test_preview_changes_nothing(app):
    call, _, fake = app
    call("/api/rules", RULES)
    status, payload = call("/api/preview", {"rules": RULES})

    assert status == 200
    assert payload["scanned"] == 3
    assert payload["changed"] == 2
    assert {m["id"] for m in payload["messages"]} == {"a", "b"}
    assert payload["messages"][0]["add"] == ["Newsletters"]
    assert fake.modifications == []


def test_apply_only_touches_the_selected_messages(app):
    call, _, fake = app
    call("/api/rules", RULES)
    call("/api/preview", {"rules": RULES})

    status, payload = call("/api/apply", {"ids": ["a"]})
    assert status == 200
    assert payload["applied"] == 1
    assert payload["remaining"] == 1

    assert fake.created_labels == ["Newsletters"]
    ids, add, remove = fake.modifications[0]
    assert ids == ["a"]
    assert remove == ["INBOX"]


def test_apply_without_a_preview_is_refused(app):
    call, _, fake = app
    status, payload = call("/api/apply", {"ids": ["a"]})
    assert status == 400
    assert "Pré-visualizar" in payload["error"]
    assert fake.modifications == []


def test_credentials_upload_rejects_a_web_client(app):
    call, _, _ = app
    status, payload = call("/api/credentials", {"content": json.dumps({"web": {"client_id": "x"}})})
    assert status == 400
    assert "Desktop app" in payload["error"]
