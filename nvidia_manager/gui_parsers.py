"""Small parsing helpers extracted from the large GUI module.

These functions are pure-Python and safe to import at top-level.
"""
from __future__ import annotations

import re
from typing import List, Dict


def parse_ubuntu_drivers(text: str) -> List[Dict[str, object]]:
    """Parse the output of "ubuntu-drivers devices" or similar text.

    Returns a list of driver dictionaries with keys: package, version,
    description, recommended, type.
    """
    drivers: List[Dict[str, object]] = []
    for line in text.split("\n"):
        m = re.search(r"(nvidia-driver-\d+\S*)\s*-\s*(.*)", line)
        if m:
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
            drivers.append(
                {
                    "package": pkg,
                    "version": ver,
                    "description": desc,
                    "recommended": recommended,
                    "type": dtype,
                }
            )
    return drivers


def parse_apt_drivers(text: str) -> List[Dict[str, object]]:
    """Parse `apt` or apt-cache style output to find nvidia-driver packages.

    Returns a sorted list of driver dicts (newest first).
    """
    drivers = []
    seen = set()
    for line in text.split("\n"):
        m = re.search(r"(nvidia-driver-(\d+))/", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            drivers.append(
                {
                    "package": m.group(1),
                    "version": m.group(2),
                    "description": line.strip(),
                    "recommended": False,
                    "type": "Production",
                }
            )

    try:
        def version_key(d):
            v = d.get("version", "0")
            try:
                return int(v)
            except (ValueError, TypeError):
                return 0
        return sorted(drivers, key=version_key, reverse=True)
    except (KeyError, ValueError, TypeError):
        return drivers
