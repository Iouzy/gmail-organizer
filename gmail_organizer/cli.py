"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .auth import DEFAULT_CREDENTIALS, DEFAULT_TOKEN, build_service
from .gmail_client import GmailClient
from .organizer import Organizer, Report
from .rules import RuleError, RuleSet

DEFAULT_RULES = "rules.yaml"


def _truncate(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_report(report: Report, dry_run: bool, verbose: bool) -> None:
    header = "DRY RUN — nothing was changed" if dry_run else "Applied"
    print(f"\n{header}")
    print(f"  scanned: {report.scanned}")
    print(f"  messages with changes: {report.changed}")
    if report.trashed:
        print(f"  moved to trash: {report.trashed}")

    if report.per_rule:
        print("\nMatches per rule:")
        for name, count in report.per_rule.most_common():
            print(f"  {count:>5}  {name}")

    if verbose and report.changes:
        print("\nPer message:")
        for change in report.changes:
            message = change.message
            print(f"  {_truncate(message.sender, 34):<34}  {_truncate(message.subject, 46)}")
            bits = []
            if change.add_names:
                bits.append("+" + ", +".join(change.add_names))
            if change.remove_names:
                bits.append("-" + ", -".join(change.remove_names))
            if change.trash:
                bits.append("TRASH")
            print(f"      {'  '.join(bits)}   [{', '.join(change.matched_rules)}]")


def _load_rules(path: str) -> RuleSet:
    try:
        return RuleSet.load(path)
    except FileNotFoundError:
        sys.exit(f"rules file not found: {path} (copy rules.example.yaml to get started)")
    except RuleError as exc:
        sys.exit(f"invalid rules file: {exc}")


def cmd_check(args: argparse.Namespace) -> int:
    ruleset = _load_rules(args.rules)
    print(f"{len(ruleset.rules)} rule(s) loaded from {args.rules}")
    print(f"search: {ruleset.search}")
    print(f"max_messages: {ruleset.max_messages}")
    for rule in ruleset.rules:
        state = "" if rule.enabled else "  (disabled)"
        print(f"  - {rule.name}{state}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ruleset = _load_rules(args.rules)
    if args.search:
        ruleset.search = args.search

    service = build_service(args.credentials, args.token)
    client = GmailClient(service)
    organizer = Organizer(client, ruleset, dry_run=not args.apply)

    print(f"search: {ruleset.search}")
    report = organizer.run(now=datetime.now(tz=timezone.utc), limit=args.limit)
    _print_report(report, dry_run=not args.apply, verbose=args.verbose or not args.apply)
    if not args.apply and report.changed:
        print("\nRe-run with --apply to actually change the mailbox.")
    return 0


def cmd_labels(args: argparse.Namespace) -> int:
    service = build_service(args.credentials, args.token)
    client = GmailClient(service)
    for name, label_id in sorted(client.labels().items()):
        print(f"{label_id:<24} {name}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from .webapp import serve

    serve(
        rules_path=args.rules,
        credentials_path=args.credentials,
        token_path=args.token,
        port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmail-organizer",
        description="Rule-based Gmail organizer. Deterministic: same inbox, same result.",
    )
    parser.add_argument("--rules", default=DEFAULT_RULES, help=f"rules file (default: {DEFAULT_RULES})")
    parser.add_argument("--credentials", default=DEFAULT_CREDENTIALS, help="OAuth client secrets JSON")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="where the OAuth token is cached")

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="apply the rules to the mailbox (dry run unless --apply)")
    run.add_argument("--apply", action="store_true", help="actually modify the mailbox")
    run.add_argument("--limit", type=int, default=None, help="cap on messages to scan")
    run.add_argument("--search", default=None, help="override the search query from the rules file")
    run.add_argument("-v", "--verbose", action="store_true", help="list every affected message")
    run.set_defaults(func=cmd_run)

    ui = sub.add_parser("ui", help="open the point-and-click app in the browser")
    ui.add_argument("--port", type=int, default=8765, help="local port (default: 8765)")
    ui.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    ui.set_defaults(func=cmd_ui)

    check = sub.add_parser("check", help="validate the rules file without touching Gmail")
    check.set_defaults(func=cmd_check)

    labels = sub.add_parser("labels", help="list the labels in the account")
    labels.set_defaults(func=cmd_labels)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit("interrupted")


if __name__ == "__main__":
    raise SystemExit(main())
