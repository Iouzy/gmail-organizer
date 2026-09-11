from datetime import datetime, timedelta, timezone

import pytest
import yaml

from gmail_organizer.message import Message, parse_size
from gmail_organizer.rules import RuleError, RuleSet

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def make_message(
    sender="alguem@exemplo.com",
    subject="Olá",
    to="eu@exemplo.com",
    labels=("INBOX", "UNREAD"),
    list_id="",
    age_days=1,
    size=2048,
    message_id="m1",
):
    headers = [
        {"name": "From", "value": sender},
        {"name": "To", "value": to},
        {"name": "Subject", "value": subject},
    ]
    if list_id:
        headers.append({"name": "List-Id", "value": list_id})
    internal = NOW - timedelta(days=age_days)
    return Message.from_api(
        {
            "id": message_id,
            "threadId": "t1",
            "labelIds": list(labels),
            "sizeEstimate": size,
            "internalDate": str(int(internal.timestamp() * 1000)),
            "payload": {"headers": headers},
        }
    )


def ruleset(**overrides):
    data = {"rules": [], **overrides}
    return data


def load(yaml_text):
    import tempfile, os

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        handle.write(yaml_text)
        path = handle.name
    try:
        return RuleSet.load(path)
    finally:
        os.unlink(path)


# --- message parsing -------------------------------------------------------


def test_message_parses_headers_and_addresses():
    message = make_message(sender="Ana Silva <ana@exemplo.com>")
    assert message.sender == "ana@exemplo.com"
    assert message.subject == "Olá"
    assert message.is_unread and message.in_inbox


def test_age_days():
    assert make_message(age_days=10).age_days(NOW) == pytest.approx(10, abs=0.01)


@pytest.mark.parametrize(
    "value,expected", [(1024, 1024), ("1k", 1024), ("5M", 5 * 1024**2), ("2.5m", int(2.5 * 1024**2))]
)
def test_parse_size(value, expected):
    assert parse_size(value) == expected


def test_parse_size_rejects_garbage():
    with pytest.raises(ValueError):
        parse_size("enorme")


# --- matching --------------------------------------------------------------


RULES = """
rules:
  - name: newsletters
    match:
      is_list: true
    actions:
      add_labels: ["Newsletters"]
      archive: true
"""


def test_list_message_is_archived_and_labelled():
    rules = load(RULES)
    plan = rules.plan_for(make_message(list_id="<noticias.exemplo.com>"), NOW)
    assert plan.add_labels == ["Newsletters"]
    assert plan.remove_labels == ["INBOX"]
    assert plan.matched_rules == ["newsletters"]


def test_non_list_message_is_untouched():
    rules = load(RULES)
    plan = rules.plan_for(make_message(), NOW)
    assert plan.is_noop


def test_from_matches_bare_domain():
    rules = load(
        """
rules:
  - name: banco
    match:
      from: ["banco.pt"]
    actions:
      add_labels: ["Finanças"]
"""
    )
    assert rules.plan_for(make_message(sender="avisos@banco.pt"), NOW).add_labels == ["Finanças"]
    assert rules.plan_for(make_message(sender="avisos@outro.pt"), NOW).is_noop


def test_not_from_excludes():
    rules = load(
        """
rules:
  - name: tudo menos o chefe
    match:
      not_from: ["chefe@empresa.com"]
      subject_contains: ["relatorio"]
    actions:
      add_labels: ["Relatórios"]
"""
    )
    assert rules.plan_for(make_message(subject="relatorio semanal"), NOW).add_labels
    assert rules.plan_for(
        make_message(sender="chefe@empresa.com", subject="relatorio semanal"), NOW
    ).is_noop


def test_any_of_is_an_or_block():
    rules = load(
        """
rules:
  - name: recibos
    match:
      any_of:
        - subject_contains: ["fatura"]
        - from: ["stripe.com"]
    actions:
      add_labels: ["Recibos"]
"""
    )
    assert rules.plan_for(make_message(subject="A sua fatura"), NOW).add_labels == ["Recibos"]
    assert rules.plan_for(make_message(sender="no-reply@stripe.com"), NOW).add_labels == ["Recibos"]
    assert rules.plan_for(make_message(subject="almoço"), NOW).is_noop


def test_conditions_are_anded_together():
    rules = load(
        """
rules:
  - name: promo antiga
    match:
      has_label: ["CATEGORY_PROMOTIONS"]
      older_than_days: 7
    actions:
      archive: true
      mark_read: true
"""
    )
    old_promo = make_message(labels=("INBOX", "UNREAD", "CATEGORY_PROMOTIONS"), age_days=30)
    new_promo = make_message(labels=("INBOX", "UNREAD", "CATEGORY_PROMOTIONS"), age_days=2)
    assert set(rules.plan_for(old_promo, NOW).remove_labels) == {"INBOX", "UNREAD"}
    assert rules.plan_for(new_promo, NOW).is_noop


def test_larger_than():
    rules = load(
        """
rules:
  - name: pesados
    match:
      larger_than: 5M
    actions:
      add_labels: ["Pesados"]
"""
    )
    assert rules.plan_for(make_message(size=6 * 1024**2), NOW).add_labels == ["Pesados"]
    assert rules.plan_for(make_message(size=1024), NOW).is_noop


def test_subject_regex_is_case_insensitive():
    rules = load(
        r"""
rules:
  - name: alertas
    match:
      subject_regex: "^\\[alert\\]"
    actions:
      star: true
"""
    )
    assert rules.plan_for(make_message(subject="[ALERT] disco cheio"), NOW).add_labels == ["STARRED"]


# --- rule ordering ---------------------------------------------------------


ORDERED = """
rules:
  - name: chefe intocável
    match:
      from: ["chefe@empresa.com"]
    actions:
      star: true
      stop: true
  - name: arquivar tudo o resto
    match:
      in_inbox: true
    actions:
      archive: true
"""


def test_stop_halts_later_rules():
    rules = load(ORDERED)
    plan = rules.plan_for(make_message(sender="chefe@empresa.com"), NOW)
    assert plan.add_labels == ["STARRED"]
    assert plan.remove_labels == []
    assert plan.matched_rules == ["chefe intocável"]


def test_rules_after_a_non_stopping_match_still_run():
    rules = load(ORDERED)
    plan = rules.plan_for(make_message(), NOW)
    assert plan.remove_labels == ["INBOX"]


def test_disabled_rule_is_skipped():
    rules = load(
        """
rules:
  - name: desligada
    enabled: false
    match:
      in_inbox: true
    actions:
      archive: true
"""
    )
    assert rules.plan_for(make_message(), NOW).is_noop


def test_removing_beats_adding_the_same_label():
    rules = load(
        """
rules:
  - name: etiqueta
    match:
      in_inbox: true
    actions:
      add_labels: ["Talvez"]
  - name: retira
    match:
      in_inbox: true
    actions:
      remove_labels: ["Talvez"]
"""
    )
    plan = rules.plan_for(make_message(), NOW)
    assert plan.add_labels == []
    assert plan.remove_labels == ["Talvez"]


# --- validation ------------------------------------------------------------


def test_empty_match_is_rejected():
    with pytest.raises(RuleError, match="empty"):
        load("rules:\n  - name: tudo\n    match: {}\n    actions:\n      archive: true\n")


def test_unknown_condition_is_rejected():
    with pytest.raises(RuleError, match="unknown condition"):
        load("rules:\n  - name: x\n    match:\n      sender: a@b.com\n    actions:\n      archive: true\n")


def test_unknown_action_is_rejected():
    with pytest.raises(RuleError, match="unknown action"):
        load("rules:\n  - name: x\n    match:\n      in_inbox: true\n    actions:\n      delete: true\n")


def test_rule_without_effect_is_rejected():
    with pytest.raises(RuleError, match="no effect"):
        load("rules:\n  - name: x\n    match:\n      in_inbox: true\n    actions:\n      stop: true\n")


def test_bad_regex_is_rejected():
    with pytest.raises(RuleError, match="invalid regex"):
        load('rules:\n  - name: x\n    match:\n      subject_regex: "([a"\n    actions:\n      archive: true\n')


def test_trash_requires_opt_in():
    body = "rules:\n  - name: limpar\n    match:\n      from: [spam@x.com]\n    actions:\n      trash: true\n"
    with pytest.raises(RuleError, match="allow_trash"):
        load(body)
    rules = load("allow_trash: true\n" + body)
    assert rules.plan_for(make_message(sender="spam@x.com"), NOW).trash


def test_example_rules_file_is_valid():
    rules = RuleSet.load("rules.example.yaml")
    assert len(rules.rules) >= 5
    assert rules.allow_trash is False
