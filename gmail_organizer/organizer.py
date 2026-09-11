"""Glue: search the mailbox, run every message past the rules, apply the result."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from .message import Message
from .rules import Plan, RuleSet

if TYPE_CHECKING:  # keeps the rule engine importable without the Google SDK
    from .gmail_client import GmailClient


@dataclass
class Change:
    """A resolved, deduplicated set of label ids to apply to one message."""

    message: Message
    add_label_ids: list[str] = field(default_factory=list)
    remove_label_ids: list[str] = field(default_factory=list)
    add_names: list[str] = field(default_factory=list)
    remove_names: list[str] = field(default_factory=list)
    trash: bool = False
    matched_rules: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not (self.add_label_ids or self.remove_label_ids or self.trash)


@dataclass
class Report:
    scanned: int = 0
    changed: int = 0
    trashed: int = 0
    per_rule: Counter = field(default_factory=Counter)
    changes: list[Change] = field(default_factory=list)


class Organizer:
    def __init__(self, client: "GmailClient", ruleset: RuleSet, dry_run: bool = True) -> None:
        self.client = client
        self.ruleset = ruleset
        self.dry_run = dry_run

    def run(self, now: datetime | None = None, limit: int | None = None) -> Report:
        report = Report()
        limit = limit or self.ruleset.max_messages
        message_ids = self.client.search_ids(self.ruleset.search, limit)

        for message in self.client.hydrate(message_ids):
            report.scanned += 1
            plan = self.ruleset.plan_for(message, now)
            for rule_name in plan.matched_rules:
                report.per_rule[rule_name] += 1
            change = self._resolve(plan)
            if change.is_noop:
                continue
            report.changes.append(change)
            report.changed += 1
            if change.trash:
                report.trashed += 1

        if not self.dry_run:
            self._apply(report.changes)
        return report

    def _resolve(self, plan: Plan) -> Change:
        """Turn label names into ids and drop changes the message already has."""
        change = Change(
            message=plan.message,
            trash=plan.trash,
            matched_rules=list(plan.matched_rules),
        )
        if plan.trash:
            return change

        existing = plan.message.label_ids
        for name in plan.add_labels:
            label_id = self._label_id(name, create=True)
            if label_id and label_id not in existing and label_id not in change.add_label_ids:
                change.add_label_ids.append(label_id)
                change.add_names.append(name)
        for name in plan.remove_labels:
            # Never create a label just to remove it.
            label_id = self._label_id(name, create=False)
            if label_id and label_id in existing and label_id not in change.remove_label_ids:
                change.remove_label_ids.append(label_id)
                change.remove_names.append(name)
        return change

    def _label_id(self, name: str, create: bool) -> str | None:
        resolved = self.client.resolve_label(name)
        if resolved:
            return resolved
        if create and not self.dry_run:
            return self.client.ensure_label(name)
        if create:
            # Dry run: the label does not exist yet, so report it by name.
            return f"<new:{name}>"
        return None

    def _apply(self, changes: list[Change]) -> None:
        to_trash = [c.message.id for c in changes if c.trash]
        grouped: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]] = defaultdict(list)
        for change in changes:
            if change.trash:
                continue
            key = (tuple(sorted(change.add_label_ids)), tuple(sorted(change.remove_label_ids)))
            grouped[key].append(change.message.id)

        for (add_ids, remove_ids), message_ids in grouped.items():
            self.client.batch_modify(message_ids, list(add_ids), list(remove_ids))

        if to_trash:
            self.client.trash(to_trash)
