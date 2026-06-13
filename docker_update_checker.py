#!/usr/bin/env python3
"""
Docker Update Checker
Lists Docker containers that need to be updated, with a curses UI.
Self-installs required dependencies if missing.
"""

from __future__ import annotations

from ducore import self_install


def main(argv: list[str] | None = None) -> None:
    from ducore.cli import parse_args

    args = parse_args(argv)
    self_install()

    from ducore.checker import (
        setup_logging,
        check_docker_access,
        filter_containers,
        check_updates_with_progress,
        logger,
    )
    from ducore.ui import curses_ui, non_interactive_update, output_json
    from typing import Any
    setup_logging()
    logger.info("=== Docker Update Checker started === (dry_run=%s, apply=%s, json=%s)",
                args.dry_run, args.apply, args.json)

    client: Any = check_docker_access()
    all_containers: list[Any] = client.containers.list()
    containers: list[Any] = filter_containers(all_containers, args)
    skipped: int = len(all_containers) - len(containers)
    logger.info("Found %d running containers (%d filtered out)", len(all_containers), skipped)
    if skipped:
        print(f"Found {len(all_containers)} running container(s). "
              f"After filtering: {len(containers)}. Checking for updates...")
    else:
        print(f"Found {len(containers)} running container(s). Checking for updates...")
    if not containers:
        print("No containers to check (check your filters).")
        return

    container_infos: list[dict[str, Any]] = check_updates_with_progress(
        client, containers, dry_run=args.dry_run, max_workers=args.max_workers,
    )

    if args.json:
        output_json(container_infos)
    elif args.apply and not args.dry_run:
        non_interactive_update(container_infos, containers, client)
    else:
        curses_ui(
            container_infos, containers, client,
            dry_run=args.dry_run, auto_confirm=args.yes,
        )

    logger.info("=== Docker Update Checker finished ===")


if __name__ == '__main__':
    main()
