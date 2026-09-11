"""A small local web app: the whole thing is driven by clicking, not typing.

The server binds to 127.0.0.1 only and every mutating request must carry the
session token embedded in the page, so no other page in the browser can drive
the user's mailbox behind their back.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .auth import DEFAULT_CREDENTIALS, DEFAULT_TOKEN, build_service
from .organizer import Change, Organizer
from .rules import RuleError, RuleSet

WEB_ROOT = Path(__file__).parent / "web"
EXAMPLE_RULES = Path(__file__).parent.parent / "rules.example.yaml"


class AppError(Exception):
    """An error worth showing to the user as-is."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class AppState:
    """Everything the UI needs, kept in memory for the life of the process."""

    def __init__(self, rules_path: str, credentials_path: str, token_path: str) -> None:
        self.rules_path = rules_path
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self._client = None
        self._email: str | None = None
        self.preview: dict[str, Change] = {}

    # --- rules ------------------------------------------------------------

    def load_rules(self) -> RuleSet:
        if not os.path.exists(self.rules_path):
            if EXAMPLE_RULES.exists():
                return RuleSet.load(str(EXAMPLE_RULES))
            return RuleSet(rules=[])
        return RuleSet.load(self.rules_path)

    def save_rules(self, data: dict) -> RuleSet:
        ruleset = RuleSet.from_data(data)
        ruleset.save(self.rules_path)
        return ruleset

    # --- gmail ------------------------------------------------------------

    @property
    def has_credentials(self) -> bool:
        return os.path.exists(self.credentials_path)

    @property
    def is_connected(self) -> bool:
        return os.path.exists(self.token_path)

    def client(self):
        from .gmail_client import GmailClient

        if self._client is None:
            if not self.has_credentials:
                raise AppError(
                    "Falta o ficheiro credentials.json. Carrega-o no primeiro passo.", 409
                )
            service = build_service(self.credentials_path, self.token_path)
            self._client = GmailClient(service)
        return self._client

    def email(self) -> str | None:
        if self._email is None and self.is_connected:
            try:
                profile = self.client().service.users().getProfile(userId="me").execute()
                self._email = profile.get("emailAddress")
            except Exception:  # noqa: BLE001 - the UI just shows "ligado"
                return None
        return self._email

    def disconnect(self) -> None:
        self._client = None
        self._email = None
        if os.path.exists(self.token_path):
            os.remove(self.token_path)


# --- serialization ---------------------------------------------------------


def change_to_json(change: Change) -> dict:
    message = change.message
    return {
        "id": message.id,
        "from": message.header("from") or message.sender,
        "subject": message.subject or "(sem assunto)",
        "date": message.internal_date.isoformat() if message.internal_date else None,
        "add": change.add_names,
        "remove": change.remove_names,
        "trash": change.trash,
        "rules": change.matched_rules,
    }


# --- request handling ------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "GmailOrganizer"
    state: AppState  # injected by serve()

    def log_message(self, fmt, *args):  # quieter console
        pass

    # -- plumbing ----------------------------------------------------------

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AppError(f"pedido inválido: {exc}") from exc

    def _check_token(self) -> None:
        if self.headers.get("X-Organizer-Token") != self.state.token:
            raise AppError("sessão inválida — recarrega a página", 403)

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        body = path.read_bytes()
        if path.name == "index.html":
            body = body.replace(b"__TOKEN__", self.state.token.encode())
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            if route == "/":
                self._serve_file(WEB_ROOT / "index.html")
            elif route.startswith("/static/"):
                name = os.path.basename(route)
                self._serve_file(WEB_ROOT / name)
            elif route == "/api/status":
                self._send_json(self._status())
            elif route == "/api/rules":
                self._send_json(self.state.load_rules().to_data())
            elif route == "/api/labels":
                self._check_token()
                self._send_json({"labels": sorted(self.state.client().labels())})
            else:
                self._send_json({"error": "not found"}, 404)
        except AppError as exc:
            self._send_json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            self._check_token()
            if route == "/api/credentials":
                self._send_json(self._save_credentials())
            elif route == "/api/connect":
                self._send_json(self._connect())
            elif route == "/api/disconnect":
                self.state.disconnect()
                self._send_json(self._status())
            elif route == "/api/rules":
                self._send_json(self._save_rules())
            elif route == "/api/preview":
                self._send_json(self._preview())
            elif route == "/api/apply":
                self._send_json(self._apply())
            elif route == "/api/quit":
                self._send_json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._send_json({"error": "not found"}, 404)
        except (AppError, RuleError) as exc:
            status = exc.status if isinstance(exc, AppError) else 400
            self._send_json({"error": str(exc)}, status)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    # -- handlers ----------------------------------------------------------

    def _status(self) -> dict:
        state = self.state
        return {
            "hasCredentials": state.has_credentials,
            "connected": state.is_connected,
            "email": state.email() if state.is_connected else None,
            "rulesPath": os.path.abspath(state.rules_path),
            "rulesFileExists": os.path.exists(state.rules_path),
        }

    def _save_credentials(self) -> dict:
        payload = self._read_json()
        content = payload.get("content")
        if not content:
            raise AppError("ficheiro vazio")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            raise AppError("isso não é um ficheiro JSON válido") from None
        if not ({"installed", "web"} & set(parsed)):
            raise AppError(
                "esse JSON não parece um OAuth client ID. Escolhe o tipo "
                "'Desktop app' na consola da Google e descarrega esse ficheiro."
            )
        if "web" in parsed and "installed" not in parsed:
            raise AppError(
                "esse cliente OAuth é do tipo 'Web application'. Cria um do tipo "
                "'Desktop app' — é esse que funciona aqui."
            )
        with open(self.state.credentials_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(self.state.credentials_path, 0o600)
        return self._status()

    def _connect(self) -> dict:
        with self.state.lock:
            self.state._client = None
            self.state._email = None
            self.state.client()  # triggers the browser consent screen
        return self._status()

    def _save_rules(self) -> dict:
        data = self._read_json()
        ruleset = self.state.save_rules(data)
        return {"ok": True, "rules": ruleset.to_data(), "path": os.path.abspath(self.state.rules_path)}

    def _preview(self) -> dict:
        payload = self._read_json()
        ruleset = RuleSet.from_data(payload.get("rules") or self.state.load_rules().to_data())
        if payload.get("search"):
            ruleset.search = str(payload["search"])
        limit = int(payload.get("limit") or ruleset.max_messages)

        with self.state.lock:
            organizer = Organizer(self.state.client(), ruleset, dry_run=True)
            report = organizer.run(now=datetime.now(tz=timezone.utc), limit=limit)
            self.state.preview = {change.message.id: change for change in report.changes}

        return {
            "scanned": report.scanned,
            "changed": report.changed,
            "trashed": report.trashed,
            "search": ruleset.search,
            "perRule": [{"name": name, "count": count} for name, count in report.per_rule.most_common()],
            "messages": [change_to_json(change) for change in report.changes],
        }

    def _apply(self) -> dict:
        payload = self._read_json()
        wanted = payload.get("ids")
        if not self.state.preview:
            raise AppError("não há nada pré-visualizado — carrega em Pré-visualizar primeiro")

        ids = list(self.state.preview) if wanted is None else [i for i in wanted if i in self.state.preview]
        if not ids:
            raise AppError("não selecionaste nenhuma mensagem")

        ruleset = self.state.load_rules()
        with self.state.lock:
            organizer = Organizer(self.state.client(), ruleset, dry_run=False)
            changes = [self.state.preview[i] for i in ids]
            organizer.apply(changes)
            applied = len(changes)
            for message_id in ids:
                self.state.preview.pop(message_id, None)

        return {"applied": applied, "remaining": len(self.state.preview)}


def serve(
    rules_path: str = "rules.yaml",
    credentials_path: str = DEFAULT_CREDENTIALS,
    token_path: str = DEFAULT_TOKEN,
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    state = AppState(rules_path, credentials_path, token_path)
    handler = type("BoundHandler", (Handler,), {"state": state})

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    print(f"Gmail Organizer a correr em {url}")
    print("Fecha esta janela (ou Ctrl+C) para desligar.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("Desligado.")


if __name__ == "__main__":
    serve()
