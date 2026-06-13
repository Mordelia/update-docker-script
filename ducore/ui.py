from __future__ import annotations

import sys
import subprocess
import time
import logging
from typing import Any

logger: logging.Logger = logging.getLogger("docker_update_checker")


def curses_ui(
    container_infos: list[dict[str, Any]],
    containers: list[Any],
    client: Any,
    dry_run: bool = False,
    auto_confirm: bool = False,
) -> None:
    import curses
    import docker

    def draw_main(stdscr: Any) -> None:
        curses.curs_set(0)
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)

        updatable = [i for i, info in enumerate(container_infos) if info['needs_update']]

        if auto_confirm and not dry_run and updatable:
            selected = set(updatable)
            _run_updates(stdscr, selected, container_infos, containers, client, 100, 100)
            stdscr.addstr(0, 0, "Update complete. Press any key to exit.")
            stdscr.refresh()
            stdscr.getch()
            return

        # --- Summary screen ---
        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            stdscr.addstr(0, 0, "Docker Update Checker".center(w), curses.A_BOLD)
            if dry_run:
                stdscr.addstr(0, w - 11, "[DRY-RUN]", curses.A_BOLD)
            stdscr.addstr(1, 0, "-" * w)
            for idx, info in enumerate(container_infos):
                if 2 + idx >= h - 3:
                    break
                status = ""
                attr = curses.color_pair(1)
                if info['error']:
                    status = f"ERROR: {info['error']}"
                    attr = curses.color_pair(3)
                elif info['needs_update']:
                    status = "UPDATE AVAILABLE"
                    attr = curses.color_pair(2)
                else:
                    status = "Up to date"
                line = f"  {info['name']:<30} {info['image_ref']:<45} {status}"
                stdscr.addstr(2 + idx, 0, line[:w-1], attr)
            if dry_run:
                footer = "q: Quit"
            else:
                footer = "u: Update containers  q: Quit" if updatable else "All containers are up to date. Press q to quit."
            stdscr.addstr(h - 1, 0, footer[:w-1], curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()
            if dry_run:
                if key in (ord('q'), 27):
                    return
            else:
                if key in (ord('q'), 27):
                    return
                if key == ord('u') and updatable:
                    break

        if not updatable or dry_run:
            return

        # --- Selection screen ---
        selected = set(updatable)
        cursor = 0
        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            stdscr.addstr(0, 0, "Select containers to update".center(w), curses.A_BOLD)
            stdscr.addstr(1, 0, "-" * w)
            for idx, i in enumerate(updatable):
                if 2 + idx >= h - 3:
                    break
                info = container_infos[i]
                checked = "[x]" if i in selected else "[ ]"
                line = f" {checked} {info['name']:<30} {info['image_ref']}"
                attr = curses.A_REVERSE if idx == cursor else curses.color_pair(2)
                stdscr.addstr(2 + idx, 0, line[:w-1], attr)
            stdscr.addstr(h - 1, 0, "↑↓: move  space: select  a: all  enter: update  q: back"[:w-1], curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('k')):
                cursor = (cursor - 1) % len(updatable)
            elif key in (curses.KEY_DOWN, ord('j')):
                cursor = (cursor + 1) % len(updatable)
            elif key == ord(' '):
                i = updatable[cursor]
                if i in selected:
                    selected.remove(i)
                else:
                    selected.add(i)
            elif key == ord('a'):
                if selected == set(updatable):
                    selected.clear()
                else:
                    selected = set(updatable)
            elif key in (curses.KEY_ENTER, 10, 13):
                break
            elif key in (ord('q'), 27):
                return

        if not selected:
            return

        # --- Update screen ---
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        stdscr.addstr(0, 0, "Updating selected containers...".center(w), curses.A_BOLD)
        stdscr.addstr(1, 0, "-" * w)
        stdscr.refresh()

        _run_updates(stdscr, selected, container_infos, containers, client, h, w)

        stdscr.addstr(h - 1, 0, "Update complete. Press any key to exit."[:w-1], curses.A_BOLD)
        stdscr.refresh()
        stdscr.getch()

    curses.wrapper(draw_main)


def _run_updates(
    stdscr: Any,
    selected: set[int],
    container_infos: list[dict[str, Any]],
    containers: list[Any],
    client: Any,
    h: int,
    w: int,
) -> None:
    import curses
    import docker

    for idx, i in enumerate(sorted(selected)):
        info = container_infos[i]
        name = info['name']
        image_ref = info['image_ref']
        row = 2 + idx * 2
        if row >= h - 3:
            break
        try:
            container = next(c for c in containers if c.name == name)
            labels = container.labels or {}
            compose_dir = labels.get('com.docker.compose.project.working_dir')
            compose_service = labels.get('com.docker.compose.service')

            if compose_dir and compose_service:
                _update_compose(stdscr, container, name, compose_dir, compose_service, row, w)
            else:
                _update_standalone(stdscr, container, client, name, image_ref, row, w)

            stdscr.addstr(row, 0, f"  {name}: done."[:w-1], curses.color_pair(1))
            stdscr.refresh()
        except Exception as e:
            stdscr.addstr(row, 0, f"  {name}: ERROR - {e}"[:w-1], curses.color_pair(3))
            stdscr.refresh()


def _update_compose(
    stdscr: Any,
    container: Any,
    name: str,
    compose_dir: str,
    compose_service: str,
    row: int,
    w: int,
) -> None:
    import docker as docker_mod
    client_docker = docker_mod.from_env()

    labels = container.labels or {}
    old_image_id: str = container.image.id
    old_image_ref: str = container.attrs['Config']['Image']
    config_files = labels.get('com.docker.compose.project.config_files', '')
    compose_cmd = ['docker', 'compose']
    if config_files:
        for cf in config_files.split(','):
            cf = cf.strip()
            if cf:
                compose_cmd += ['-f', cf]

    stdscr.addstr(row, 0, f"  {name}: pulling via compose...")
    stdscr.refresh()
    r = subprocess.run(
        compose_cmd + ['pull', compose_service],
        cwd=compose_dir,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if r.returncode != 0:
        logger.error("%s: compose pull failed", name)
        raise RuntimeError(r.stderr.decode().strip().splitlines()[-1])

    stdscr.addstr(row, 0, f"  {name}: recreating via compose...")
    stdscr.refresh()
    r = subprocess.run(
        compose_cmd + ['up', '-d', '--no-deps', compose_service],
        cwd=compose_dir,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if r.returncode != 0:
        logger.error("%s: compose up failed, attempting rollback...", name)
        err_msg: str = r.stderr.decode().strip().splitlines()[-1]
        stdscr.addstr(row, 0, f"  {name}: up FAILED, rolling back...")
        stdscr.refresh()
        try:
            old_img = client_docker.images.get(old_image_id)
            old_img.tag(old_image_ref, force=True)
            r2 = subprocess.run(
                compose_cmd + ['up', '-d', '--no-deps', compose_service],
                cwd=compose_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if r2.returncode != 0:
                raise RuntimeError(
                    r2.stderr.decode().strip().splitlines()[-1]
                )
            logger.info("%s: compose rollback successful", name)
            stdscr.addstr(row, 0, f"  {name}: rollback OK — old image restored")
        except Exception as rollback_err:
            logger.critical("%s: compose rollback failed: %s", name, rollback_err)
            stdscr.addstr(row, 0, f"  {name}: ROLLBACK FAILED — manual recovery needed")
        stdscr.refresh()
        raise RuntimeError(err_msg)

    logger.info("%s: compose update done", name)


def _update_standalone(
    stdscr: Any,
    container: Any,
    client: Any,
    name: str,
    image_ref: str,
    row: int,
    w: int,
) -> None:
    import docker
    attrs = container.attrs
    host_cfg = attrs['HostConfig']
    cfg = attrs['Config']

    port_bindings = host_cfg.get('PortBindings') or {}

    volumes = {}
    for m in (attrs.get('Mounts') or []):
        mode = 'rw' if m.get('RW', True) else 'ro'
        if m['Type'] == 'bind':
            volumes[m['Source']] = {'bind': m['Destination'], 'mode': mode}
        elif m['Type'] == 'volume':
            vol_key = m.get('Name') or m['Destination']
            volumes[vol_key] = {'bind': m['Destination'], 'mode': mode}

    volumes_from = host_cfg.get('VolumesFrom') or []
    env = cfg.get('Env') or []
    restart_policy = host_cfg.get('RestartPolicy') or {}
    orig_labels = cfg.get('Labels') or {}
    extra_hosts = host_cfg.get('ExtraHosts') or []
    privileged = host_cfg.get('Privileged', False)
    hostname = cfg.get('Hostname') or None
    cap_add = host_cfg.get('CapAdd') or []
    cap_drop = host_cfg.get('CapDrop') or []
    network_mode = host_cfg.get('NetworkMode', 'bridge')

    use_network_mode = (
        network_mode in ('host', 'none')
        or network_mode.startswith('container:')
    )
    all_networks = list(
        (attrs.get('NetworkSettings', {}).get('Networks') or {}).keys()
    )
    primary_network = None if use_network_mode else (all_networks[0] if all_networks else None)
    extra_networks = [] if use_network_mode else all_networks[1:]

    backup_name = f"{name}.rollback-{int(time.time())}"

    stdscr.addstr(row, 0, f"  {name}: stopping...")
    stdscr.refresh()
    container.stop()
    logger.info("%s: container stopped", name)

    stdscr.addstr(row, 0, f"  {name}: renaming to {backup_name} (backup)...")
    stdscr.refresh()
    container.rename(backup_name)
    logger.info("%s: renamed to %s (backup)", name, backup_name)

    stdscr.addstr(row, 0, f"  {name}: pulling latest image...")
    stdscr.refresh()
    pull_result = subprocess.run(
        ['docker', 'pull', image_ref],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if pull_result.returncode != 0:
        logger.error("%s: pull failed — restoring backup", name)
        stdscr.addstr(row, 0, f"  {name}: pull FAILED — restoring backup...")
        stdscr.refresh()
        backup = client.containers.get(backup_name)
        backup.rename(name)
        backup.start()
        logger.info("%s: backup restored after pull failure", name)
        raise RuntimeError(
            pull_result.stderr.decode().strip().splitlines()[-1]
        )
    logger.info("%s: image pulled (%s)", name, image_ref)

    stdscr.addstr(row, 0, f"  {name}: creating new container...")
    stdscr.refresh()
    try:
        new_container = client.containers.run(
            image_ref,
            name=name,
            detach=True,
            ports=port_bindings if port_bindings else None,
            volumes=volumes if volumes else None,
            volumes_from=volumes_from if volumes_from else None,
            environment=env if env else None,
            restart_policy=restart_policy if restart_policy.get('Name') else None,
            network_mode=network_mode if use_network_mode else None,
            network=primary_network,
            labels=orig_labels if orig_labels else None,
            extra_hosts=extra_hosts if extra_hosts else None,
            privileged=privileged,
            hostname=hostname,
            cap_add=cap_add if cap_add else None,
            cap_drop=cap_drop if cap_drop else None,
        )
        for net_name in extra_networks:
            try:
                client.networks.get(net_name).connect(new_container)
            except Exception:
                pass

        stdscr.addstr(row, 0, f"  {name}: removing backup container...")
        stdscr.refresh()
        backup = client.containers.get(backup_name)
        backup.remove()
        logger.info("%s: update successful, backup removed", name)
    except Exception:
        logger.error("%s: update failed, initiating rollback...", name)
        stdscr.addstr(row, 0, f"  {name}: update FAILED, rolling back...")
        stdscr.refresh()
        try:
            try:
                failed = client.containers.get(name)
                failed.remove(force=True)
                logger.info("%s: failed new container removed", name)
            except docker.errors.NotFound:
                pass
            backup = client.containers.get(backup_name)
            backup.rename(name)
            backup.start()
            logger.info("%s: rollback completed, original container restored", name)
            stdscr.addstr(row, 0, f"  {name}: rollback OK — original restored")
        except Exception as rollback_err:
            logger.critical("%s: rollback also failed: %s", name, rollback_err)
            stdscr.addstr(row, 0, f"  {name}: ROLLBACK ALSO FAILED — manual recovery needed")
        stdscr.refresh()
        raise


def non_interactive_update(
    container_infos: list[dict[str, Any]],
    containers: list[Any],
    client: Any,
) -> None:
    import docker

    updatable = [i for i, info in enumerate(container_infos) if info['needs_update']]
    if not updatable:
        print("All containers are up to date.")
        return

    print(f"Updating {len(updatable)} container(s) in non-interactive mode...")
    errors: int = 0
    for i in sorted(updatable):
        info = container_infos[i]
        name = info['name']
        image_ref = info['image_ref']
        print(f"  {name}: updating ({image_ref})...", end="", flush=True)
        try:
            container = next(c for c in containers if c.name == name)
            labels = container.labels or {}
            compose_dir = labels.get('com.docker.compose.project.working_dir')
            compose_service = labels.get('com.docker.compose.service')

            if compose_dir and compose_service:
                _update_compose_noninteractive(container, name, compose_dir, compose_service)
            else:
                _update_standalone_noninteractive(container, client, name, image_ref)
            print(" done.")
        except Exception as e:
            print(f" ERROR: {e}")
            errors += 1

    if errors:
        print(f"\n{errors} update(s) failed.")
        sys.exit(1)
    print("\nAll updates applied successfully.")


def _update_compose_noninteractive(
    container: Any,
    name: str,
    compose_dir: str,
    compose_service: str,
) -> None:
    import docker as docker_mod
    client_docker = docker_mod.from_env()

    labels = container.labels or {}
    old_image_id: str = container.image.id
    old_image_ref: str = container.attrs['Config']['Image']
    config_files = labels.get('com.docker.compose.project.config_files', '')
    compose_cmd = ['docker', 'compose']
    if config_files:
        for cf in config_files.split(','):
            cf = cf.strip()
            if cf:
                compose_cmd += ['-f', cf]

    r = subprocess.run(
        compose_cmd + ['pull', compose_service],
        cwd=compose_dir,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode().strip().splitlines()[-1])
    r = subprocess.run(
        compose_cmd + ['up', '-d', '--no-deps', compose_service],
        cwd=compose_dir,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if r.returncode != 0:
        err_msg: str = r.stderr.decode().strip().splitlines()[-1]
        try:
            old_img = client_docker.images.get(old_image_id)
            old_img.tag(old_image_ref, force=True)
            r2 = subprocess.run(
                compose_cmd + ['up', '-d', '--no-deps', compose_service],
                cwd=compose_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if r2.returncode != 0:
                raise RuntimeError(
                    r2.stderr.decode().strip().splitlines()[-1]
                )
            logger.info("%s: compose rollback successful", name)
        except Exception as rollback_err:
            logger.critical("%s: compose rollback failed: %s", name, rollback_err)
            raise RuntimeError(
                f"Update failed ({err_msg}) and rollback also failed: {rollback_err}"
            ) from None
        raise RuntimeError(err_msg)


def _update_standalone_noninteractive(
    container: Any,
    client: Any,
    name: str,
    image_ref: str,
) -> None:
    import docker
    attrs = container.attrs
    host_cfg = attrs['HostConfig']
    cfg = attrs['Config']

    port_bindings = host_cfg.get('PortBindings') or {}
    volumes = {}
    for m in (attrs.get('Mounts') or []):
        mode = 'rw' if m.get('RW', True) else 'ro'
        if m['Type'] == 'bind':
            volumes[m['Source']] = {'bind': m['Destination'], 'mode': mode}
        elif m['Type'] == 'volume':
            vol_key = m.get('Name') or m['Destination']
            volumes[vol_key] = {'bind': m['Destination'], 'mode': mode}
    volumes_from = host_cfg.get('VolumesFrom') or []
    env = cfg.get('Env') or []
    restart_policy = host_cfg.get('RestartPolicy') or {}
    orig_labels = cfg.get('Labels') or {}
    extra_hosts = host_cfg.get('ExtraHosts') or []
    privileged = host_cfg.get('Privileged', False)
    hostname = cfg.get('Hostname') or None
    cap_add = host_cfg.get('CapAdd') or []
    cap_drop = host_cfg.get('CapDrop') or []
    network_mode = host_cfg.get('NetworkMode', 'bridge')

    use_network_mode = (
        network_mode in ('host', 'none')
        or network_mode.startswith('container:')
    )
    all_networks = list(
        (attrs.get('NetworkSettings', {}).get('Networks') or {}).keys()
    )
    primary_network = None if use_network_mode else (all_networks[0] if all_networks else None)
    extra_networks = [] if use_network_mode else all_networks[1:]

    backup_name = f"{name}.rollback-{int(time.time())}"

    container.stop()
    container.rename(backup_name)
    pull_result = subprocess.run(
        ['docker', 'pull', image_ref],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if pull_result.returncode != 0:
        logger.error("%s: pull failed — restoring backup", name)
        backup = client.containers.get(backup_name)
        backup.rename(name)
        backup.start()
        logger.info("%s: backup restored after pull failure", name)
        raise RuntimeError(
            pull_result.stderr.decode().strip().splitlines()[-1]
        )

    try:
        new_container = client.containers.run(
            image_ref, name=name, detach=True,
            ports=port_bindings if port_bindings else None,
            volumes=volumes if volumes else None,
            volumes_from=volumes_from if volumes_from else None,
            environment=env if env else None,
            restart_policy=restart_policy if restart_policy.get('Name') else None,
            network_mode=network_mode if use_network_mode else None,
            network=primary_network,
            labels=orig_labels if orig_labels else None,
            extra_hosts=extra_hosts if extra_hosts else None,
            privileged=privileged,
            hostname=hostname,
            cap_add=cap_add if cap_add else None,
            cap_drop=cap_drop if cap_drop else None,
        )
        for net_name in extra_networks:
            try:
                client.networks.get(net_name).connect(new_container)
            except Exception:
                pass
        backup = client.containers.get(backup_name)
        backup.remove()
    except Exception:
        try:
            try:
                failed = client.containers.get(name)
                failed.remove(force=True)
            except docker.errors.NotFound:
                pass
            backup = client.containers.get(backup_name)
            backup.rename(name)
            backup.start()
        except Exception as rollback_err:
            logger.critical("%s: rollback also failed: %s", name, rollback_err)
            raise
        raise


def output_json(container_infos: list[dict[str, Any]]) -> None:
    """Print container status as JSON to stdout."""
    import json
    report: list[dict[str, Any]] = []
    for info in container_infos:
        report.append({
            "name": info["name"],
            "image": info["image_ref"],
            "needs_update": info["needs_update"],
            "error": info["error"],
            "local_id": info.get("local_id"),
            "latest_id": info.get("latest_id"),
        })
    print(json.dumps(report, indent=2))
