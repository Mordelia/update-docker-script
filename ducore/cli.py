from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check and apply Docker container updates."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show summary without pulling images or applying updates",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Non-interactive mode: apply all updates without UI",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Max parallel checks (default: 4)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Only check these container names (can be repeated)",
        metavar="NAME",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude these container names (can be repeated)",
        metavar="NAME",
    )
    parser.add_argument(
        "--only-label",
        action="append",
        default=[],
        help="Only containers with label key=value (can be repeated)",
        metavar="KEY=VALUE",
    )
    parser.add_argument(
        "--exclude-label",
        action="append",
        default=[],
        help="Exclude containers with label key=value (can be repeated)",
        metavar="KEY=VALUE",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-confirm: skip summary and selection screens, update all",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON report instead of curses UI",
    )
    return parser.parse_args(argv)
