# Docker Update Checker

A terminal-based interactive tool to detect and apply updates to your Docker containers, with a clean **curses UI**, **parallel checking**, **rollback safety**, and **CLI filtering**.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS-lightgrey)

---

## Features

- **Detects outdated containers** by pulling the latest image and comparing SHA256 digests
- **Parallel checking** — containers are verified concurrently via `ThreadPoolExecutor` (configurable with `--max-workers`)
- **Interactive curses UI** — color-coded status, keyboard navigation, multi-select
- **Smart update logic**:
  - Docker Compose containers → updated via `docker compose pull` + `docker compose up -d`
  - Standalone containers → full configuration is preserved before recreation: ports, volumes (bind + named), networks, environment variables, restart policy, labels, hostname, capabilities, `--volumes-from`, extra hosts, network mode, privileged mode
- **Rollback safety**:
  - Standalone containers are renamed (`name.rollback-<timestamp>`) instead of removed; restored automatically on failure
  - Compose containers save the old image ID; tagged back and restarted if `up -d` fails
  - Pull failures trigger immediate restore (no intermediate broken state)
- **CLI filtering** — `--only`, `--exclude`, `--only-label`, `--exclude-label`
- **Auto-confirm mode** (`--yes`) — skip summary & selection, update everything
- **Non-interactive mode** (`--apply`) — apply updates without UI, usable in cron/CI
- **JSON output** (`--json`) — machine-readable report for CI pipelines
- **Dry-run mode** (`--dry-run`) — display outdated containers without pulling images
- **Custom compose file support** — reads the `com.docker.compose.project.config_files` label
- **Self-installs** missing Python dependencies on first run
- **Structured logging** — debug log to `~/.docker_update_checker.log`
- Uses `c.attrs['Config']['Image']` as image reference (same method as Diun)

---

## Requirements

- Python 3.10+
- Docker installed and running
- Your user must have access to the Docker socket:
  ```bash
  sudo usermod -aG docker $USER
  # then log out and back in
  ```

---

## Usage

```bash
# Run directly (dependencies installed automatically on first run)
python3 docker_update_checker.py

# Check only specific containers
python3 docker_update_checker.py --only myapp --only myworker

# Exclude containers matching a label
python3 docker_update_checker.py --exclude-label env=dev

# Dry-run: show summary without pulling images
python3 docker_update_checker.py --dry-run

# Non-interactive: apply all updates (for cron/CI)
python3 docker_update_checker.py --apply --only production-app

# Parallel check with 8 workers
python3 docker_update_checker.py --max-workers 8

# Auto-confirm: update all without interaction
python3 docker_update_checker.py --yes

# JSON report for CI pipelines
python3 docker_update_checker.py --json --dry-run | jq '.[] | select(.needs_update) | .name'

# Install via pip (optional, no self-install needed)
pip install .
docker-update-checker --help
```

### CLI options

| Flag | Description |
|------|-------------|
| `--dry-run` | Show summary without pulling images or applying updates |
| `--apply` | Non-interactive mode: apply all updates without curses UI |
| `--max-workers N` | Max parallel checks (default: 4) |
| `--only NAME` | Only check these container names (repeatable) |
| `--exclude NAME` | Exclude these container names (repeatable) |
| `--only-label KEY=VALUE` | Only containers with this label (repeatable) |
| `--exclude-label KEY=VALUE` | Exclude containers with this label (repeatable) |
| `--yes` | Auto-confirm: skip summary and selection, update all |
| `--json` | Output machine-readable JSON report instead of curses UI |
| `-h`, `--help` | Show help message and exit |

---

## UI Controls

### Summary screen
| Key | Action |
|-----|--------|
| `u` | Go to update selection |
| `q` / `Esc` | Quit |

### Selection screen
| Key | Action |
|-----|--------|
| `↑` / `k` | Move up |
| `↓` / `j` | Move down |
| `Space` | Toggle selection |
| `a` | Select / deselect all |
| `Enter` | Start update |
| `q` / `Esc` | Back |

---

## Installation

### Direct (self-install)
```bash
python3 docker_update_checker.py
# Missing dependencies are installed automatically
```

### Via pip
```bash
pip install .
docker-update-checker --help
```

### Manual
```bash
pip install -r requirements.txt
python3 docker_update_checker.py
```

---

## Notes

- **Standalone containers** are renamed (not removed) before recreation. If the update fails, the original container is restored. If restoration also fails, a critical message is shown — manual recovery needed.
- **Compose containers** are updated via `docker compose up -d`. If this fails, the old image is tagged back and `up -d` is retried.
- **Pull failures** during standalone update immediately restore the backup container. The container is never left in a broken state.
- Environment variable *values* are preserved as resolved at container creation time, not from the original `.env` file.
- Logs are written to `~/.docker_update_checker.log` (debug level).

---

## Project structure

```
docker_update_checker.py   — Entry point
ducore/
├── __init__.py            — Self-install logic
├── cli.py                 — CLI argument parsing
├── checker.py             — Docker access, filtering, update checking
└── ui.py                  — Curses UI + update functions + non-interactive mode
tests/
├── __init__.py
├── test_checker.py        — 36 unit tests
└── test_integration.py    — 5 integration tests (skipped if Docker absent)
pyproject.toml             — Packaging & dependencies
```

---

## License

[MIT](LICENSE)
