"""Organizer tests against a fake Gmail client — no network, no credentials."""

from datetime import datetime, timezone

from gmail_organizer.organizer import Organizer
from gmail_organizer.rules import RuleSet
from tests.test_rules import load, make_message

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, messages, labels=None):
        self.messages = messages
        self._labels = dict(labels or {"INBOX": "INBOX", "UNREAD": "UNREAD", "STARRED": "STARRED"})
        self.modifications = []
        self.trashed = []
        self.created_labels = []

    def labels(self):
        return self._labels

    def resolve_label(self, name):
        if name in self._labels:
            return self._labels[name]
        if name in self._labels.values():
            return name
        return None

    def ensure_label(self, name):
        self.created_labels.append(name)
        self._labels[name] = f"Label_{len(self._labels)}"
        return self._labels[name]

    def search_ids(self, query, limit):
        return [m.id for m in self.messages][:limit]

    def hydrate(self, ids):
        by_id = {m.id: m for m in self.messages}
        return (by_id[i] for i in ids)

    def batch_modify(self, message_ids, add_label_ids, remove_label_ids):
        self.modifications.append((sorted(message_ids), add_label_ids, remove_label_ids))

    def trash(self, message_ids):
        self.trashed.extend(message_ids)


RULES = load(
    """
rules:
  - name: newsletters
    match:
      is_list: true
    actions:
      add_labels: ["Newsletters"]
      archive: true
"""
)


def newsletter(message_id):
    return make_message(message_id=message_id, list_id="<noticias.exemplo.com>")


def test_dry_run_changes_nothing():
    client = FakeClient([newsletter("a"), newsletter("b"), make_message(message_id="c")])
    report = Organizer(client, RULES, dry_run=True).run(NOW)

    assert report.scanned == 3
    assert report.changed == 2
    assert report.per_rule["newsletters"] == 2
    assert client.modifications == []
    assert client.created_labels == []


def test_apply_groups_identical_changes_into_one_call():
    client = FakeClient([newsletter("a"), newsletter("b")])
    Organizer(client, RULES, dry_run=False).run(NOW)

    assert client.created_labels == ["Newsletters"]
    assert len(client.modifications) == 1
    ids, add, remove = client.modifications[0]
    assert ids == ["a", "b"]
    assert add == [client.labels()["Newsletters"]]
    assert remove == ["INBOX"]


def test_labels_already_present_are_not_reapplied():
    message = make_message(message_id="a", list_id="<x.com>", labels=("INBOX", "Label_9"))
    client = FakeClient([message], labels={"INBOX": "INBOX", "Newsletters": "Label_9"})
    report = Organizer(client, RULES, dry_run=False).run(NOW)

    assert report.changed == 1
    _, add, remove = client.modifications[0]
    assert add == []          # already labelled
    assert remove == ["INBOX"]


def test_message_already_archived_and_labelled_is_a_noop():
    message = make_message(message_id="a", list_id="<x.com>", labels=("Label_9",))
    client = FakeClient([message], labels={"INBOX": "INBOX", "Newsletters": "Label_9"})
    report = Organizer(client, RULES, dry_run=False).run(NOW)

    assert report.changed == 0
    assert client.modifications == []


def test_trash_wins_over_label_changes():
    rules = load(
        """
allow_trash: true
rules:
  - name: etiqueta
    match:
      is_list: true
    actions:
      add_labels: ["Newsletters"]
  - name: lixo
    match:
      from: ["spam@x.com"]
    actions:
      trash: true
"""
    )
    message = make_message(message_id="a", sender="spam@x.com", list_id="<x.com>")
    client = FakeClient([message])
    report = Organizer(client, rules, dry_run=False).run(NOW)

    assert report.trashed == 1
    assert client.trashed == ["a"]
    assert client.modifications == []


def test_limit_caps_the_scan():
    client = FakeClient([newsletter(str(i)) for i in range(10)])
    report = Organizer(client, RULES, dry_run=True).run(NOW, limit=3)
    assert report.scanned == 3
