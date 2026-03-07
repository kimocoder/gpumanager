"""Shared GUI helpers and constants for nvidia_manager GUI.

This module intentionally avoids importing tkinter so it can be imported
safely at top-level. GUI-specific modules can import these helpers before
performing lazy tkinter imports.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

# Color palette and constants used by the GUI
BG_DARK = "#111318"
BG_PANEL = "#0e1014"
BG_CARD = "#1a1c22"
BG_CARD_HOVER = "#20232b"
BG_INPUT = "#22252d"
BG_HEADER = "#0c0d10"
NVIDIA_GREEN = "#76b900"
GREEN_DIM = "#5a8f00"
GREEN_HOVER = "#8fd400"
GREEN_BG = "#1a2a10"
GREEN_BORDER = "#2a4a10"
GREEN_SELECT = "#3a5c10"
TEXT_PRIMARY = "#e8eaed"
TEXT_SECOND = "#8a8f98"
TEXT_DIM = "#555a63"
RED = "#e74c3c"
RED_BORDER = "#5a2020"
ORANGE = "#f39c12"
CYAN = "#61dafb"
PURPLE = "#a78bfa"
BORDER = "#2a2d35"
BORDER_LIGHT = "#3a3d45"

CONFIG_PATH = Path.home() / ".config" / "nvidia-driver-manager" / "settings.json"


def run_cmd_stream(cmd, log_fn: Callable[[str, str], None], timeout: int = 300) -> int:
    """Run a command and stream combined stdout/stderr lines to log_fn.

    log_fn is called as log_fn(line, level) where level is one of
    "info", "warn", "error", "cmd", etc.
    Returns the process return code, or 1 on error.
    """
    try:
        # Use context manager so resources are cleaned up properly.
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        ) as proc:
            stdout = proc.stdout
            if stdout is None:
                try:
                    log_fn("Failed to capture stdout", "error")
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
                return 1

            for line in iter(stdout.readline, ""):
                s = line.strip()
                if not s:
                    continue
                lvl = "info"
                sl = s.lower()
                if "error" in sl or "failed" in sl:
                    lvl = "error"
                elif "warning" in sl or "dkms" in sl:
                    lvl = "warn"
                elif "done" in sl or "success" in sl or "enabled" in sl:
                    lvl = "success"
                try:
                    log_fn(s, lvl)
                except Exception:  # pylint: disable=broad-exception-caught
                    # Keep broad to avoid log errors crashing the installer
                    pass

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Best-effort: terminate and wait for cleanup
                try:
                    proc.kill()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
                proc.wait()

            return proc.returncode
    except (OSError, subprocess.SubprocessError) as e:
        try:
            log_fn(str(e), "error")
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return 1


__all__ = [
    "run_cmd_stream",
    "CONFIG_PATH",
    "BG_DARK",
    "BG_PANEL",
    "BG_CARD",
    "BG_CARD_HOVER",
    "BG_INPUT",
    "BG_HEADER",
    "NVIDIA_GREEN",
    "GREEN_DIM",
    "GREEN_HOVER",
    "GREEN_BG",
    "GREEN_BORDER",
    "GREEN_SELECT",
    "TEXT_PRIMARY",
    "TEXT_SECOND",
    "TEXT_DIM",
    "RED",
    "RED_BORDER",
    "ORANGE",
    "CYAN",
    "PURPLE",
    "BORDER",
    "BORDER_LIGHT",

]
