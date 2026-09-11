"""Drive the real page in a real browser.

These caught a CSS bug that no amount of API testing would: a class setting
`display` silently beats the browser's own rule for the `hidden` attribute, so
the loading veil covered the page forever.

Skipped when Playwright is not installed — `pip install playwright`.
"""

import json
import threading
from http.server import ThreadingHTTPServer

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

from gmail_organizer import webapp  # noqa: E402
from tests.test_organizer import FakeClient  # noqa: E402
from tests.test_rules import make_message  # noqa: E402
from tests.test_webapp import RULES  # noqa: E402

CHROMIUM = "/opt/pw-browsers/chromium"


def newsletter(message_id):
    return make_message(
        message_id=message_id,
        sender=f"noticias{message_id}@jornal.pt",
        subject=f"Edição {message_id}",
        list_id="<noticias.jornal.pt>",
    )


class UIState(webapp.AppState):
    def __init__(self, *args, mailbox, connected, **kwargs):
        super().__init__(*args, **kwargs)
        self._fake = mailbox
        self._connected = connected

    @property
    def has_credentials(self):
        return self._connected

    @property
    def is_connected(self):
        return self._connected

    def client(self):
        return self._fake

    def email(self):
        return "eu@exemplo.com" if self._connected else None


@pytest.fixture()
def ui(tmp_path, request):
    connected = getattr(request, "param", True)
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(json.dumps(RULES), encoding="utf-8")  # YAML is a JSON superset

    fake = FakeClient([newsletter("a"), newsletter("b"), make_message(message_id="c")])
    state = UIState(
        str(rules_path),
        str(tmp_path / "cred.json"),
        str(tmp_path / "tok.json"),
        mailbox=fake,
        connected=connected,
    )
    handler = type("BoundHandler", (webapp.Handler,), {"state": state})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROMIUM)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(url)
        page.wait_for_load_state("networkidle")
        try:
            yield page, state, fake, errors
        finally:
            browser.close()
            httpd.shutdown()
            httpd.server_close()


@pytest.mark.parametrize("ui", [False, True], indirect=True)
def test_loading_veil_is_not_covering_the_page(ui):
    page, _, _, errors = ui
    assert errors == []
    assert page.locator("#blocker").is_visible() is False
    assert page.locator("#toast").is_visible() is False


@pytest.mark.parametrize("ui", [False], indirect=True)
def test_setup_is_shown_until_the_account_is_connected(ui):
    page, _, _, _ = ui
    assert page.locator("#setup").is_visible() is True
    assert page.locator("#app").is_visible() is False
    assert page.locator("#btn-connect").is_disabled() is True
    assert "por ligar" in page.locator("#account-chip").inner_text()


def test_connected_account_sees_the_rules(ui):
    page, _, _, _ = ui
    assert page.locator("#setup").is_visible() is False
    assert page.locator("#app").is_visible() is True
    assert page.locator("#account-chip").inner_text() == "eu@exemplo.com"
    assert page.locator(".rule").count() == 1
    assert "newsletters" in page.locator(".rule-name").inner_text()


def test_hidden_panels_only_appear_once_there_is_something_to_show(ui):
    page, _, _, _ = ui
    assert page.locator("#preview-summary").is_visible() is False
    assert page.locator("#preview-actions").is_visible() is False
    assert page.locator("#preview-empty").is_visible() is True


def test_preview_then_apply_only_the_ticked_messages(ui):
    page, _, fake, errors = ui

    page.click("#btn-preview")
    page.wait_for_selector("#preview-table tbody tr")
    assert page.locator("#blocker").is_visible() is False
    assert page.locator("#preview-table tbody tr").count() == 2
    assert page.locator("#preview-summary").is_visible() is True
    assert fake.modifications == []

    # Untick the second message; only the first should be touched.
    page.locator("#preview-table tbody tr").nth(1).locator("input").uncheck()
    assert "Aplicar a 1" in page.locator("#btn-apply").inner_text()

    page.on("dialog", lambda dialog: dialog.accept())
    page.click("#btn-apply")
    page.wait_for_selector("#preview-actions", state="hidden")

    assert len(fake.modifications) == 1
    ids, _, remove = fake.modifications[0]
    assert ids == ["a"]
    assert remove == ["INBOX"]
    assert errors == []


def test_rule_editor_round_trips_a_new_rule(ui):
    page, state, _, errors = ui

    page.click("#btn-new-rule")
    page.wait_for_selector("#rule-dialog[open]")
    page.fill("#rule-name", "Recibos")
    page.select_option(".condition select", "subject_contains")
    page.fill(".condition .value input", "fatura, recibo")
    page.fill("#act-add-labels", "Finanças")
    page.check("#act-archive")
    page.click("#rule-form button[type=submit]")

    page.wait_for_function("document.querySelectorAll('.rule').length === 2")
    saved = state.load_rules().to_data()["rules"][1]
    assert saved["name"] == "Recibos"
    assert saved["match"] == {"subject_contains": ["fatura", "recibo"]}
    assert saved["actions"] == {"add_labels": ["Finanças"], "archive": True}
    assert errors == []


def test_trash_needs_the_setting_turned_on_first(ui):
    page, _, _, _ = ui

    page.click("#btn-new-rule")
    page.fill("#rule-name", "Lixo")
    page.fill(".condition .value input", "spam@x.com")
    page.check("#act-trash")
    page.click("#rule-form button[type=submit]")

    assert page.locator("#rule-dialog[open]").count() == 1
    assert "Permitir enviar para o lixo" in page.locator("#rule-error").inner_text()
