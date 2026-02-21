#!/usr/bin/env python3
"""
Docker Update Checker
Lists Docker containers that need to be updated, with a curses UI.
Self-installs required dependencies if missing.
"""

import sys
import subprocess
import os

REQUIRED_PACKAGES = ['docker', 'curses']


def self_install():
    """Install required packages if missing."""
    import importlib
    import platform
    missing = []
    for pkg in ['docker']:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    # curses is built-in on Linux/macOS, windows-curses for Windows
    if platform.system() == "Windows":
        try:
            importlib.import_module('curses')
        except ImportError:
            missing.append('windows-curses')
    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)
        print("Installation complete. Please restart the script.")
        sys.exit(0)


def check_updates_with_progress(client, containers):
    """Check which containers need updates, showing progress in terminal."""
    container_infos = []
    total = len(containers)
    for i, c in enumerate(containers):
        # Use the image name from container config (same as Diun)
        image_ref = c.attrs['Config']['Image']
        # Ensure image has a tag, default to :latest
        if ':' not in image_ref.split('/')[-1]:
            image_ref = image_ref + ':latest'
        info = {
            'name': c.name,
            'image_ref': image_ref,
            'needs_update': False,
            'error': None,
            'local_id': None,
            'latest_id': None,
        }
        try:
            local_id = c.image.id
            result = subprocess.run(
                ['docker', 'pull', image_ref],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if result.returncode != 0:
                info['error'] = result.stderr.decode().strip().splitlines()[-1]
            else:
                latest_id = client.images.get(image_ref).id
                info['local_id'] = local_id
                info['latest_id'] = latest_id
                if local_id != latest_id:
                    info['needs_update'] = True
        except Exception as e:
            info['error'] = str(e)
        container_infos.append(info)
        print(f"[{i+1}/{total}] Checked {c.name} ({image_ref})")
    return container_infos


def curses_ui(container_infos, containers, client):
    import curses

    def draw_main(stdscr):
        curses.curs_set(0)
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)   # up to date
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # needs update
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)     # error
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)   # selected/cursor

        updatable = [i for i, info in enumerate(container_infos) if info['needs_update']]

        # --- Summary screen ---
        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            stdscr.addstr(0, 0, "Docker Update Checker".center(w), curses.A_BOLD)
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
            footer = "u: Update containers  q: Quit" if updatable else "All containers are up to date. Press q to quit."
            stdscr.addstr(h - 1, 0, footer[:w-1], curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord('q'), 27):
                return
            if key == ord('u') and updatable:
                break

        if not updatable:
            return

        # --- Selection screen ---
        selected = set(updatable)  # all pre-selected by default
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
                    # Container managed by Docker Compose — use compose to update
                    # Support custom compose file paths via label
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
                        raise RuntimeError(r.stderr.decode().strip().splitlines()[-1])
                    stdscr.addstr(row, 0, f"  {name}: recreating via compose...")
                    stdscr.refresh()
                    r = subprocess.run(
                        compose_cmd + ['up', '-d', '--no-deps', compose_service],
                        cwd=compose_dir,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    if r.returncode != 0:
                        raise RuntimeError(r.stderr.decode().strip().splitlines()[-1])
                else:
                    # Standalone container — preserve full config before recreating
                    attrs = container.attrs
                    host_cfg = attrs['HostConfig']
                    cfg = attrs['Config']

                    # Ports
                    port_bindings = host_cfg.get('PortBindings') or {}

                    # Volumes: use Mounts to handle both bind mounts and named volumes
                    volumes = {}
                    for m in (attrs.get('Mounts') or []):
                        mode = 'rw' if m.get('RW', True) else 'ro'
                        if m['Type'] == 'bind':
                            volumes[m['Source']] = {'bind': m['Destination'], 'mode': mode}
                        elif m['Type'] == 'volume':
                            vol_key = m.get('Name') or m['Destination']
                            volumes[vol_key] = {'bind': m['Destination'], 'mode': mode}

                    # VolumesFrom
                    volumes_from = host_cfg.get('VolumesFrom') or []

                    # Environment
                    env = cfg.get('Env') or []

                    # Restart policy
                    restart_policy = host_cfg.get('RestartPolicy') or {}

                    # Labels (preserve original labels)
                    orig_labels = cfg.get('Labels') or {}

                    # Extra hosts
                    extra_hosts = host_cfg.get('ExtraHosts') or []

                    # Privileged
                    privileged = host_cfg.get('Privileged', False)

                    # Hostname
                    hostname = cfg.get('Hostname') or None

                    # Linux capabilities
                    cap_add = host_cfg.get('CapAdd') or []
                    cap_drop = host_cfg.get('CapDrop') or []

                    # Network mode (host, none, container:xyz, or custom/bridge)
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

                    stdscr.addstr(row, 0, f"  {name}: stopping...")
                    stdscr.refresh()
                    container.stop()
                    stdscr.addstr(row, 0, f"  {name}: removing...")
                    stdscr.refresh()
                    container.remove()
                    stdscr.addstr(row, 0, f"  {name}: pulling latest image...")
                    stdscr.refresh()
                    subprocess.run(['docker', 'pull', image_ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    stdscr.addstr(row, 0, f"  {name}: restarting...")
                    stdscr.refresh()
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
                    # Connect to additional networks
                    for net_name in extra_networks:
                        try:
                            client.networks.get(net_name).connect(new_container)
                        except Exception:
                            pass

                stdscr.addstr(row, 0, f"  {name}: done."[:w-1], curses.color_pair(1))
                stdscr.refresh()
            except Exception as e:
                stdscr.addstr(row, 0, f"  {name}: ERROR - {e}"[:w-1], curses.color_pair(3))
                stdscr.refresh()
        stdscr.addstr(h - 1, 0, "Update complete. Press any key to exit."[:w-1], curses.A_BOLD)
        stdscr.refresh()
        stdscr.getch()

    curses.wrapper(draw_main)


def main():
    self_install()
    import docker
    client = docker.from_env()
    containers = client.containers.list()
    print(f"Checking {len(containers)} containers for updates...")
    container_infos = check_updates_with_progress(client, containers)
    curses_ui(container_infos, containers, client)


if __name__ == '__main__':
    main()
