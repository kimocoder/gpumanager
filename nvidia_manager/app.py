"""Lightweight helpers from the NVIDIA Driver Manager project.

Only a few pure helpers are provided here so unit tests and other tools can
import the package without initializing or depending on a GUI environment.
"""

from __future__ import annotations

import subprocess
import re
import os
from typing import List, Dict, Optional

def _ensure_xdg_runtime_dir() -> None:
    """Ensure XDG_RUNTIME_DIR is set in minimal environments.

    This is performed in a small helper to avoid creating module-level
    variables that static linters might treat as constants.
    """
    if os.environ.get("XDG_RUNTIME_DIR"):
        return
    try:
        uid = os.getuid()
    except (AttributeError, OSError):
        uid = None
    candidate = f"/run/user/{uid}" if uid is not None else None
    if candidate and os.path.isdir(candidate):
        os.environ["XDG_RUNTIME_DIR"] = candidate
    else:
        # Fall back to a writable location; /tmp is safe and widely available.
        os.environ["XDG_RUNTIME_DIR"] = "/tmp"


# Ensure the runtime dir is set at module import time.
_ensure_xdg_runtime_dir()


def run_cmd(cmd: List[str], timeout: int = 15, env: Optional[Dict[str, str]] = None) -> tuple[str, str, int]:
    """Run a command and return (stdout, stderr, returncode)."""
    # Ensure the child process inherits a sensible environment. If the caller
    # provided an env mapping, merge it on top of the current environment so
    # we don't accidentally drop important variables like XDG_RUNTIME_DIR.
    if env is None:
        use_env = os.environ.copy()
    else:
        use_env = os.environ.copy()
        use_env.update(env)
    try:
        # Do not raise CalledProcessError; prefer to inspect returncode.
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=use_env, check=False
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", f"Command not found: {cmd[0]}", 127
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except (OSError, subprocess.SubprocessError) as e:
        # Handle process creation and execution-related errors explicitly.
        return "", str(e), 1


def parse_ubuntu_drivers(text: str) -> List[Dict[str, object]]:
    """Parse output from `ubuntu-drivers devices` into a list of driver dicts.

    Returns a list of dicts with keys: package, version, description,
    recommended, type.
    """
    drivers: List[Dict[str, object]] = []
    for line in text.splitlines():
        m = re.search(r"(nvidia-driver-\d+\S*)\s*-\s*(.*)", line)
        if not m:
            continue
        pkg = m.group(1)
        desc = m.group(2).strip()
        ver_m = re.search(r"(\d+)", pkg)
        ver = ver_m.group(1) if ver_m else pkg
        recommended = "recommended" in desc.lower()
        dtype = "Production"
        if "server" in desc.lower():
            dtype = "Server"
        elif "open" in desc.lower():
            dtype = "Open Kernel"
        drivers.append({
            "package": pkg,
            "version": ver,
            "description": desc,
            "recommended": recommended,
            "type": dtype,
        })
    return drivers


def parse_apt_drivers(text: str) -> List[Dict[str, object]]:
    """Parse `apt list nvidia-driver-* --all-versions` output for drivers."""
    drivers: List[Dict[str, object]] = []
    seen = set()
    for line in text.splitlines():
        m = re.search(r"(nvidia-driver-(\d+))/", line)
        if not m:
            continue
        pkg = m.group(1)
        ver = m.group(2)
        if pkg in seen:
            continue
        seen.add(pkg)
        drivers.append({
            "package": pkg,
            "version": ver,
            "description": line.strip(),
            "recommended": False,
            "type": "Production",
        })
    try:
        return sorted(drivers, key=lambda d: int(str(d["version"])), reverse=True)
    except (ValueError, TypeError):
        # If version strings cannot be converted to int, return as-is.
        return drivers


def detect_driver_version_nvidia_smi() -> Optional[str]:
    """Return installed NVIDIA driver version from nvidia-smi or None."""
    out, _, rc = run_cmd(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
    if rc == 0 and out:
        return out.splitlines()[0].strip()
    return None


def main(argv=None) -> int:
    """Console entry point.

    This function is intentionally import-safe: importing this module does not
    import tkinter or initialize the GUI. When the console entry calls
    `main()` we attempt to launch the full GUI in one of two ways (in order):

    1. If the top-level script `nvidia-manager.py` exists next to the package,
       load it as a module (lazy import) and, if it defines
       `NvidiaDriverManager`, instantiate it and call `mainloop()`.
    2. Fall back to spawning the top-level script as a subprocess.

    These strategies keep import-time safe while enabling the installed
    `nvidia-manager` command to launch the GUI when available in the source
    tree or editable installation.
    """
    # The following imports are intentionally lazy so importing this module
    # remains safe in headless/test environments. Tell pylint this is OK.
    # pylint: disable=import-outside-toplevel
    import sys
    import importlib.util
    from pathlib import Path

    # Locate the top-level script relative to this package (two levels up).
    pkg_path = Path(__file__).resolve()
    project_root = pkg_path.parent.parent
    script_path = project_root / "nvidia-manager.py"

    if not script_path.exists():
        # Nothing to run in this installation — helpful message for users.
        print("nvidia-manager: GUI entry point is not available in this installation. Import helpers instead.")
        return 1

    # First attempt: import the script as a module so we can instantiate the
    # GUI class in-process. This keeps everything in the same Python process
    # and makes it simple to pass control back and forth.
    try:
        spec = importlib.util.spec_from_file_location("nvidia_manager_gui_script", str(script_path))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # If the script defines the application class, instantiate it.
            if hasattr(mod, "NvidiaDriverManager"):
                app_cls = getattr(mod, "NvidiaDriverManager")
                app = app_cls()
                app.mainloop()
                return 0
    except Exception as exc:  # pragma: no cover - runtime GUI errors  # pylint: disable=broad-exception-caught
        # The GUI import/runtime can raise many environment-dependent
        # exceptions (missing tkinter, no display, etc.). We intentionally
        # catch broad exceptions here to fall back to the subprocess launcher
        # instead of allowing import-time failures.
        print(f"nvidia-manager: in-process GUI launch failed: {exc}", file=sys.stderr)

    # Fallback: spawn a new Python interpreter to run the script.
    try:
        python = sys.executable or "python3"
        args = [python, str(script_path)]
        if argv:
            # If argv is provided, extend the subprocess args (list or tuple)
            args.extend(list(argv))
        return subprocess.call(args)
    except Exception as exc:  # pragma: no cover - runtime fallback  # pylint: disable=broad-exception-caught
        # Catch broad exceptions here for robustness and document intent for
        # static analysis tools.
        print(f"nvidia-manager: failed to launch GUI subprocess: {exc}", file=sys.stderr)
        return 1
