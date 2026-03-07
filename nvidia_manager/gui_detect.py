"""System detection helpers extracted from GUI.

These helpers are pure functions that call the provided `run_cmd` helper and
return structured detection results. They have no GUI dependencies so they can
be unit tested and linted independently.
"""
from __future__ import annotations

import os
import glob
from typing import Dict, Any


def detect_cpu(run_cmd) -> Dict[str, Any]:  # pylint: disable=too-many-branches,too-many-statements
    """Detect CPU information using lscpu and /proc files.

    Returns a dictionary with keys similar to the GUI's expectations.
    """
    info: Dict[str, Any] = {
        "model": None,
        "vendor": None,
        "arch": None,
        "cores_physical": None,
        "cores_logical": None,
        "threads_per_core": None,
        "sockets": None,
        "freq_base_mhz": None,
        "freq_max_mhz": None,
        "freq_cur_mhz": None,
        "cache": {},
        "features": [],
        "vulnerabilities": {},
        "numa_nodes": None,
        "microcode": None,
    }

    out, _, rc = run_cmd(["lscpu"], timeout=10)
    if rc == 0 and out:
        for line in out.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            kl = k.lower()
            if "model name" in kl:
                info["model"] = v
            elif kl == "vendor id":
                info["vendor"] = v
            elif kl == "architecture":
                info["arch"] = v
            elif "socket(s)" in kl:
                info["sockets"] = v
            elif "core(s) per socket" in kl:
                try:
                    sockets = int(info.get("sockets") or 1)
                    info["cores_physical"] = int(v) * sockets
                except ValueError:
                    pass
            elif "thread(s) per core" in kl:
                info["threads_per_core"] = v
            elif "cpu(s)" == kl:
                info["cores_logical"] = v
            elif "cpu max mhz" in kl:
                info["freq_max_mhz"] = v.split(".")[0]
            elif "cpu min mhz" in kl:
                info["freq_base_mhz"] = v.split(".")[0]
            elif "cpu mhz" == kl:
                info["freq_cur_mhz"] = v.split(".")[0]
            elif kl.startswith("l1d"):
                info["cache"]["L1d"] = v
            elif kl.startswith("l1i"):
                info["cache"]["L1i"] = v
            elif kl.startswith("l2"):
                info["cache"]["L2"] = v
            elif kl.startswith("l3"):
                info["cache"]["L3"] = v
            elif "numa node(s)" in kl:
                info["numa_nodes"] = v
            elif kl == "flags":
                isa_set = {
                    "avx", "avx2", "avx512f", "avx512bw", "avx512cd",
                    "avx512dq", "avx512vl", "avx512vnni", "avx512bf16",
                    "avx512_bf16", "amx_bf16", "amx_int8", "amx_tile",
                    "sse4_1", "sse4_2", "aes", "vaes", "vpclmulqdq",
                    "f16c", "fma", "bmi1", "bmi2", "popcnt",
                }
                info["features"] = sorted(isa_set & set(v.lower().split()))

    # fallback /proc/cpuinfo
    if not info["freq_cur_mhz"]:
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("cpu MHz"):
                        info["freq_cur_mhz"] = line.split(":")[1].strip().split(".")[0]
                        break
        except OSError:
            pass

    # microcode
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("microcode"):
                    info["microcode"] = line.split(":")[1].strip()
                    break
    except OSError:
        pass

    # vulnerabilities
    vuln_dir = "/sys/devices/system/cpu/vulnerabilities"
    if os.path.isdir(vuln_dir):
        for p in sorted(glob.glob(f"{vuln_dir}/*")):
            name = os.path.basename(p)
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    status = fh.read().strip()
                info["vulnerabilities"][name] = status
            except OSError:
                pass

    return info
