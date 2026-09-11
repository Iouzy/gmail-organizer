"""OAuth for a desktop app: one browser consent, then a cached refresh token."""

from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

DEFAULT_CREDENTIALS = "credentials.json"
DEFAULT_TOKEN = "token.json"


def get_credentials(
    credentials_path: str = DEFAULT_CREDENTIALS,
    token_path: str = DEFAULT_TOKEN,
) -> Credentials:
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"{credentials_path} not found. Create an OAuth client ID of type "
                "'Desktop app' in the Google Cloud console, enable the Gmail API, "
                "and download the JSON to that path."
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        creds = flow.run_local_server(port=0)

    with open(token_path, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    os.chmod(token_path, 0o600)
    return creds


def build_service(
    credentials_path: str = DEFAULT_CREDENTIALS,
    token_path: str = DEFAULT_TOKEN,
):
    creds = get_credentials(credentials_path, token_path)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
