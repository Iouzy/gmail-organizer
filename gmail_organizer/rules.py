"""Deterministic rule engine: YAML in, label decisions out. No model involved."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

import yaml

from .message import Message, parse_size

SYSTEM_LABELS = {
    "INBOX",
    "UNREAD",
    "STARRED",
    "IMPORTANT",
    "SPAM",
    "TRASH",
    "SENT",
    "DRAFT",
    "CATEGORY_PERSONAL",
    "CATEGORY_SOCIAL",
    "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES",
    "CATEGORY_FORUMS",
}

KNOWN_CONDITIONS = {
    "from",
    "not_from",
    "to",
    "cc",
    "from_regex",
    "subject_contains",
    "subject_regex",
    "list_id",
    "is_list",
    "has_label",
    "not_label",
    "is_unread",
    "is_starred",
    "in_inbox",
    "older_than_days",
    "newer_than_days",
    "larger_than",
    "any_of",
}

KNOWN_ACTIONS = {
    "add_labels",
    "remove_labels",
    "archive",
    "mark_read",
    "mark_unread",
    "star",
    "unstar",
    "trash",
    "stop",
}


class RuleError(ValueError):
    """Raised when a rules file cannot be understood."""


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _matches_address(candidates: Iterable[str], patterns: Iterable[str]) -> bool:
    """A pattern matches a full address, a domain, or any substring of it."""
    candidates = [c.lower() for c in candidates]
    for pattern in patterns:
        pattern = pattern.strip().lower().lstrip("@")
        if not pattern:
            continue
        for candidate in candidates:
            if candidate == pattern or candidate.endswith("@" + pattern) or pattern in candidate:
                return True
    return False


@dataclass
class Conditions:
    raw: dict[str, Any]

    def __post_init__(self) -> None:
        unknown = set(self.raw) - KNOWN_CONDITIONS
        if unknown:
            raise RuleError(f"unknown condition(s): {', '.join(sorted(unknown))}")
        for key in ("from_regex", "subject_regex"):
            if key in self.raw:
                try:
                    re.compile(str(self.raw[key]), re.IGNORECASE)
                except re.error as exc:
                    raise RuleError(f"invalid regex in {key}: {exc}") from exc
        if "larger_than" in self.raw:
            parse_size(self.raw["larger_than"])
        self.any_of = [Conditions(dict(block)) for block in self.raw.get("any_of", [])]

    def matches(self, message: Message, now: datetime | None = None) -> bool:
        c = self.raw

        if "from" in c and not _matches_address(message.addresses("from"), _as_list(c["from"])):
            return False
        if "not_from" in c and _matches_address(message.addresses("from"), _as_list(c["not_from"])):
            return False
        if "to" in c:
            recipients = message.addresses("to") + message.addresses("cc")
            if not _matches_address(recipients, _as_list(c["to"])):
                return False
        if "cc" in c and not _matches_address(message.addresses("cc"), _as_list(c["cc"])):
            return False
        if "from_regex" in c and not re.search(str(c["from_regex"]), message.header("from"), re.IGNORECASE):
            return False
        if "subject_contains" in c:
            subject = message.subject.lower()
            if not any(needle.lower() in subject for needle in _as_list(c["subject_contains"])):
                return False
        if "subject_regex" in c and not re.search(str(c["subject_regex"]), message.subject, re.IGNORECASE):
            return False
        if "list_id" in c:
            list_id = message.list_id
            if not any(needle.lower() in list_id for needle in _as_list(c["list_id"])):
                return False
        if "is_list" in c and bool(c["is_list"]) != message.has_list_header:
            return False
        if "has_label" in c and not set(_as_list(c["has_label"])) <= message.label_ids:
            return False
        if "not_label" in c and set(_as_list(c["not_label"])) & message.label_ids:
            return False
        if "is_unread" in c and bool(c["is_unread"]) != message.is_unread:
            return False
        if "is_starred" in c and bool(c["is_starred"]) != message.is_starred:
            return False
        if "in_inbox" in c and bool(c["in_inbox"]) != message.in_inbox:
            return False
        if "older_than_days" in c:
            age = message.age_days(now)
            if age is None or age < float(c["older_than_days"]):
                return False
        if "newer_than_days" in c:
            age = message.age_days(now)
            if age is None or age > float(c["newer_than_days"]):
                return False
        if "larger_than" in c and message.size_estimate < parse_size(c["larger_than"]):
            return False
        if self.any_of and not any(block.matches(message, now) for block in self.any_of):
            return False
        return True


@dataclass
class Actions:
    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    archive: bool = False
    mark_read: bool = False
    mark_unread: bool = False
    star: bool = False
    unstar: bool = False
    trash: bool = False
    stop: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Actions":
        unknown = set(data) - KNOWN_ACTIONS
        if unknown:
            raise RuleError(f"unknown action(s): {', '.join(sorted(unknown))}")
        actions = cls(
            add_labels=_as_list(data.get("add_labels")),
            remove_labels=_as_list(data.get("remove_labels")),
            archive=bool(data.get("archive", False)),
            mark_read=bool(data.get("mark_read", False)),
            mark_unread=bool(data.get("mark_unread", False)),
            star=bool(data.get("star", False)),
            unstar=bool(data.get("unstar", False)),
            trash=bool(data.get("trash", False)),
            stop=bool(data.get("stop", False)),
        )
        if actions.mark_read and actions.mark_unread:
            raise RuleError("mark_read and mark_unread are mutually exclusive")
        if actions.star and actions.unstar:
            raise RuleError("star and unstar are mutually exclusive")
        if not any(
            [
                actions.add_labels,
                actions.remove_labels,
                actions.archive,
                actions.mark_read,
                actions.mark_unread,
                actions.star,
                actions.unstar,
                actions.trash,
            ]
        ):
            raise RuleError("rule has no effect: define at least one action besides 'stop'")
        return actions


@dataclass
class Rule:
    name: str
    conditions: Conditions
    actions: Actions
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> "Rule":
        if not isinstance(data, dict):
            raise RuleError(f"rule #{index + 1} must be a mapping")
        name = str(data.get("name") or f"rule #{index + 1}")
        try:
            if "match" not in data:
                raise RuleError("missing 'match' block")
            if "actions" not in data:
                raise RuleError("missing 'actions' block")
            conditions = Conditions(dict(data["match"] or {}))
            if not conditions.raw:
                raise RuleError("'match' block is empty; that would touch every message")
            actions = Actions.from_dict(dict(data["actions"] or {}))
        except RuleError as exc:
            raise RuleError(f"{name}: {exc}") from exc
        return cls(
            name=name,
            conditions=conditions,
            actions=actions,
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class Plan:
    """What should happen to one message, after every rule has had its say."""

    message: Message
    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    trash: bool = False
    matched_rules: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not (self.add_labels or self.remove_labels or self.trash)


@dataclass
class RuleSet:
    rules: list[Rule]
    search: str = "in:inbox"
    max_messages: int = 500
    allow_trash: bool = False

    @classmethod
    def load(cls, path: str) -> "RuleSet":
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise RuleError("rules file must be a mapping with a 'rules' key")
        raw_rules = data.get("rules")
        if not raw_rules:
            raise RuleError("rules file defines no rules")
        rules = [Rule.from_dict(item, i) for i, item in enumerate(raw_rules)]
        allow_trash = bool(data.get("allow_trash", False))

        # Destructive actions are opt-in for the whole file, not per rule: a
        # typo in one pattern should not be able to empty an inbox.
        if not allow_trash:
            offenders = [rule.name for rule in rules if rule.actions.trash]
            if offenders:
                raise RuleError(
                    "these rules use 'trash' but the file does not set "
                    f"allow_trash: true — {', '.join(offenders)}"
                )
        return cls(
            rules=rules,
            search=str(data.get("search", "in:inbox")),
            max_messages=int(data.get("max_messages", 500)),
            allow_trash=allow_trash,
        )

    def plan_for(self, message: Message, now: datetime | None = None) -> Plan:
        plan = Plan(message=message)
        add: list[str] = []
        remove: list[str] = []

        for rule in self.rules:
            if not rule.enabled or not rule.conditions.matches(message, now):
                continue
            plan.matched_rules.append(rule.name)
            a = rule.actions

            for label in a.add_labels:
                if label not in add:
                    add.append(label)
            for label in a.remove_labels:
                if label not in remove:
                    remove.append(label)
            if a.archive and "INBOX" not in remove:
                remove.append("INBOX")
            if a.mark_read and "UNREAD" not in remove:
                remove.append("UNREAD")
            if a.mark_unread and "UNREAD" not in add:
                add.append("UNREAD")
            if a.star and "STARRED" not in add:
                add.append("STARRED")
            if a.unstar and "STARRED" not in remove:
                remove.append("STARRED")
            if a.trash:
                plan.trash = True
            if a.stop:
                break

        # Removing wins over adding the same label: an explicit "get this out of
        # my inbox" late in the file should not be undone by an earlier rule.
        plan.add_labels = [label for label in add if label not in remove]
        plan.remove_labels = remove

        # Trashing makes every other label change pointless.
        if plan.trash:
            plan.add_labels = []
            plan.remove_labels = []
        return plan
