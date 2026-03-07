"""Settings helpers for nvidia_manager GUI and CLI

This module provides load/save helpers with logging and atomic write semantics.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "nvidia-manager"
CONFIG_PATH = CONFIG_DIR / "settings.json"


def load_settings(defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Load settings from disk and merge with provided defaults.

    Returns a dict with defaults updated with any saved values.
    Any errors are logged and the defaults are returned.
    """
    out = dict(defaults)
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    out.update(data)
                else:
                    logger.warning("Settings file %s did not contain a JSON object", CONFIG_PATH)
    except Exception as exc:  # wide catch to ensure GUI does not crash on bad config
        logger.exception("Failed to load settings from %s: %s", CONFIG_PATH, exc)
    return out


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings atomically to CONFIG_PATH.

    Writes to a temporary file in the same directory and then renames it into place
    using os.replace so the operation is atomic on POSIX systems.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Write to a named temporary file in the target directory to ensure
        # os.replace will be atomic on the same filesystem.
        fd, tmp = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=str(CONFIG_DIR))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(settings, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            # Replace target atomically
            os.replace(tmp, CONFIG_PATH)
        finally:
            # If something went wrong and the tmp still exists, remove it
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                # Best-effort cleanup; do not raise
                pass
    except Exception as exc:
        logger.exception("Failed to save settings to %s: %s", CONFIG_PATH, exc)

