from __future__ import annotations

import sys
import subprocess


def self_install() -> None:
    """Install required packages if missing."""
    import importlib
    import platform
    missing: list[str] = []
    for pkg in ['docker']:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
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
