"""Thin wrapper over the Gmail REST API: search, hydrate, batch-modify."""

from __future__ import annotations

import time
from typing import Iterable, Iterator

from googleapiclient.errors import HttpError

from .message import Message

METADATA_HEADERS = [
    "From",
    "To",
    "Cc",
    "Subject",
    "Date",
    "List-Id",
    "List-Unsubscribe",
]

# Gmail rejects batches larger than this for messages.batchModify.
MODIFY_BATCH_SIZE = 1000
GET_BATCH_SIZE = 50
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


def _with_retry(request, attempts: int = 5):
    """Gmail rate-limits aggressively; back off instead of giving up."""
    delay = 1.0
    for attempt in range(attempts):
        try:
            return request.execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status not in RETRYABLE_STATUS or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


class GmailClient:
    def __init__(self, service, user_id: str = "me") -> None:
        self.service = service
        self.user_id = user_id
        self._label_cache: dict[str, str] | None = None

    # --- labels -----------------------------------------------------------

    def labels(self) -> dict[str, str]:
        """Map of label name -> label id, cached for the run."""
        if self._label_cache is None:
            response = _with_retry(self.service.users().labels().list(userId=self.user_id))
            self._label_cache = {item["name"]: item["id"] for item in response.get("labels", [])}
        return self._label_cache

    def ensure_label(self, name: str) -> str:
        """Return the id of a label, creating it (and its parents) if needed."""
        labels = self.labels()
        if name in labels:
            return labels[name]

        # "Work/Clients/Acme" needs "Work" and "Work/Clients" to exist first.
        parts = name.split("/")
        label_id = ""
        for depth in range(1, len(parts) + 1):
            path = "/".join(parts[:depth])
            if path in labels:
                label_id = labels[path]
                continue
            created = _with_retry(
                self.service.users()
                .labels()
                .create(
                    userId=self.user_id,
                    body={
                        "name": path,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
            )
            labels[path] = created["id"]
            label_id = created["id"]
        return label_id

    def resolve_label(self, name: str) -> str | None:
        """Label name or system id -> id, without creating anything."""
        labels = self.labels()
        if name in labels:
            return labels[name]
        if name in labels.values():
            return name
        return None

    # --- messages ---------------------------------------------------------

    def search_ids(self, query: str, limit: int) -> list[str]:
        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            response = _with_retry(
                self.service.users()
                .messages()
                .list(
                    userId=self.user_id,
                    q=query,
                    maxResults=min(500, limit - len(ids)),
                    pageToken=page_token,
                )
            )
            ids.extend(item["id"] for item in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return ids[:limit]

    def hydrate(self, message_ids: Iterable[str]) -> Iterator[Message]:
        """Fetch metadata for each id, in batches, yielding Message objects."""
        ids = list(message_ids)
        for start in range(0, len(ids), GET_BATCH_SIZE):
            chunk = ids[start : start + GET_BATCH_SIZE]
            collected: list[Message] = []
            errors: list[Exception] = []

            def callback(_request_id, response, exception):
                if exception is not None:
                    errors.append(exception)
                    return
                collected.append(Message.from_api(response))

            batch = self.service.new_batch_http_request(callback=callback)
            for message_id in chunk:
                batch.add(
                    self.service.users()
                    .messages()
                    .get(
                        userId=self.user_id,
                        id=message_id,
                        format="metadata",
                        metadataHeaders=METADATA_HEADERS,
                    )
                )
            batch.execute()
            if errors and not collected:
                raise errors[0]
            yield from collected

    def batch_modify(
        self,
        message_ids: list[str],
        add_label_ids: list[str],
        remove_label_ids: list[str],
    ) -> None:
        if not message_ids or not (add_label_ids or remove_label_ids):
            return
        for start in range(0, len(message_ids), MODIFY_BATCH_SIZE):
            chunk = message_ids[start : start + MODIFY_BATCH_SIZE]
            _with_retry(
                self.service.users()
                .messages()
                .batchModify(
                    userId=self.user_id,
                    body={
                        "ids": chunk,
                        "addLabelIds": add_label_ids,
                        "removeLabelIds": remove_label_ids,
                    },
                )
            )

    def trash(self, message_ids: list[str]) -> None:
        for message_id in message_ids:
            _with_retry(self.service.users().messages().trash(userId=self.user_id, id=message_id))
