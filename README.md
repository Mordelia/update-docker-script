# 🐳 Docker Update Checker

A terminal-based interactive tool to detect and apply updates to your Docker containers, with a clean **curses UI** and **self-installation** of dependencies.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS-lightgrey)

---

## ✨ Features

- **Detects outdated containers** by pulling the latest image and comparing SHA256 digests
- **Interactive curses UI** — color-coded status, keyboard navigation, multi-select
- **Smart update logic**:
  - Docker Compose containers → updated via `docker compose pull` + `docker compose up -d` (preserves the full compose config)
  - Standalone containers → full configuration is preserved before recreation: ports, volumes (bind + named), networks (all of them), environment variables, restart policy, labels, hostname, capabilities (`--cap-add`/`--cap-drop`), `--volumes-from`, extra hosts, network mode (`host`, `none`, `container:...`), privileged mode
- **Custom compose file support** — reads the `com.docker.compose.project.config_files` label to find non-standard compose file paths
- **Self-installs** missing Python dependencies (`docker` SDK) on first run
- Uses `c.attrs['Config']['Image']` as image reference (same method as Diun) — works even when `image.tags` is empty

---

## 📋 Requirements

- Python 3.8+
- Docker installed and running
- Your user must have access to the Docker socket:
  ```bash
  sudo usermod -aG docker $USER
  # then log out and back in
  ```

---

## 🚀 Usage

```bash
# Run directly (dependencies are installed automatically on first run)
python3 docker_update_checker.py
```

The script will:
1. Check all running containers for updates (shown as terminal progress)
2. Open a curses UI with the results

---

## 🖥️ UI Controls

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

## 📦 Manual dependency installation

```bash
pip install -r requirements.txt
```

---

## ⚠️ Notes

- **Standalone containers** are stopped, removed, and recreated with the exact same configuration. There is no rollback if the pull succeeds but the recreation fails — back up critical containers before updating.
- **Compose containers** are updated in-place using `docker compose up -d`, which is the safest method.
- Environment variable *values* are preserved as resolved at container creation time, not from the original `.env` file.

---

## 📄 License

[MIT](LICENSE)
