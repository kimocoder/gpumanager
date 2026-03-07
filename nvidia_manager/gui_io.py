"""I/O helpers for the GUI module.

Provide small wrappers for reading/writing JSON and text files with
explicit encodings to satisfy linters and make behavior explicit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def load_json(path: Path) -> Optional[Any]:
    """Load JSON from path returning the parsed object or None on error."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def save_json(path: Path, data: Any) -> bool:
    """Save data as JSON. Returns True on success."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        return True
    except OSError:
        return False
