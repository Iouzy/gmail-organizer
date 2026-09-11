"""Normalized view of a Gmail message, built from the API metadata format."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import getaddresses

_ADDRESS_HEADERS = ("from", "to", "cc", "bcc", "reply-to")


def _addresses(raw: str) -> list[str]:
    return [addr.lower() for _, addr in getaddresses([raw or ""]) if addr]


@dataclass
class Message:
    """Everything the rule engine needs to decide what to do with a message."""

    id: str
    thread_id: str
    label_ids: set[str] = field(default_factory=set)
    headers: dict[str, str] = field(default_factory=dict)
    size_estimate: int = 0
    internal_date: datetime | None = None

    @classmethod
    def from_api(cls, payload: dict) -> "Message":
        headers = {}
        for header in payload.get("payload", {}).get("headers", []):
            name = header.get("name", "").lower()
            # Gmail can repeat headers; the first one wins, like most clients.
            headers.setdefault(name, header.get("value", ""))

        internal_date = None
        raw_date = payload.get("internalDate")
        if raw_date:
            internal_date = datetime.fromtimestamp(int(raw_date) / 1000, tz=timezone.utc)

        return cls(
            id=payload["id"],
            thread_id=payload.get("threadId", payload["id"]),
            label_ids=set(payload.get("labelIds", [])),
            headers=headers,
            size_estimate=int(payload.get("sizeEstimate", 0)),
            internal_date=internal_date,
        )

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    def addresses(self, name: str) -> list[str]:
        if name.lower() not in _ADDRESS_HEADERS:
            raise ValueError(f"{name} is not an address header")
        return _addresses(self.header(name))

    @property
    def sender(self) -> str:
        addrs = self.addresses("from")
        return addrs[0] if addrs else ""

    @property
    def subject(self) -> str:
        return self.header("subject")

    @property
    def list_id(self) -> str:
        return self.header("list-id").lower()

    @property
    def is_unread(self) -> bool:
        return "UNREAD" in self.label_ids

    @property
    def is_starred(self) -> bool:
        return "STARRED" in self.label_ids

    @property
    def in_inbox(self) -> bool:
        return "INBOX" in self.label_ids

    @property
    def has_list_header(self) -> bool:
        return bool(self.list_id or self.header("list-unsubscribe"))

    def age_days(self, now: datetime | None = None) -> float | None:
        if self.internal_date is None:
            return None
        now = now or datetime.now(tz=timezone.utc)
        return (now - self.internal_date).total_seconds() / 86400


SIZE_UNITS = {"": 1, "b": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2}
_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")


def parse_size(value: int | str) -> int:
    """Turn "5M", "500k" or 1024 into a byte count."""
    if isinstance(value, int):
        return value
    match = _SIZE_RE.match(str(value))
    if not match:
        raise ValueError(f"invalid size: {value!r}")
    amount, unit = match.groups()
    unit = unit.lower()
    if unit not in SIZE_UNITS:
        raise ValueError(f"unknown size unit in {value!r}")
    return int(float(amount) * SIZE_UNITS[unit])
