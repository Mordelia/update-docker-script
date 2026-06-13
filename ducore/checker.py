from __future__ import annotations

import sys
import subprocess
import os
import logging
import argparse
import concurrent.futures
from typing import Any

LOG_FILE: str = os.path.expanduser("~/.docker_update_checker.log")
logger: logging.Logger = logging.getLogger("docker_update_checker")


def setup_logging() -> None:
    log_dir: str = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    formatter: logging.Formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler: logging.FileHandler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    stderr_handler: logging.StreamHandler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(stderr_handler)


def check_docker_access() -> Any:
    import docker
    try:
        client: Any = docker.from_env()
        client.ping()
        logger.info("Docker daemon access OK")
        return client
    except docker.errors.DockerException as e:
        logger.critical("Cannot connect to Docker daemon: %s", e)
        print(f"Error: Cannot connect to Docker daemon.\n"
              f"Is Docker running and does your user have access?\n"
              f"  sudo usermod -aG docker $USER\n{e}")
        sys.exit(1)


def filter_containers(containers: list[Any], args: argparse.Namespace) -> list[Any]:
    filtered: list[Any] = list(containers)
    if args.only:
        only_names: set[str] = set(args.only)
        filtered = [c for c in filtered if c.name in only_names]
    if args.exclude:
        exclude_names: set[str] = set(args.exclude)
        filtered = [c for c in filtered if c.name not in exclude_names]
    if args.only_label:
        for kv in args.only_label:
            key, _, val = kv.partition("=")
            filtered = [c for c in filtered if (c.labels or {}).get(key) == val]
    if args.exclude_label:
        for kv in args.exclude_label:
            key, _, val = kv.partition("=")
            filtered = [c for c in filtered if (c.labels or {}).get(key) != val]
    return filtered


def check_updates_with_progress(
    client: Any,
    containers: list[Any],
    dry_run: bool = False,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    total: int = len(containers)
    container_infos: list[dict[str, Any]] = [None] * total  # type: ignore[list-item]

    def check_one(c: Any) -> tuple[int, dict[str, Any]]:
        image_ref: str = c.attrs['Config']['Image']
        if ':' not in image_ref.split('/')[-1]:
            image_ref = image_ref + ':latest'
        info: dict[str, Any] = {
            'name': c.name,
            'image_ref': image_ref,
            'needs_update': False,
            'error': None,
            'local_id': None,
            'latest_id': None,
        }
        try:
            local_id: str = c.image.id
            info['local_id'] = local_id
            if not dry_run:
                result: subprocess.CompletedProcess = subprocess.run(
                    ['docker', 'pull', image_ref],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if result.returncode != 0:
                    info['error'] = result.stderr.decode().strip().splitlines()[-1]
                    logger.warning("%s: pull failed — %s", c.name, info['error'])
                else:
                    latest_id: str = client.images.get(image_ref).id
                    info['latest_id'] = latest_id
                    if local_id != latest_id:
                        info['needs_update'] = True
                        logger.info("%s: update available (%s)", c.name, image_ref)
                    else:
                        logger.info("%s: up to date (%s)", c.name, image_ref)
            else:
                logger.info("%s: dry-run — skipped pull (%s)", c.name, image_ref)
        except Exception as e:
            info['error'] = str(e)
            logger.error("%s: check error — %s", c.name, e)
        return id(c), info

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map: dict[concurrent.futures.Future[Any], Any] = {
            pool.submit(check_one, c): c for c in containers
        }
        done: int = 0
        for fut in concurrent.futures.as_completed(fut_map):
            done += 1
            c = fut_map[fut]
            _cid, info = fut.result()
            for idx in range(len(container_infos)):
                if container_infos[idx] is None:
                    container_infos[idx] = info
                    if info['name'] == c.name:
                        break
            print(f"[{done}/{total}] Checked {c.name} ({info['image_ref']})")

    return [info for info in container_infos if info is not None]
