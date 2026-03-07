"""Inlined GUI implementation (lazy tkinter import).

This file contains a lazily-defined `NvidiaDriverManager` class copied from
the project's top-level `nvidia-manager.py`. The class is created only when
`get_app_class()` is called so importing the package remains safe in
headless/test environments.
"""

from __future__ import annotations

# Large GUI file: relax a few structural pylint checks while we iteratively
# refactor into smaller modules. We keep other pylint checks enabled.
# A few GUI patterns (broad exception handling in the top-level runner,
# module-level global app-class assignment and attributes created lazily in
# methods) are intentional and safe in this context. Silence the specific
# pylint warnings so the remainder of the file can be linted meaningfully.
# pylint: disable=too-many-lines,too-many-statements,too-many-branches,too-many-instance-attributes,
# The GUI is a large inlined module which intentionally contains large
# functions for UI construction and detection; silence some refactor
# warnings that are impractical to address without a major rewrite.
# pylint: disable=broad-exception-caught,global-statement,too-many-locals,too-many-nested-blocks
import sys
import os
import re
import json
import signal
import time
import shlex
import shutil
import threading
import subprocess
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Callable, Literal, Optional, Type, Dict, Any
from functools import partial

from .app import run_cmd
from .gui_helpers import (
    run_cmd_stream,
    CONFIG_PATH,
    BG_DARK,
    BG_PANEL,
    BG_CARD,
    BG_CARD_HOVER,
    BG_INPUT,
    BG_HEADER,
    NVIDIA_GREEN,
    GREEN_DIM,
    GREEN_HOVER,
    GREEN_BG,
    GREEN_BORDER,
    GREEN_SELECT,
    TEXT_PRIMARY,
    TEXT_SECOND,
    TEXT_DIM,
    RED,
    RED_BORDER,
    ORANGE,
    CYAN,
    PURPLE,
    BORDER,
    BORDER_LIGHT,
)
from . import __version__
from . import gui_detect
from . import gui_parsers
from . import gui_widgets
package_version = __version__


_APP_CLASS: Optional[Type] = None


def main(_argv=None) -> int:
    """Launch the NVIDIA Driver Manager GUI.

    Returns 0 on success, 1 if the GUI could not be initialized (e.g. no
    display or tkinter is unavailable).
    """
    app_cls = get_app_class()
    if app_cls is None:
        print(
            "nvidia-manager: could not initialise the GUI "
            "(tkinter not available or no display).",
            file=sys.stderr,
        )
        return 1
    try:
        app = app_cls()
        app.mainloop()
    except Exception as exc:  # pragma: no cover
        print(f"nvidia-manager: GUI error: {exc}", file=sys.stderr)
        return 1
    return 0


def get_app_class() -> Optional[Type]:
    """Return the lazily-created GUI application class or None if tkinter
    is unavailable.

    The GUI class is created only when this function is called so importing
    the package remains safe in headless or test environments.
    """
    global _APP_CLASS
    if _APP_CLASS is not None:
        return _APP_CLASS

    try:
        # Local imports: tkinter is optional and only required for the GUI
        # — perform lazy imports here. Tell pylint this is intentional.
        # pylint: disable=import-outside-toplevel
        import tkinter as tk
        from tkinter import ttk, messagebox, scrolledtext, filedialog
    except ImportError:
        return None

    def _parse_ubuntu_drivers(text):
        return gui_parsers.parse_ubuntu_drivers(text)

    def _make_section_header(parent, text):
        # delegate to widgets helper to keep code small; we pass colors here
        gui_widgets.make_section_header(tk, parent, text)

    def _make_section_label(parent, text):
        gui_widgets.make_section_label(tk, parent, text)

    def _make_card(parent, **kw):
        border = kw.pop("border_color", BORDER)
        return gui_widgets.make_card(tk, parent, border_color=border, bg_card=BG_CARD, **kw)

    def _make_metric(parent, label_text, default="\u2014", row=0, col=0):
        return gui_widgets.make_metric(tk, parent, label_text, default=default, row=row, col=col, border_color=BORDER, bg_card=BG_CARD)

    def _make_toggle_row(parent, label_text, var, callback=None):
        row = tk.Frame(parent, bg=BG_CARD, pady=5)
        row.pack(fill="x")
        tk.Label(row, text=label_text, font=("monospace", 10), fg=TEXT_PRIMARY, bg=BG_CARD, anchor="w").pack(
            side="left"
        )
        cb = tk.Checkbutton(
            row,
            variable=var,
            bg=BG_CARD,
            fg=NVIDIA_GREEN,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=NVIDIA_GREEN,
            highlightthickness=0,
            command=callback,
        )
        cb.pack(side="right")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

    def _make_green_btn(parent, text, command):
        return tk.Button(
            parent,
            text=text,
            font=("monospace", 10, "bold"),
            fg="#000",
            bg=NVIDIA_GREEN,
            activeforeground="#000",
            activebackground=GREEN_HOVER,
            bd=0,
            padx=14,
            pady=4,
            cursor="hand2",
            command=command,
        )

    def _make_action_btn(_app, parent, text, cmd, fg_color=None):
        """Create a small action-style button and return it.

        This helper is bound to the application instance as
        ``self._make_action_btn`` so UI-building code can call it via
        ``self._make_action_btn(...)``. Keep styling minimal and allow
        an override color via ``fg_color``.
        """
        fg = fg_color if fg_color is not None else TEXT_PRIMARY
        try:
            btn = tk.Button(
                parent,
                text=text,
                font=("monospace", 10),
                fg=fg,
                bg=BG_CARD,
                activeforeground=fg,
                activebackground=BG_CARD_HOVER,
                bd=0,
                padx=8,
                pady=3,
                cursor="hand2",
                command=cmd,
            )
        except Exception:
            # In rare environments creating a styled button may fail; fall
            # back to a plain Button creation to avoid crashing UI build.
            btn = tk.Button(parent, text=text, command=cmd)
        return btn

    def _default_settings():
        return {
            "secure_boot_sign": True,
            "persistence_mode": True,
            "drm_modeset": True,
            "wayland_compat": True,
            "open_source_modules": False,
            "coolbits": False,
            "powermizer": "Adaptive",
            "blacklist_nouveau": True,
            "nvreg_psr": False,
            "nvreg_preserve_video_memory": False,
            "nvreg_temp_threshold": 97,
            "nvreg_gpu_recovery": True,
            "prime_mode": "nvidia",
            "power_limit_watts": 0,
            "fan_control_manual": False,
            "fan_speed_pct": 50,
            "clock_offset_core": 0,
            "clock_offset_mem": 0,
            "monitor_interval_sec": 2,
            # Update checker settings
            "enable_update_checks": True,
        }

    def _open_release_page(url):
        """Open *url* in the user's browser, with a xdg-open fallback.

        Kept as a small helper because webbrowser.open can raise OSError in
        some headless or restricted environments; we fall back to xdg-open via
        run_cmd when available.
        """
        if not url:
            return
        try:
            webbrowser.open(url)
        except OSError:
            try:
                # fallback: use run_cmd to call xdg-open
                run_cmd(["xdg-open", url])
            except OSError:
                pass

    def _load_settings():
        """Load persisted GUI settings or return defaults.

        Implemented as a closure-level helper so the GUI class can call
        it during initialization without requiring an instance method.
        """
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                d = _default_settings()
                if isinstance(saved, dict):
                    d.update(saved)
                return d
        except Exception:
            pass
        return _default_settings()

    def _apply_theme():
        """Apply ttk theme/styles for the GUI.

        Kept as a closure-level helper to avoid importing tkinter at module
        import time in headless contexts; ttk is already imported in the
        surrounding scope of this closure.
        """
        try:
            style = ttk.Style()
            style.theme_use("clam")
            style.configure(
                "TProgressbar",
                troughcolor="#1a1c22",
                background=NVIDIA_GREEN,
                bordercolor=BG_DARK,
                lightcolor=NVIDIA_GREEN,
                darkcolor=GREEN_DIM,
            )
            style.configure(
                "TCombobox",
                fieldbackground=BG_INPUT,
                background=BG_INPUT,
                foreground=TEXT_PRIMARY,
                bordercolor=BORDER_LIGHT,
                arrowcolor=NVIDIA_GREEN,
            )
            style.map("TCombobox", fieldbackground=[("readonly", BG_INPUT)], foreground=[("readonly", TEXT_PRIMARY)])
            style.configure(
                "Treeview",
                background=BG_CARD,
                foreground=TEXT_PRIMARY,
                fieldbackground=BG_CARD,
                rowheight=26,
                font=("monospace", 9),
            )
            style.configure("Treeview.Heading", background=BG_PANEL, foreground=TEXT_SECOND, font=("monospace", 9, "bold"))
            style.map("Treeview", background=[("selected", GREEN_BG)], foreground=[("selected", NVIDIA_GREEN)])
        except Exception:
            # If styling fails (rare), don't crash the GUI
            pass

    def _get_run_filename(version):
        return f"NVIDIA-Linux-x86_64-{version}.run"

    def _get_download_dir():
        d = Path.home() / "nvidia-drivers"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d

    def _draw_arc_gauge(canvas, pct, color, label_text="", size=110):
        """Draw a 270° arc gauge on *canvas*.  pct is 0-100."""
        # math is small; import locally to avoid top-level tkinter dependency.
        # pylint: disable=import-outside-toplevel
        import math
        canvas.delete("all")
        pad = 10
        w = size
        cx, cy = w / 2, w / 2
        r = (w - 2 * pad) / 2
        line_w = 8
        # background arc (full 270°)
        start_angle = 135  # degrees (tkinter: 0=3-o'clock, ccw)
        extent = 270
        canvas.create_arc(
            pad, pad, w - pad, w - pad,
            start=start_angle, extent=extent,
            style="arc", outline="#2a2d35", width=line_w,
        )
        # value arc
        # value arc
        val_extent = max(0, min(pct, 100)) / 100.0 * extent
        if val_extent > 0:
            canvas.create_arc(
                pad, pad, w - pad, w - pad,
                start=start_angle, extent=val_extent,
                style="arc", outline=color, width=line_w,
            )
        # centre text
        canvas.create_text(
            cx, cy - 4, text=f"{int(pct)}%", fill=TEXT_PRIMARY,
            font=("Helvetica", 14, "bold"),
        )
        canvas.create_text(
            cx, cy + 14, text=label_text, fill=TEXT_DIM,
            font=("monospace", 7),
        )
        # small tick at 0-mark and end-mark
        for frac in (0, 1):
            angle_rad = math.radians(180 + 45 - frac * 270)
            x0 = cx + (r - line_w) * math.cos(angle_rad)
            y0 = cy - (r - line_w) * math.sin(angle_rad)
            x1 = cx + (r + 2) * math.cos(angle_rad)
            y1 = cy - (r + 2) * math.sin(angle_rad)
            canvas.create_line(x0, y0, x1, y1, fill=TEXT_DIM, width=1)

    def _draw_hbar(canvas, pct, color):
        """Draw a simple horizontal percentage bar on *canvas*.

        This helper is used by instance methods via ``self._draw_hbar`` so
        it's attached to the instance during initialization.
        """
        try:
            canvas.delete("hbar")
            # Query actual width; fallback to widget 'width' option if not yet
            # laid out (winfo_width can be 1 before geometry manager runs).
            w = canvas.winfo_width()
            if not w or w < 10:
                try:
                    w = int(canvas.cget("width"))
                except Exception:
                    w = 200
            pad = 2
            h = 12
            pct_clamped = max(0.0, min(100.0, float(pct or 0)))
            inner_w = int((w - 2 * pad) * (pct_clamped / 100.0))
            # Background track
            canvas.create_rectangle(pad, pad, w - pad, pad + h, fill=BG_CARD_HOVER, width=0, tags=("hbar",))
            # Filled portion
            if inner_w > 0:
                canvas.create_rectangle(pad, pad, pad + inner_w, pad + h, fill=color, width=0, tags=("hbar",))
            # Percentage text
            try:
                canvas.create_text(w / 2, pad + h / 2, text=f"{int(pct_clamped)}%", fill=TEXT_PRIMARY, font=("monospace", 9), tags=("hbar",))
            except Exception:
                pass
        except Exception:
            # GUI drawing must not raise during periodic refreshes
            pass

    def _is_newer_version(current: str, latest: str) -> bool:
        """Return True if *latest* appears newer than *current*.

        Uses a simple numeric component comparison to handle versions like
        '525.60.11' and '530.41.03'. Non-numeric components fall back to
        lexicographic comparison.
        """
        if not current or not latest:
            return False
        try:
            def to_parts(v: str):
                return [int(x) if x.isdigit() else x for x in re.split(r"[.\-+_]", v)]
            return to_parts(latest) > to_parts(current)
        except Exception:
            return latest > current

    class NvidiaDriverManager(tk.Tk):
        """Main GUI application class for NVIDIA Driver Manager."""
        def __init__(self):
            super().__init__()
            self.title("NVIDIA Driver Manager — Advanced")
            self.geometry("1080x720")
            self.minsize(960, 620)
            self.configure(bg=BG_DARK)
            self.is_root = os.geteuid() == 0

            # ── State ──
            self.installed_driver = tk.StringVar(value="Detecting...")
            self.gpu_info = {}
            self.gpu_info_extended = {}
            self.available_drivers = []
            self.cuda_info = {}
            self.vulkan_info = {}
            self.opencl_info = {}
            self.levelzero_info = {}
            self.npu_info = {}
            self.rocm_info = {}
            self.cpu_info = {}
            self.hashcat_info = {}  # {version, cuda_version, backends: [{type,devices:[...]}]}
            self.active_tab = tk.StringVar(value="status")
            self.busy = False
            self.monitoring = False
            self._monitor_id = None
            self.settings: Dict[str, Any] = _load_settings()
            self.processes = []
            self._clock_offset_core_var: tk.IntVar = tk.IntVar(value=0)
            self._clock_offset_mem_var: tk.IntVar = tk.IntVar(value=0)

            # Explicitly initialize attributes that are set later by
            # individual _build_* methods so pylint does not report
            # attribute-defined-outside-init (W0201). These are created
            # during incremental UI construction but having them present
            # on the instance makes the class behavior clearer and
            # improves static analysis.
            self._update_info = None
            self._status_badge = None
            self._kern_os_label = None
            self._kern_ver_label = None
            self._kern_arch_badge = None
            self._kern_info_frame = None
            self._kern_labels = None
            self._gpu_name_label = None
            self._gpu_sub_label = None
            self._drv_info_frame = None
            self._drv_labels = None
            self._gauge_canvases = None
            self._vram_pct_label = None
            self._vram_bar = None
            self._vram_used_lbl = None
            self._vram_total_lbl = None
            self._metrics_frame = None
            self._metric_labels = None
            self._monitor_badge = None
            self._mon_interval_var = None
            self._mon_metrics = None
            self._mon_labels = None
            self._mon_log = None
            self._proc_tree = None
            self._drivers_canvas = None
            self._drivers_inner = None
            self._run_canvas = None
            self._run_inner = None
            self._run_version_var = None
            self._run_file_var = None
            self._cuda_content = None
            self._compute_canvas = None
            self._compute_inner = None
            self._power_info_frame = None
            self._power_labels = None
            self._power_limit_var = None
            self._fan_manual_var = None
            self._fan_speed_var = None
            self._fan_val_label = None
            self._fan_scale = None
            self._fan_apply_btn = None
            self._prime_status_label = None
            self._prime_test_label = None
            self._xorg_coolbits_var = None
            self._xorg_triple_var = None
            self._xorg_comp_pipe_var = None
            self._xorg_modeset_var = None
            self._xorg_allow_empty_var = None
            self._xorg_text = None
            self._nouveau_var = None
            self._nvreg_psr_var = None
            self._nvreg_preserve_var = None
            self._nvreg_recovery_var = None
            self._nvreg_temp_var = None
            self._dkms_text = None
            self._setting_vars = None
            self._pm_var = None
            self._updates_var = None
            self._update_interval_var = None
            self._updates_preview_text = None
            self._term_badge = None
            self._progress_var = None
            self._progress_label = None
            self._progress_bar = None
            self._terminal = None

            # Bind closure helpers that the UI builder expects as
            # instance-callables. These are lightweight closures defined in
            # this outer scope and bound to the instance so calls like
            # ``self._make_action_btn(...)`` work during _build_ui().
            self._make_action_btn = partial(_make_action_btn, self)
            # Bind drawing helpers used by instance methods. _draw_hbar takes
            # (canvas, pct, color) so assign the closure directly rather than
            # partially applying 'self'.
            self._draw_hbar = _draw_hbar

            self._build_ui()
            _apply_theme()

            # Initial data fetch
            threading.Thread(target=self._detect_all, daemon=True).start()

            self.protocol("WM_DELETE_WINDOW", self._on_close)

        def _on_close(self):
            self.monitoring = False
            if self._monitor_id:
                self.after_cancel(self._monitor_id)
            self.destroy()

        def _schedule(self, func: Callable[..., object], ms: int = 0) -> str:
            """Schedule *func* on the Tk main-loop after *ms* milliseconds.

            Thin wrapper around ``tk.Misc.after`` that keeps the type-checker
            happy (``after`` expects variadic ``*args`` which are almost never
            needed in this codebase).
            """
            return self.after(ms, func)  # type: ignore[return-value]

        # ═══════════════════════════════════════════════════════════════════════════
        #  SETTINGS PERSISTENCE
        # ═══════════════════════════════════════════════════════════════════════════

        def _save_settings(self):
            try:
                CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=2)
            except OSError:
                pass

        # ═══════════════════════════════════════════════════════════════════════════
        #  SYSTEM DETECTION
        # ═══════════════════════════════════════════════════════════════════════════
        def _detect_all(self):
            self._log("Detecting system configuration...", "info")
            self._detect_driver()
            self._detect_gpu()
            self._detect_gpu_extended()
            self._detect_available_drivers()
            self._detect_cuda()
            self._detect_vulkan()
            self._detect_opencl()
            self._detect_levelzero()
            self._detect_npu()
            self._detect_rocm()
            self._detect_cpu()
            self._detect_hashcat()
            self._detect_processes()
            self._schedule(self._refresh_ui)

        def _detect_driver(self):
            out, _, rc = run_cmd(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
            if rc == 0 and out:
                version = out.split("\n")[0].strip()
                self.installed_driver.set(version)
                self._log(f"Installed driver: {version}", "success")
            else:
                out2, _, rc2 = run_cmd(["dpkg", "-l", "nvidia-driver-*"])
                if rc2 == 0:
                    for line in out2.split("\n"):
                        if line.startswith("ii"):
                            parts = line.split()
                            if len(parts) >= 3:
                                self.installed_driver.set(parts[2])
                                self._log(f"Installed package: {parts[1]}", "success")
                                return
                self.installed_driver.set("None")
                self._log("No NVIDIA driver detected.", "warn")

        def _detect_gpu(self):
            queries = (
                "gpu_name,gpu_bus_id,memory.total,memory.used,memory.free,"
                "temperature.gpu,fan.speed,clocks.current.graphics,clocks.current.memory,"
                "clocks.max.graphics,clocks.max.memory,"
                "utilization.gpu,utilization.memory,driver_version,vbios_version,"
                "pcie.link.gen.current,pcie.link.width.current,"
                "power.draw,power.limit,power.default_limit,power.max_limit,power.min_limit,"
                "enforced.power.limit,gpu_serial,gpu_uuid"
            )
            out, _, rc = run_cmd(["nvidia-smi", f"--query-gpu={queries}", "--format=csv,noheader,nounits"])
            if rc == 0 and out:
                vals = [v.strip() for v in out.split("\n")[0].split(",")]
                keys = [
                    "name",
                    "bus_id",
                    "vram_total",
                    "vram_used",
                    "vram_free",
                    "temp",
                    "fan",
                    "clock_core",
                    "clock_mem",
                    "clock_core_max",
                    "clock_mem_max",
                    "usage_gpu",
                    "usage_mem",
                    "driver",
                    "vbios",
                    "pcie_gen",
                    "pcie_width",
                    "power_draw",
                    "power_limit",
                    "power_default",
                    "power_max",
                    "power_min",
                    "power_enforced",
                    "serial",
                    "uuid",
                ]
                if len(vals) == len(keys):
                    self.gpu_info = dict(zip(keys, vals))
                else:
                    self.gpu_info = dict(zip(keys[: len(vals)], vals))
                self._log(f"GPU: {self.gpu_info.get('name', 'Unknown')}", "success")
            else:
                out3, _, _ = run_cmd(["lspci"])
                for line in out3.split("\n"):
                    if "NVIDIA" in line.upper():
                        self.gpu_info = {"name": line.split(":")[-1].strip()}
                        self._log(f"GPU (lspci): {self.gpu_info['name']}", "info")
                        break
                if not self.gpu_info:
                    self._log("Could not detect GPU information.", "warn")

        def _detect_gpu_extended(self):
            out, _, rc = run_cmd(["nvidia-smi", "-q"], timeout=10)
            if rc == 0 and out:
                ext = {}
                for line in out.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        k, _, v = line.partition(":")
                        k = k.strip().lower().replace(" ", "_")
                        v = v.strip()
                        if k in (
                            "product_architecture",
                            "compute_cap",
                            "cuda_version",
                            "ecc_mode",
                            "mig_mode",
                            "accounting_mode",
                            "display_active",
                            "display_mode",
                            "persistence_mode",
                            "compute_mode",
                            "total_error_count",
                            "gpu_operation_mode",
                        ):
                            ext[k] = v
                self.gpu_info_extended = ext
            out2, _, rc2 = run_cmd(["nvcc", "--version"])
            if rc2 == 0:
                m = re.search(r"release (\S+),", out2)
                if m:
                    self.gpu_info_extended["nvcc_version"] = m.group(1)

        def _detect_available_drivers(self):
            self._log("Querying available drivers...", "info")
            out, _, rc = run_cmd(["ubuntu-drivers", "devices"])
            if rc == 0 and out:
                self.available_drivers = _parse_ubuntu_drivers(out)
                self._log(f"Found {len(self.available_drivers)} available driver(s).", "success")
            else:
                out2, _, rc2 = run_cmd(["apt", "list", "nvidia-driver-*", "--all-versions"], timeout=30)
                if rc2 == 0 and out2:
                    self.available_drivers = self._parse_apt_drivers(out2)
                    self._log(f"Found {len(self.available_drivers)} driver(s) via apt.", "info")
                else:
                    self._log("Could not query available drivers. Is ubuntu-drivers-common installed?", "warn")

        def _detect_cuda(self):
            info = {}
            out, _, rc = run_cmd(["nvidia-smi"])
            if rc == 0:
                m = re.search(r"CUDA Version:\s*(\S+)", out)
                if m:
                    info["driver_cuda"] = m.group(1)
            out2, _, rc2 = run_cmd(["nvcc", "--version"])
            if rc2 == 0:
                m2 = re.search(r"release (\S+),", out2)
                if m2:
                    info["nvcc"] = m2.group(1)
                m3 = re.search(r"Build (.+)", out2)
                if m3:
                    info["nvcc_build"] = m3.group(1)
            out3, _, rc3 = run_cmd(["dpkg", "-l", "cuda-toolkit-*"])
            if rc3 == 0:
                pkgs = []
                for line in out3.split("\n"):
                    if line.startswith("ii"):
                        parts = line.split()
                        if len(parts) >= 3:
                            pkgs.append(f"{parts[1]} ({parts[2]})")
                info["installed_packages"] = pkgs
            out4, _, rc4 = run_cmd(["dpkg", "-l", "libcudnn*"])
            if rc4 == 0:
                for line in out4.split("\n"):
                    if line.startswith("ii") and "libcudnn" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            info["cudnn"] = parts[2]
                        break
            out5, _, rc5 = run_cmd(["dpkg", "-l", "libnvinfer*"])
            if rc5 == 0:
                for line in out5.split("\n"):
                    if line.startswith("ii") and "libnvinfer" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            info["tensorrt"] = parts[2]
                        break
            out6, _, rc6 = run_cmd(["nvidia-container-cli", "--version"])
            if rc6 == 0 and out6:
                info["container_cli"] = out6.split("\n")[0]
            out7, _, rc7 = run_cmd(["dpkg", "-l", "nvidia-container-toolkit"])
            if rc7 == 0:
                for line in out7.split("\n"):
                    if line.startswith("ii"):
                        parts = line.split()
                        if len(parts) >= 3:
                            info["container_toolkit"] = parts[2]
                        break
            self.cuda_info = info

        def _detect_vulkan(self):
            info: Dict[str, Any] = {"devices": [], "instance_extensions": 0, "instance_layers": 0}

            # Build env with XDG_RUNTIME_DIR set to suppress the spurious warning
            # from vulkaninfo when the variable is absent/invalid.
            vk_env = os.environ.copy()
            if not vk_env.get("XDG_RUNTIME_DIR"):
                uid = os.getuid()
                xdg = f"/run/user/{uid}"
                vk_env["XDG_RUNTIME_DIR"] = xdg if os.path.isdir(xdg) else "/tmp"

            # Prefer --summary (fast, one line per device) then fall back to full output
            out, _, rc = run_cmd(["vulkaninfo", "--summary"], timeout=15, env=vk_env)
            if rc != 0 or not out:
                out, _, rc = run_cmd(["vulkaninfo"], timeout=15, env=vk_env)
            if not (rc == 0 and out):
                self.vulkan_info = info
                self._log("Vulkan not detected (vulkaninfo not found or no Vulkan devices).", "warn")
                return

            # ── Vendor ID → short name ──────────────────────────────────────────
            vendor_map = {
                "0x10de": "NVIDIA",
                "0x1002": "AMD",
                "0x8086": "Intel",
                "0x13b5": "ARM",
                "0x5143": "Qualcomm",
                "0x10005": "Mesa/CPU",
            }
            # ── deviceType → short label ─────────────────────────────────────────
            def _dev_type(raw_dev_type: str) -> str:
                r = raw_dev_type.upper()
                if "DISCRETE" in r:
                    return "dGPU"
                if "INTEGRATED" in r:
                    return "iGPU"
                if "VIRTUAL" in r:
                    return "vGPU"
                if "CPU" in r:
                    return "CPU"
                return raw_dev_type

            cur: dict | None = None

            for raw in out.splitlines():
                line = raw.strip()
                if not line:
                    continue

                # ── Section markers ──────────────────────────────────────────────
                if line.startswith("Devices:") or line == "Devices":
                    continue

                # ── Instance-level counts (before Devices: section) ──────────────
                # "Instance Extensions: count = 27"
                m = re.match(r"Instance Extensions\s*.*count\s*=\s*(\d+)", line, re.I)
                if m:
                    info["instance_extensions"] = int(m.group(1))
                    continue
                m = re.match(r"Instance Layers\s*.*count\s*=\s*(\d+)", line, re.I)
                if m:
                    info["instance_layers"] = int(m.group(1))
                    continue

                # ── Device boundary: "GPU0:", "GPU1:", … ─────────────────────────
                if re.match(r"^GPU\d+\s*:", line):
                    if cur:
                        info["devices"].append(cur)
                    cur = {"label": line.rstrip(":")}
                    continue

                # ── Key = Value lines (vulkaninfo --summary format) ───────────────
                if "=" in line and cur is not None:
                    k_raw, _, v = line.partition("=")
                    k = k_raw.strip().lower().replace(" ", "")
                    v = v.strip()
                    if k == "apiversion":
                        cur["api_version"] = v
                    elif k == "driverversion":
                        cur["driver_version"] = v
                    elif k == "devicename":
                        cur["name"] = v
                    elif k == "devicetype":
                        cur["type"] = _dev_type(v)
                    elif k == "vendorid":
                        cur["vendor_id"] = v
                        cur["vendor"] = vendor_map.get(v.lower(), v)
                    elif k == "deviceid":
                        cur["device_id"] = v
                    elif k == "driverid":
                        cur["driver_id"] = v
                    elif k == "drivername":
                        cur["driver_name"] = v
                    elif k == "driverinfo":
                        cur["driver_info"] = v
                    elif k == "conformanceversion":
                        cur["conformance"] = v
                    continue

                # ── Key: Value lines (full vulkaninfo format) ─────────────────────
                if ":" in line and cur is not None:
                    k_raw, _, v = line.partition(":")
                    k = k_raw.strip().lower().replace(" ", "")
                    v = v.strip()
                    if k == "apiversion":
                        cur.setdefault("api_version", v)
                    elif k == "devicename":
                        cur.setdefault("name", v)
                    elif k == "devicetype":
                        cur.setdefault("type", _dev_type(v))
                    elif k == "vendorid":
                        cur.setdefault("vendor_id", v)
                        cur.setdefault("vendor", vendor_map.get(v.lower(), v))

            if cur:
                info["devices"].append(cur)

            # ── Fallback: grep deviceName if parser found nothing ─────────────────
            if not info["devices"]:
                for raw in out.splitlines():
                    if "deviceName" in raw:
                        _, _, v = raw.partition("=") if "=" in raw else raw.partition(":")
                        v = v.strip()
                        if v:
                            info["devices"].append({"name": v})

            self.vulkan_info = info
            n = len(info["devices"])
            exts = info["instance_extensions"]
            lyrs = info["instance_layers"]
            self._log(
                f"Vulkan: {n} device(s), {exts} instance ext(s), {lyrs} layer(s).",
                "success" if n else "warn",
            )

        def _detect_opencl(self):
            info: Dict[str, Any] = {"platforms": [], "available": False}
            # Try pyopencl first (most detailed)
            try:
                import pyopencl as cl  # type: ignore  # pylint: disable=import-outside-toplevel
                for p in cl.get_platforms():
                    plat: Dict[str, Any] = {
                        "name": p.name.strip(),
                        "vendor": p.vendor.strip(),
                        "version": p.version.strip(),
                        "devices": [],
                    }
                    for d in p.get_devices():
                        # Some pyopencl versions expose a callable `to_string`,
                        # others may provide a different API. Use getattr and
                        # check callable to avoid calling a non-callable object
                        # (and to keep static analyzers happy).
                        to_str = getattr(cl.device_type, "to_string", None)
                        if callable(to_str):
                            try:
                                dtype = to_str(d.type)  # type: ignore[arg-type]
                            except Exception:
                                dtype = str(d.type)
                        else:
                            dtype = str(d.type)
                        plat["devices"].append({
                            "name": d.name.strip(),
                            "type": dtype,
                            "compute_units": d.max_compute_units,
                            "clock_mhz": d.max_clock_frequency,
                            "global_mem_mb": d.global_mem_size // (1024 * 1024),
                            "local_mem_kb": d.local_mem_size // 1024,
                            "opencl_version": d.opencl_c_version.strip() if hasattr(d, "opencl_c_version") else "?",
                        })
                    if not isinstance(info.get("platforms"), list):
                        info["platforms"] = []
                    info["platforms"].append(plat)
                info["available"] = bool(info["platforms"])
                self._log(f"OpenCL: {len(info['platforms'])} platform(s) via pyopencl.", "success")
            except ImportError:
                # Fallback: parse clinfo
                out, _, rc = run_cmd(["clinfo", "-l"], timeout=15)
                if rc != 0 or not out:
                    out, _, rc = run_cmd(["clinfo"], timeout=20)
                if rc == 0 and out:
                    cur_plat: Dict[str, Any] = {}
                    cur_dev: Dict[str, Any] = {}
                    for raw in out.splitlines():
                        line = raw.strip()
                        if not line:
                            continue
                        if line.startswith("Platform #") or line.startswith("Platform Name"):
                            # If current platform has a name, it is a completed platform
                            if cur_plat.get("name"):
                                if cur_dev.get("name"):
                                    cur_plat["devices"].append(cur_dev)
                                    cur_dev = {}
                                if not isinstance(info.get("platforms"), list):
                                    info["platforms"] = []
                                info["platforms"].append(cur_plat)
                            cur_plat = {"name": "", "vendor": "", "version": "", "devices": []}
                            if ":" in line:
                                cur_plat["name"] = line.split(":", 1)[-1].strip()
                        elif line.startswith("Platform Vendor") and cur_plat.get("name"):
                            cur_plat["vendor"] = line.split(":", 1)[-1].strip() if ":" in line else ""
                        elif line.startswith("Platform Version") and cur_plat.get("name"):
                            cur_plat["version"] = line.split(":", 1)[-1].strip() if ":" in line else ""
                        elif line.startswith("Device #") or line.startswith("Device Name"):
                            if cur_dev.get("name") and cur_plat.get("name"):
                                cur_plat["devices"].append(cur_dev)
                            cur_dev = {"name": "", "type": "", "compute_units": "?", "clock_mhz": "?",
                                       "global_mem_mb": "?", "local_mem_kb": "?", "opencl_version": "?"}
                            if ":" in line:
                                cur_dev["name"] = line.split(":", 1)[-1].strip()
                        elif cur_dev.get("name"):
                            if "Device Type" in line and ":" in line:
                                cur_dev["type"] = line.split(":", 1)[-1].strip()
                            elif "Max compute units" in line and ":" in line:
                                cur_dev["compute_units"] = line.split(":", 1)[-1].strip()
                            elif "Max clock frequency" in line and ":" in line:
                                cur_dev["clock_mhz"] = line.split(":", 1)[-1].strip()
                            elif "Global memory size" in line and ":" in line:
                                try:
                                    cur_dev["global_mem_mb"] = int(line.split(":", 1)[1].strip()) // (1024 * 1024)
                                except ValueError:
                                    pass
                            elif "Local memory size" in line and ":" in line:
                                try:
                                    cur_dev["local_mem_kb"] = int(line.split(":", 1)[1].strip()) // 1024
                                except ValueError:
                                    pass
                            elif "OpenCL C version" in line and ":" in line:
                                cur_dev["opencl_version"] = line.split(":", 1)[1].strip()
                    if cur_plat is not None:
                        if cur_dev:
                            cur_plat["devices"].append(cur_dev)
                        if not isinstance(info.get("platforms"), list):
                            info["platforms"] = []
                        info["platforms"].append(cur_plat)
                    info["available"] = bool(info["platforms"])
                    self._log(f"OpenCL: {len(info['platforms'])} platform(s) via clinfo.", "success")
                else:
                    self._log("OpenCL: clinfo not found. Install opencl-info or pyopencl.", "warn")
            except (OSError, ValueError, IndexError) as exc:
                self._log(f"OpenCL detection error: {exc}", "warn")
            self.opencl_info = info

        def _detect_levelzero(self):
            devices: list[dict] = []
            info: Dict[str, Any] = {"available": False, "devices": devices, "raw": "", "version": None}

            # ── Try ze_info first (oneAPI toolkit / compute-runtime ships this)
            ze_info_bin: str | None = None
            ze_info_candidate = shutil.which("ze_info")
            if ze_info_candidate is not None:
                ze_info_bin = str(ze_info_candidate)
            else:
                for alt in ["/opt/intel/oneapi/compiler/latest/linux/bin/ze_info",
                            "/usr/local/bin/ze_info",
                            "/usr/bin/ze_info",
                            "/tmp/oneapi-build/compute-runtime/build/bin/ze_info"]:
                    if os.path.exists(alt):
                        ze_info_bin = alt
                        break

            if ze_info_bin:
                out, _, rc = run_cmd([ze_info_bin], timeout=15)
                if rc == 0 and out:
                    info["available"] = True
                    info["raw"] = out
                    cur: dict | None = None
                    for line in out.splitlines():
                        s = line.strip()
                        if s.startswith("Device :") or "Device Name" in s:
                            if cur:
                                devices.append(cur)
                            cur = {"name": s.split(":", 1)[1].strip() if ":" in s else s}
                        elif cur is not None:
                            if "Device Type" in s and ":" in s:
                                cur["type"] = s.split(":", 1)[1].strip()
                            elif "Vendor ID" in s and ":" in s:
                                cur["vendor_id"] = s.split(":", 1)[1].strip()
                            elif "EU Count" in s and ":" in s:
                                cur["eu_count"] = s.split(":", 1)[1].strip()
                            elif "Number of subdevices" in s and ":" in s:
                                cur["subdevices"] = s.split(":", 1)[1].strip()
                            elif "Memory" in s and "total" in s.lower() and ":" in s:
                                cur["memory"] = s.split(":", 1)[1].strip()
                    if cur:
                        devices.append(cur)
                    self._log(f"Level Zero: {len(devices)} device(s) via ze_info.", "success")

            # ── Fallback: detect via library presence (build-from-source) ─
            if not info["available"]:
                # Check pkg-config
                ver_out, _, rc_pkg = run_cmd(["pkg-config", "--modversion", "level-zero"], timeout=5)
                if rc_pkg == 0 and ver_out:
                    info["available"] = True
                    info["version"] = ver_out.strip()

                # Check ldconfig for the shared library
                ld_out, _, _ = run_cmd(["ldconfig", "-p"], timeout=5)
                if ld_out and "libze_loader" in ld_out:
                    info["available"] = True

                # Try zello_world (built alongside level-zero loader)
                if info["available"] and not devices:
                    zello_candidates = [shutil.which("zello_world"),
                                        "/usr/local/bin/zello_world",
                                        "/tmp/level-zero-build/level-zero/build/bin/zello_world"]
                    for zello in zello_candidates:
                        if zello is None:
                            continue
                        zello = str(zello)
                        if os.path.isfile(zello):
                            z_out, _, z_rc = run_cmd([zello], timeout=10)
                            if z_rc == 0 and z_out:
                                info["raw"] = z_out
                                for zl in z_out.splitlines():
                                    zl = zl.strip()
                                    if "Device" in zl and ":" in zl:
                                        name = zl.split(":", 1)[1].strip()
                                        if name:
                                            devices.append({"name": name})
                            break

                if info["available"]:
                    ver = info.get("version") or "unknown"
                    n = len(devices)
                    msg = f"Level Zero {ver}: library installed"
                    if n:
                        msg += f", {n} device(s)"
                    else:
                        msg += " (ze_info not available for detailed enumeration)"
                    self._log(msg, "success")
                else:
                    self._log("Level Zero: not detected (no library or ze_info found).", "warn")

            self.levelzero_info = info

        def _detect_npu(self):
            info: Dict[str, Any] = {"devices": [], "openvino_devices": [], "driver": None, "openvino_version": None}
            # ── Accel device nodes (Intel NPU kernel driver) ─────────────────────
            import glob  # pylint: disable=import-outside-toplevel
            accel_nodes = glob.glob("/dev/accel/accel*") or glob.glob("/dev/accel*")
            for node in accel_nodes:
                info["devices"].append({"path": node, "type": "Intel NPU (accel node)"})
            # ── lspci scan for NPU/VPU PCI IDs ──────────────────────────────────
            out, _, _ = run_cmd(["lspci", "-nn"], timeout=8)
            if out:
                for line in out.splitlines():
                    low = line.lower()
                    if any(kw in low for kw in
                           ["npu", "vpu", "neural", "movidius", "meteor lake npu",
                            "intel ai", "image processing unit"]):
                        info["devices"].append({"path": line.strip(), "type": "NPU/VPU (lspci)"})
                    if re.search(r"8086:(7d1d|a7a0|643[0-9]|6434|6438|a70f|a72f|a740)", line, re.I):
                        info["devices"].append({"path": line.strip(), "type": "Intel NPU"})
            # ── OpenVINO (2024+ API: openvino.Core; legacy: openvino.runtime.Core) ─
            _ov_core = None
            try:
                from openvino import Core as _OVCore  # type: ignore  # OpenVINO ≥ 2023.1  # pylint: disable=import-outside-toplevel
                _ov_core = _OVCore()
            except ImportError:
                try:
                    from openvino.runtime import Core as _OVCore  # type: ignore  # legacy  # pylint: disable=import-outside-toplevel
                    _ov_core = _OVCore()
                except ImportError:
                    pass
            if _ov_core is not None:
                try:
                    # Version
                    try:
                        cpu_ver = _ov_core.get_versions("CPU").get("CPU")
                        info["openvino_version"] = getattr(cpu_ver, "build_number", None) if cpu_ver else None
                    except (RuntimeError, AttributeError):
                        pass
                    for d in _ov_core.available_devices:
                        dev_entry: dict = {"name": d, "full_name": d}
                        try:
                            props: dict = _ov_core.get_property(d, "SUPPORTED_PROPERTIES")
                            prop_keys = set(props.keys()) if isinstance(props, dict) else set(props)
                            if "FULL_DEVICE_NAME" in prop_keys:
                                dev_entry["full_name"] = _ov_core.get_property(d, "FULL_DEVICE_NAME")
                            if "DEVICE_TYPE" in prop_keys:
                                dev_entry["device_type"] = str(_ov_core.get_property(d, "DEVICE_TYPE"))
                            if "OPTIMIZATION_CAPABILITIES" in prop_keys:
                                caps = _ov_core.get_property(d, "OPTIMIZATION_CAPABILITIES")
                                dev_entry["capabilities"] = caps if isinstance(caps, list) else [str(caps)]
                            if "NUM_STREAMS" in prop_keys:
                                dev_entry["streams"] = str(_ov_core.get_property(d, "NUM_STREAMS"))
                        except (RuntimeError, KeyError, AttributeError):
                            pass
                        info["openvino_devices"].append(dev_entry)
                    self._log(
                        f"OpenVINO {info.get('openvino_version') or ''}: "
                        f"{len(info['openvino_devices'])} device(s) — "
                        + ", ".join(d["name"] for d in info["openvino_devices"]),
                        "success",
                    )
                except (RuntimeError, AttributeError, OSError) as exc:
                    self._log(f"OpenVINO error: {exc}", "warn")
            else:
                self._log("OpenVINO not installed (pip install openvino).", "warn")
            # ── Intel NPU driver package ─────────────────────────────────────────
            out2, _, rc2 = run_cmd(
                ["dpkg", "-l", "intel-npu-driver", "intel-driver-compiler-npu"], timeout=8
            )
            if rc2 == 0:
                for line in out2.splitlines():
                    if line.startswith("ii"):
                        parts = line.split()
                        if len(parts) >= 3:
                            info["driver"] = f"{parts[1]} {parts[2]}"
                            break
            self.npu_info = info

        def _detect_rocm(self):
            info: Dict[str, Any] = {"available": False, "devices": [], "version": None, "opencl_devices": []}
            # rocm-smi
            out, _, rc = run_cmd(["rocm-smi", "--showproductname", "--csv"], timeout=12)
            if rc == 0 and out:
                info["available"] = True
                for line in out.splitlines():
                    if line.startswith("card") or ("GPU" in line and "GPU[" in line):
                        info["devices"].append({"name": line.strip()})
            # rocminfo for richer data
            out2, _, rc2 = run_cmd(["rocminfo"], timeout=15)
            if rc2 == 0 and out2:
                info["available"] = True
                cur: dict | None = None
                for line in out2.splitlines():
                    s = line.strip()
                    if s.startswith("Agent") and "Agent" in s:
                        if cur and cur.get("type") == "GPU":
                            info["devices"].append(cur)
                        cur = {}
                    elif cur is not None:
                        if s.startswith("Name") and ":" in s:
                            cur["name"] = s.split(":", 1)[1].strip()
                        elif s.startswith("Device Type") and ":" in s:
                            cur["type"] = s.split(":", 1)[1].strip()
                        elif s.startswith("Compute Unit") and ":" in s:
                            cur["compute_units"] = s.split(":", 1)[1].strip()
                        elif s.startswith("Max Clock Freq") and ":" in s:
                            cur["clock_mhz"] = s.split(":", 1)[1].strip()
                        elif "Global Mem Size" in s and ":" in s:
                            cur["memory"] = s.split(":", 1)[1].strip()
                if cur and cur.get("type") == "GPU":
                    info["devices"].append(cur)
            # ROCm version
            out3, _, rc3 = run_cmd(["cat", "/opt/rocm/.info/version"], timeout=5)
            if rc3 == 0 and out3:
                info["version"] = out3.strip()
            else:
                out3b, _, rc3b = run_cmd(["rocminfo", "--version"], timeout=5)
                if rc3b == 0 and out3b:
                    m = re.search(r"(\d+\.\d+[.\d]*)", out3b)
                    if m:
                        info["version"] = m.group(1)
            if info["available"]:
                self._log(f"ROCm: {len(info['devices'])} GPU(s), version {info.get('version', '?')}.", "success")
            else:
                self._log("ROCm not detected.", "warn")
            self.rocm_info = info

        def _detect_cpu(self):
            # Delegate CPU detection to gui_detect so it can be linted/tested
            # separately from the large GUI module.
            try:
                info = gui_detect.detect_cpu(run_cmd)
            except Exception:
                # Be defensive; do not let detection crash the GUI.
                info = {
                    "model": "Unknown CPU",
                    "cores_logical": "?",
                }
            self.cpu_info = info
            model = info.get("model") or "Unknown CPU"
            cores = info.get("cores_logical", "?")
            self._log(f"CPU: {model} ({cores} logical CPUs).", "success")

        def _detect_hashcat(self):
            """Parse `hashcat -I` output into structured backend/device info."""
            info: dict = {
                "available": False,
                "version": None,
                "backends": [],   # [{type, version, platforms:[{name,vendor,version,devices:[...]}]}]
            }
            out, _, rc = run_cmd(["hashcat", "-I"], timeout=20)
            if rc != 0 or not out:
                self._log("hashcat not found or failed (-I).", "warn")
                self.hashcat_info = info
                return

            info["available"] = True

            # hashcat (v7.1.2-…) starting …
            m = re.search(r"hashcat\s+\(([^)]+)\)", out)
            if m:
                info["version"] = m.group(1).lstrip("v")

            # ── Key normaliser ────────────────────────────────────────────────────
            def _norm(raw_key: str) -> str:
                n = raw_key.strip().rstrip(".")
                n = re.sub(r"\(s\)", "s", n, flags=re.I)   # Processor(s) → Processors
                n = n.lower()
                n = re.sub(r"[.\s]+", "_", n)              # dots/spaces → underscores
                n = re.sub(r"\W", "", n)                  # drop remaining non-word chars
                return n

            # ── Key-value line regex ──────────────────────────────────────────────
            # Handles: "Name...........: value", "Processor(s)...: 82",
            #          "Memory.Total...: 24123 MB", "Vendor.: NVIDIA", "Version.: OpenCL …"
            kv_re = re.compile(r"^([\w.()\s/]+?)\s*\.+\s*:\s*(.+)$")

            cur_backend:  Dict[str, Any] | None = None
            cur_platform: Dict[str, Any] | None = None
            cur_device:   dict | None = None

            def _flush_device():
                nonlocal cur_device
                if cur_device is not None and cur_platform is not None:
                    cur_platform["devices"].append(cur_device)
                cur_device = None

            def _flush_platform():
                _flush_device()
                if cur_platform is not None and cur_backend is not None:
                    cur_backend["platforms"].append(cur_platform)

            def _flush_backend():
                _flush_platform()
                if cur_backend is not None:
                    info["backends"].append(cur_backend)

            for raw in out.splitlines():
                line = raw.strip()
                if not line:
                    continue

                # ── Backend section header: "CUDA Info:", "OpenCL Info:", … ────────
                m_back = re.match(r"^(CUDA|OpenCL|Metal|HIP|Level[_ ]?Zero)\s+Info\s*:", line, re.I)
                if m_back:
                    _flush_backend()
                    btype = m_back.group(1).upper().replace(" ", "_")
                    cur_backend  = {"type": btype, "platforms": [], "version": None}
                    cur_platform = {"name": btype, "vendor": "", "version": "", "devices": []}
                    cur_device   = None
                    continue

                if cur_backend is None:
                    continue

                # ── Backend-level version: "CUDA.Version.: 13.2" ─────────────────
                m_bver = re.match(r"^(CUDA|OpenCL|HIP|Metal|Level[_ ]?Zero)\.Version\.\s*:\s*(.+)", line, re.I)
                if m_bver:
                    cur_backend["version"] = m_bver.group(2).strip()
                    if cur_platform is not None and not cur_platform.get("version"):
                        cur_platform["version"] = cur_backend["version"]
                    continue

                # ── OpenCL Platform ID #N ─────────────────────────────────────────
                if re.match(r"^OpenCL Platform ID\s+#\d+", line, re.I):
                    _flush_platform()
                    cur_platform = {"name": "", "vendor": "", "version": "", "devices": []}
                    cur_device   = None
                    continue

                # ── Backend Device ID #N (Alias: #M) ─────────────────────────────
                m_dev = re.match(r".*Backend\s+Device\s+ID\s+#(\d+)(.*)", line, re.I)
                if m_dev:
                    _flush_device()
                    alias_m = re.search(r"Alias\s*:\s*#(\d+)", m_dev.group(2))
                    cur_device = {
                        "id":    m_dev.group(1),
                        "alias": alias_m.group(1) if alias_m else None,
                    }
                    continue

                # ── Generic key=value line ────────────────────────────────────────
                m_kv = kv_re.match(line)
                if not m_kv:
                    continue
                k_raw = m_kv.group(1)
                v     = m_kv.group(2).strip()
                k     = _norm(k_raw)

                if cur_device is not None:
                    # Device field — skip the OpenCL C version from overwriting backend ver
                    if k == "opencl_version":
                        cur_device["opencl_c_version"] = v
                    else:
                        cur_device[k] = v

                elif cur_platform is not None:
                    # Platform attribute (no device open yet)
                    if k == "vendor":
                        cur_platform["vendor"] = v
                    elif k == "name":
                        cur_platform["name"] = v
                    elif k == "version":
                        cur_platform["version"] = v
                        # Also set backend version if not already set
                        if cur_backend is not None and not cur_backend.get("version"):
                            cur_backend["version"] = v

            _flush_backend()

            self.hashcat_info = info
            total = sum(len(p["devices"]) for b in info["backends"] for p in b["platforms"])
            self._log(
                f"hashcat {info.get('version','?')}: "
                f"{len(info['backends'])} backend(s), {total} device(s).",
                "success",
            )

        def _detect_processes(self):
            out, _, rc = run_cmd(
                ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"]
            )
            procs = []
            if rc == 0 and out:
                for line in out.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        procs.append({"pid": parts[0], "name": parts[1], "mem": parts[2]})
            self.processes = procs

        @staticmethod
        def _parse_apt_drivers(text):
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
            return sorted(drivers, key=lambda d: int(d["version"]), reverse=True)

        # ═══════════════════════════════════════════════════════════════════════════
        #  BUILD UI
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_ui(self):
            # ── Title bar ──
            title_bar = tk.Frame(self, bg=BG_HEADER, height=48)
            title_bar.pack(fill="x")
            title_bar.pack_propagate(False)

            tk.Label(title_bar, text="\u2B22", font=("monospace", 18), fg=NVIDIA_GREEN, bg=BG_HEADER).pack(
                side="left", padx=(16, 6)
            )
            title_col = tk.Frame(title_bar, bg=BG_HEADER)
            title_col.pack(side="left")
            tk.Label(
                title_col,
                text="NVIDIA Driver Manager \u2014 Advanced",
                font=("Helvetica", 13, "bold"),
                fg=TEXT_PRIMARY,
                bg=BG_HEADER,
            ).pack(anchor="w")
            self._subtitle = tk.Label(title_col, text="UBUNTU LINUX", font=("monospace", 8), fg=TEXT_DIM, bg=BG_HEADER)
            self._subtitle.pack(anchor="w")

            if not self.is_root:
                tk.Label(
                    title_bar,
                    text="\u26A0 Not running as root \u2014 some actions need sudo",
                    font=("monospace", 9),
                    fg=ORANGE,
                    bg=BG_HEADER,
                ).pack(side="right", padx=16)

            # ── Main layout ──
            main_layout = tk.Frame(self, bg=BG_DARK)
            main_layout.pack(fill="both", expand=True)

            # ── Sidebar with scrollable tabs ──
            sidebar_outer = tk.Frame(main_layout, bg=BG_PANEL, width=200)
            sidebar_outer.pack(side="left", fill="y")
            sidebar_outer.pack_propagate(False)

            tk.Label(
                sidebar_outer, text="NAVIGATION", font=("monospace", 8), fg=TEXT_DIM, bg=BG_PANEL, anchor="w"
            ).pack(fill="x", padx=16, pady=(14, 6))

            tabs = [
                ("status", "\u25C8  Status"),
                ("monitor", "\u25C9  Live Monitor"),
                ("processes", "\u25A6  Processes"),
                ("drivers", "\u2B21  Drivers"),
                ("runfile", "\u2B07  NVIDIA.com .run"),
                ("cuda", "\u229E  CUDA / Toolkit"),
                ("vulkan", "\u29BF  Compute & APIs"),
                ("power", "\u26A1 Power / Clocks"),
                ("prime", "\u21CC  PRIME / Optimus"),
                ("xorg", "\u22A1  Xorg Config"),
                ("kernel", "\u269B  Kernel Modules"),
                ("settings", "\u2699  Settings"),
                ("terminal", "\u25B8  Terminal"),
            ]
            self._tab_btns = {}
            for key, label in tabs:
                btn = tk.Label(
                    sidebar_outer,
                    text=label,
                    font=("monospace", 10),
                    fg=TEXT_SECOND,
                    bg=BG_PANEL,
                    anchor="w",
                    padx=16,
                    pady=5,
                    cursor="hand2",
                )
                btn.pack(fill="x")
                btn.bind("<Button-1>", lambda e, k=key: self._switch_tab(k))
                btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=BG_CARD))
                btn.bind(
                    "<Leave>",
                    lambda e, b=btn, k=key: b.configure(bg=GREEN_BG if self.active_tab.get() == k else BG_PANEL),
                )
                self._tab_btns[key] = btn

            # Remove button at bottom
            sidebar_bottom = tk.Frame(sidebar_outer, bg=BG_PANEL)
            sidebar_bottom.pack(side="bottom", fill="x", padx=12, pady=12)
            # Update notice frame (hidden until needed)
            self._update_notice_frame = tk.Frame(sidebar_bottom, bg=BG_PANEL)
            self._update_notice_frame.pack(fill="x", pady=(0, 6))
            self._remove_btn = tk.Button(
                sidebar_bottom,
                text="\u2717  Remove Driver",
                font=("monospace", 10),
                fg=RED,
                bg=BG_PANEL,
                activeforeground=RED,
                activebackground=BG_CARD,
                bd=0,
                highlightthickness=1,
                highlightbackground=RED_BORDER,
                cursor="hand2",
                pady=6,
                command=self._confirm_remove,
            )
            self._remove_btn.pack(fill="x")

            # ── Content area ──
            self._content = tk.Frame(main_layout, bg=BG_DARK)
            self._content.pack(side="left", fill="both", expand=True)

            self._frames = {}
            for key, _ in tabs:
                self._frames[key] = tk.Frame(self._content, bg=BG_DARK)

            self._build_status_tab()
            self._build_monitor_tab()
            self._build_processes_tab()
            self._build_drivers_tab()
            self._build_runfile_tab()
            self._build_cuda_tab()
            self._build_vulkan_tab()
            self._build_power_tab()
            self._build_prime_tab()
            self._build_xorg_tab()
            self._build_kernel_tab()
            self._build_settings_tab()
            self._build_terminal_tab()
            self._switch_tab("status")

            # Update checker initial state
            self._update_info = None
            # Start periodic checks (background)
            try:
                self._start_update_checker()
            except (RuntimeError, OSError):
                pass

        def _switch_tab(self, tab_key):
            if self.active_tab.get() == "monitor" and tab_key != "monitor":
                self.monitoring = False
            self.active_tab.set(tab_key)
            for key, frame in self._frames.items():
                frame.pack_forget()
            self._frames[tab_key].pack(fill="both", expand=True, padx=24, pady=16)
            for key, btn in self._tab_btns.items():
                btn.configure(
                    bg=GREEN_BG if key == tab_key else BG_PANEL, fg=NVIDIA_GREEN if key == tab_key else TEXT_SECOND
                )
            if tab_key == "monitor":
                self.monitoring = True
                self._monitor_tick()
            elif tab_key == "processes":
                threading.Thread(target=self._refresh_processes_ui, daemon=True).start()

        # ─── Utility UI builders ──────────────────────────────────────────────────
        def _update_fan_controls(self):
            """Enable or disable fan controls depending on manual toggle state."""
            enabled = bool(self._fan_manual_var.get())
            state: Literal["normal", "disabled"] = "normal" if enabled else "disabled"
            # Scale widget uses 'state' as well
            if hasattr(self, "_fan_scale") and self._fan_scale:
                try:
                    self._fan_scale.configure(state=state)
                except tk.TclError:
                    pass
            if hasattr(self, "_fan_apply_btn") and self._fan_apply_btn:
                try:
                    self._fan_apply_btn.configure(state=state)
                except tk.TclError:
                    pass

        # ── Update checker helpers ──
        def _fetch_latest_release(self):
            """Fetch latest release info from GitHub API. Returns dict or None."""
            url = "https://api.github.com/repos/kimocoder/nvidia-manager/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "nvidia-manager-updater"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    data = json.load(resp)
                    # Keep the full assets list (contains browser_download_url)
                    return {
                        "tag_name": data.get("tag_name") or data.get("name"),
                        "html_url": data.get("html_url"),
                        "body": data.get("body", ""),
                        "assets": data.get("assets", []),
                        "raw": data,
                    }
            except urllib.error.HTTPError as e:
                # GitHub returns 404 for /releases/latest when there are no releases.
                if getattr(e, "code", None) == 404:
                    self._log("No releases found at GitHub for this repository.", "warn")
                    # Try list releases endpoint as a fallback
                    try:
                        list_url = "https://api.github.com/repos/kimocoder/nvidia-manager/releases"
                        req2 = urllib.request.Request(list_url, headers={"User-Agent": "nvidia-manager-updater"})
                        with urllib.request.urlopen(req2, timeout=10) as resp2:
                            if resp2.status == 200:
                                lst = json.load(resp2)
                                if lst:
                                    # Use first release in list
                                    data = lst[0]
                                    return {
                                        "tag_name": data.get("tag_name") or data.get("name"),
                                        "html_url": data.get("html_url"),
                                        "body": data.get("body", ""),
                                        "assets": data.get("assets", []),
                                        "raw": data,
                                    }
                    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
                        pass
                    # If no releases, try tags endpoint to at least get latest tag
                    try:
                        tags_url = "https://api.github.com/repos/kimocoder/nvidia-manager/tags"
                        req3 = urllib.request.Request(tags_url, headers={"User-Agent": "nvidia-manager-updater"})
                        with urllib.request.urlopen(req3, timeout=10) as resp3:
                            if resp3.status == 200:
                                tags = json.load(resp3)
                                if tags:
                                    t = tags[0]
                                    tag_name = t.get("name")
                                    return {
                                        "tag_name": tag_name,
                                        "html_url": f"https://github.com/kimocoder/nvidia-manager/releases/tag/{tag_name}",
                                        "body": "",
                                        "assets": [],
                                        "raw": t,
                                    }
                    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
                        pass
                    return None
                # For all other HTTP error codes, log the error
                if getattr(e, "code", None) != 404:
                    self._log(f"Update check HTTP error: {e}", "warn")
            except urllib.error.URLError as e:
                self._log(f"Update check network error: {e}", "warn")
            except (ValueError, OSError) as e:
                self._log(f"Update check failed: {e}", "warn")
            return None

        def _on_update_available(self, info):
            """Update the sidebar UI to show a notice above the Remove button.

            Note: Do NOT mark the release as seen here; it will be marked when the
            user Dismisses the notice (or optionally after user action).
            """
            # Save state in memory
            self._update_info = info

            # Update Settings preview if present
            def _update_settings_preview(*_args):
                try:
                    if hasattr(self, "_updates_preview_text") and self._updates_preview_text:
                        self._updates_preview_text.configure(state="normal")
                        self._updates_preview_text.delete("1.0", "end")
                        if info and info.get("body"):
                            body = info.get("body")
                            preview = body.strip()[:1000]
                            self._updates_preview_text.insert("1.0", preview)
                        else:
                            self._updates_preview_text.insert("1.0", "No changelog available.")
                        self._updates_preview_text.configure(state="disabled")
                except tk.TclError:
                    pass

            # Update sidebar notice
            def _render(*_args):
                try:
                    if not hasattr(self, "_update_notice_frame") or self._update_notice_frame is None:
                        return
                    # Clear existing
                    for w in self._update_notice_frame.winfo_children():
                        w.destroy()
                    if not info:
                        return
                    label = tk.Label(
                        self._update_notice_frame,
                        text=f"Update available: {info.get('tag_name')}",
                        font=("monospace", 9),
                        fg=ORANGE,
                        bg=BG_PANEL,
                        anchor="w",
                    )
                    label.pack(side="left", fill="x", expand=True)

                    # Buttons: Open, Install (if .run asset), Dismiss
                    btn_open = tk.Button(
                        self._update_notice_frame,
                        text="Open",
                        font=("monospace", 9),
                        fg=TEXT_PRIMARY,
                        bg=BG_CARD,
                        bd=0,
                        cursor="hand2",
                        command=lambda: _open_release_page(info.get("html_url")),
                    )
                    btn_open.pack(side="right", padx=(4, 0))

                    # If release contains a .run asset, offer Install
                    run_asset: dict | None = None
                    for a in info.get("assets", []) or []:
                        name = a.get("name", "")
                        if name.endswith(".run") or re.search(r"NVIDIA.*\.run", name, re.IGNORECASE):
                            run_asset = a
                            break
                    if run_asset is not None:
                        btn_install = tk.Button(
                            self._update_notice_frame,
                            text="Install",
                            font=("monospace", 9),
                            fg=TEXT_PRIMARY,
                            bg=NVIDIA_GREEN,
                            bd=0,
                            cursor="hand2",
                            command=lambda
                                update_notice_frame_a=None: self._download_and_install_asset(update_notice_frame_a),
                        )
                        btn_install.pack(side="right", padx=(4, 0))

                    btn_dismiss = tk.Button(
                        self._update_notice_frame,
                        text="Dismiss",
                        font=("monospace", 9),
                        fg=TEXT_SECOND,
                        bg=BG_CARD,
                        bd=0,
                        cursor="hand2",
                        command=lambda: self._dismiss_update_notice(info.get("tag_name")),
                    )
                    btn_dismiss.pack(side="right", padx=(4, 0))
                except tk.TclError:
                    pass

            self._schedule(_render)
            self._schedule(_update_settings_preview)

        def _dismiss_update_notice(self, tag_name: str):
            """Mark the given tag as seen and hide the sidebar notice."""
            try:
                if tag_name:
                    self.settings["last_seen_release"] = tag_name
                    self._save_settings()
                # Clear UI
                if hasattr(self, "_update_notice_frame") and self._update_notice_frame:
                    for w in self._update_notice_frame.winfo_children():
                        w.destroy()
                self._update_info = None
                # Also clear settings preview
                if hasattr(self, "_updates_preview_text") and self._updates_preview_text:
                    try:
                        self._updates_preview_text.configure(state="normal")
                        self._updates_preview_text.delete("1.0", "end")
                        self._updates_preview_text.configure(state="disabled")
                    except tk.TclError:
                        pass
            except (tk.TclError, OSError):
                pass

        def _check_for_updates(self, manual=False):
            """Check GitHub for latest release in a background thread."""
            def _worker():
                self._log("Checking for updates...", "info")
                info = self._fetch_latest_release()
                if not info or not info.get("tag_name"):
                    if manual:
                        try:
                            messagebox.showinfo("Updates", "No update information available.")
                        except tk.TclError:
                            pass
                    return
                latest_tag = str(info.get("tag_name") or "")
                current = package_version
                # Only notify if latest is newer than installed and not already dismissed
                last_seen = self.settings.get("last_seen_release", "")
                is_newer = _is_newer_version(current, latest_tag)
                already_seen = latest_tag == last_seen
                if is_newer and not already_seen:
                    self._log(f"Update available: {latest_tag}", "info")
                    self._schedule(lambda: self._on_update_available(info))
                    if manual:
                        try:
                            if messagebox.askyesno("Update available", f"A new release {latest_tag} is available. Open release page?"):
                                _open_release_page(info.get("html_url"))
                        except tk.TclError:
                            pass
                else:
                    self._log("No updates available.", "info")
                    # If user manually checked and no update, show a dialog
                    if manual:
                        try:
                            messagebox.showinfo("Updates", "You are up to date.")
                        except tk.TclError:
                            pass

            threading.Thread(target=_worker, daemon=True).start()

        def _start_update_checker(self):
            """Start periodic background update checks respecting settings."""
            def _loop():
                while True:
                    try:
                        interval = int(self.settings.get("update_check_interval_sec", 3600))
                    except (ValueError, TypeError):
                        interval = 3600
                    time.sleep(max(30, interval))
                    if self.settings.get("enable_update_checks", True):
                        try:
                            self._check_for_updates()
                        except (urllib.error.URLError, OSError):
                            # Transient network or other error: ignore and continue
                            pass

            threading.Thread(target=_loop, daemon=True).start()

        def _build_status_tab(self):
            f = self._frames["status"]

            # ── header row ────────────────────────────────────────────────────
            header = tk.Frame(f, bg=BG_DARK)
            header.pack(fill="x", pady=(0, 8))
            tk.Label(
                header, text="Status", font=("Helvetica", 16, "bold"),
                fg=TEXT_PRIMARY, bg=BG_DARK,
            ).pack(side="left")
            self._status_badge = tk.Label(
                header, text="  DETECTING  ", font=("monospace", 9, "bold"),
                fg=ORANGE, bg="#2a1e00", padx=8, pady=2,
                highlightbackground="#3d2e00", highlightthickness=1,
            )
            self._status_badge.pack(side="left", padx=12)
            self._make_action_btn(
                header, "\u21BB Refresh",
                lambda: threading.Thread(target=self._detect_all, daemon=True).start(),
            ).pack(side="right")

            # ══════════════════════════════════════════════════════════════════
            #  KERNEL & SYSTEM  (first widget — cyan accent left-border)
            # ══════════════════════════════════════════════════════════════════
            kern_outer = tk.Frame(f, bg=CYAN)
            kern_outer.pack(fill="x", pady=(0, 8))
            kern_card = tk.Frame(kern_outer, bg=BG_CARD, padx=18, pady=12)
            kern_card.pack(fill="both", expand=True, padx=(3, 0))  # 3px cyan left-border

            # title row with icon + OS name on the right
            kern_title_row = tk.Frame(kern_card, bg=BG_CARD)
            kern_title_row.pack(fill="x", pady=(0, 8))
            tk.Label(
                kern_title_row, text="\u269B", font=("monospace", 12), fg=CYAN, bg=BG_CARD,
            ).pack(side="left")
            tk.Label(
                kern_title_row, text="  KERNEL & SYSTEM", font=("monospace", 9, "bold"),
                fg=CYAN, bg=BG_CARD,
            ).pack(side="left")
            self._kern_os_label = tk.Label(
                kern_title_row, text="", font=("monospace", 8), fg=TEXT_SECOND, bg=BG_CARD,
            )
            self._kern_os_label.pack(side="right")

            # top row: kernel version (large) + architecture badge
            kern_top = tk.Frame(kern_card, bg=BG_CARD)
            kern_top.pack(fill="x", pady=(0, 6))
            self._kern_ver_label = tk.Label(
                kern_top, text="Detecting\u2026",
                font=("Helvetica", 14, "bold"), fg="#ffffff", bg=BG_CARD, anchor="w",
            )
            self._kern_ver_label.pack(side="left")
            self._kern_arch_badge = tk.Label(
                kern_top, text="", font=("monospace", 8, "bold"),
                fg=PURPLE, bg="#1e1530", padx=6, pady=1,
                highlightbackground="#3a2a5a", highlightthickness=1,
            )
            self._kern_arch_badge.pack(side="left", padx=(10, 0))

            # separator line
            tk.Frame(kern_card, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))

            # detail grid: 4 columns x 2 rows
            self._kern_info_frame = tk.Frame(kern_card, bg=BG_CARD)
            self._kern_info_frame.pack(fill="x")
            self._kern_labels: Dict[str, Any] = {}
            kern_fields = [
                ("Hostname",    NVIDIA_GREEN),
                ("Uptime",      ORANGE),
                ("GCC",         TEXT_SECOND),
                ("Secure Boot", PURPLE),
                ("Init System", CYAN),
                ("Desktop",     TEXT_SECOND),
                ("Display",     TEXT_DIM),
                ("Shell",       TEXT_DIM),
            ]
            for i, (key, color) in enumerate(kern_fields):
                col = i % 4
                row = (i // 4) * 2
                tk.Label(
                    self._kern_info_frame, text=key.upper(),
                    font=("monospace", 7, "bold"), fg=color, bg=BG_CARD,
                ).grid(row=row, column=col, sticky="w", padx=(0, 20))
                lbl = tk.Label(
                    self._kern_info_frame, text="\u2014",
                    font=("monospace", 9, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD,
                )
                lbl.grid(row=row + 1, column=col, sticky="w", padx=(0, 20), pady=(1, 4))
                self._kern_labels[key] = lbl
            for c in range(4):
                self._kern_info_frame.columnconfigure(c, weight=1)

            self._populate_kernel_info()

            # ══════════════════════════════════════════════════════════════════
            #  GPU Identity card (green accent left-border)
            # ══════════════════════════════════════════════════════════════════
            gpu_outer = tk.Frame(f, bg=NVIDIA_GREEN)
            gpu_outer.pack(fill="x", pady=(0, 8))
            gpu_card = tk.Frame(gpu_outer, bg=BG_CARD, padx=20, pady=12)
            gpu_card.pack(fill="both", expand=True, padx=(3, 0))  # 3px green left-border
            tag_row = tk.Frame(gpu_card, bg=BG_CARD)
            tag_row.pack(fill="x")
            tk.Label(
                tag_row, text="\u2B22", font=("monospace", 10), fg=NVIDIA_GREEN, bg=BG_CARD,
            ).pack(side="left")
            tk.Label(
                tag_row, text=" DETECTED GPU", font=("monospace", 8, "bold"),
                fg=NVIDIA_GREEN, bg=BG_CARD, anchor="w",
            ).pack(side="left")
            self._gpu_name_label = tk.Label(
                gpu_card, text="Detecting\u2026",
                font=("Helvetica", 16, "bold"), fg="#ffffff", bg=BG_CARD, anchor="w",
            )
            self._gpu_name_label.pack(fill="x", pady=(4, 1))
            self._gpu_sub_label = tk.Label(
                gpu_card, text="", font=("monospace", 9), fg=TEXT_SECOND, bg=BG_CARD, anchor="w",
            )
            self._gpu_sub_label.pack(fill="x")

            # ── Driver & System card ──────────────────────────────────────────
            drv_frame = _make_card(f, padx=18, pady=12, border_color=BORDER)
            drv_frame.pack(fill="x", pady=(0, 6))
            tk.Label(
                drv_frame, text="\u2699  DRIVER & SYSTEM",
                font=("monospace", 8, "bold"), fg=NVIDIA_GREEN, bg=BG_CARD, anchor="w",
            ).pack(fill="x", pady=(0, 8))
            self._drv_info_frame = tk.Frame(drv_frame, bg=BG_CARD)
            self._drv_info_frame.pack(fill="x")
            self._drv_labels = {}
            drv_keys = ["Version", "CUDA Cap.", "VBIOS", "UUID", "Persistence", "Compute"]
            drv_colors = [NVIDIA_GREEN, ORANGE, TEXT_SECOND, TEXT_DIM, CYAN, PURPLE]
            for i, key in enumerate(drv_keys):
                col = i % 3
                row = (i // 3) * 2
                tk.Label(
                    self._drv_info_frame, text=key.upper(),
                    font=("monospace", 7, "bold"), fg=drv_colors[i], bg=BG_CARD,
                ).grid(row=row, column=col, sticky="w", padx=(0, 28))
                lbl = tk.Label(
                    self._drv_info_frame, text="\u2014",
                    font=("monospace", 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD,
                )
                lbl.grid(row=row + 1, column=col, sticky="w", padx=(0, 28), pady=(1, 6))
                self._drv_labels[key] = lbl

            # ── Gauge row: Temp / GPU% / Mem% / Power ─────────────────────────
            gauge_row = tk.Frame(f, bg=BG_DARK)
            gauge_row.pack(fill="x", pady=(0, 6))
            self._gauge_canvases = {}
            gauge_sz = 120
            gauge_defs = [
                ("temp_gauge",   "TEMPERATURE", CYAN,        0),
                ("gpu_gauge",    "GPU LOAD",    NVIDIA_GREEN, 1),
                ("mem_gauge",    "MEM LOAD",    PURPLE,       2),
                ("power_gauge",  "POWER",       ORANGE,       3),
            ]
            for gid, glabel, gcolor, gcol in gauge_defs:
                card = _make_card(gauge_row, padx=6, pady=8, border_color=BORDER)
                card.grid(row=0, column=gcol, padx=3, pady=0, sticky="nsew")
                tk.Label(
                    card, text=glabel, font=("monospace", 7, "bold"),
                    fg=gcolor, bg=BG_CARD, anchor="n",
                ).pack()
                c = tk.Canvas(card, width=gauge_sz, height=gauge_sz, bg=BG_CARD, highlightthickness=0)
                c.pack(pady=(0, 2))
                self._gauge_canvases[gid] = (c, gcolor, gauge_sz)
                vl = tk.Label(card, text="\u2014", font=("monospace", 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD)
                vl.pack()
                self._gauge_canvases[gid + "_lbl"] = vl
            for c in range(4):
                gauge_row.columnconfigure(c, weight=1)

            # initial blank gauges
            for gid, _, _, _ in gauge_defs:
                cv, clr, sz = self._gauge_canvases[gid]
                _draw_arc_gauge(cv, 0, clr, "", sz)

            # ── VRAM bar ──────────────────────────────────────────────────────
            vram_card = _make_card(f, padx=16, pady=10, border_color=BORDER)
            vram_card.pack(fill="x", pady=(0, 6))
            vram_hdr = tk.Frame(vram_card, bg=BG_CARD)
            vram_hdr.pack(fill="x")
            tk.Label(
                vram_hdr, text="\u25A0  VRAM USAGE", font=("monospace", 8, "bold"),
                fg=CYAN, bg=BG_CARD,
            ).pack(side="left")
            self._vram_pct_label = tk.Label(
                vram_hdr, text="", font=("monospace", 9, "bold"),
                fg=TEXT_PRIMARY, bg=BG_CARD,
            )
            self._vram_pct_label.pack(side="right")
            self._vram_bar = tk.Canvas(
                vram_card, height=16, bg=BG_CARD, highlightthickness=0,
            )
            self._vram_bar.pack(fill="x", pady=(6, 2))
            self._vram_bar.bind("<Configure>", lambda e: self._redraw_vram_bar())
            vram_det = tk.Frame(vram_card, bg=BG_CARD)
            vram_det.pack(fill="x", pady=(2, 0))
            self._vram_used_lbl = tk.Label(
                vram_det, text="Used: \u2014", font=("monospace", 8), fg=TEXT_SECOND, bg=BG_CARD,
            )
            self._vram_used_lbl.pack(side="left")
            self._vram_total_lbl = tk.Label(
                vram_det, text="Total: \u2014", font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD,
            )
            self._vram_total_lbl.pack(side="right")

            # ── Metric grid: clocks / fan / bus ───────────────────────────────
            self._metrics_frame = tk.Frame(f, bg=BG_DARK)
            self._metrics_frame.pack(fill="x", pady=(0, 6))
            self._metric_labels = {}

            metric_grid = [
                [("Core Clock", 0, NVIDIA_GREEN, "\u25B8"),
                 ("Mem Clock",  1, PURPLE, "\u25B8"),
                 ("Fan Speed",  2, CYAN, "\u2741"),
                 ("PCIe",       3, TEXT_SECOND, "\u2194")],
                [("Power Draw", 0, ORANGE, "\u26A1"),
                 ("Power Limit",1, TEXT_DIM, "\u26A1"),
                 ("Bus ID",     2, TEXT_DIM, "\u2338"),
                 ("Mem Util",   3, PURPLE, "\u25A6")],
            ]
            for r, row_data in enumerate(metric_grid):
                for label_text, c, accent, icon in row_data:
                    card = _make_card(self._metrics_frame, padx=12, pady=8, border_color=BORDER)
                    card.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
                    hdr = tk.Frame(card, bg=BG_CARD)
                    hdr.pack(fill="x")
                    tk.Label(
                        hdr, text=icon, font=("monospace", 9), fg=accent, bg=BG_CARD,
                    ).pack(side="left")
                    tk.Label(
                        hdr, text=f" {label_text.upper()}", font=("monospace", 7, "bold"),
                        fg=accent, bg=BG_CARD,
                    ).pack(side="left")
                    val = tk.Label(
                        card, text="\u2014", font=("monospace", 13, "bold"),
                        fg=TEXT_PRIMARY, bg=BG_CARD, anchor="w",
                    )
                    val.pack(fill="x", pady=(3, 0))
                    self._metric_labels[label_text] = val
                for c in range(4):
                    self._metrics_frame.columnconfigure(c, weight=1)



        # ── VRAM bar redraw (called on <Configure> and refresh) ───────────────

        def _redraw_vram_bar(self):
            g = self.gpu_info
            try:
                used = float(g.get("vram_used", 0))
                total = float(g.get("vram_total", 1) or 1)
                pct = used / total * 100.0
            except (ValueError, ZeroDivisionError):
                pct = 0
            color = NVIDIA_GREEN if pct < 70 else (ORANGE if pct < 90 else RED)
            # Call the closure-level drawing helper directly to avoid
            # depending on an instance attribute that might not be present
            # in all runtime import/install situations.
            _draw_hbar(self._vram_bar, pct, color)

        def _populate_kernel_info(self):
            """Gather kernel & OS info and populate the labels."""
            import platform  # pylint: disable=import-outside-toplevel
            try:
                kern_ver = platform.release()
            except OSError:
                kern_ver = "\u2014"
            try:
                arch = platform.machine()
            except OSError:
                arch = "\u2014"
            try:
                hostname = platform.node()
            except OSError:
                hostname = "\u2014"

            # OS pretty name from /etc/os-release
            os_name = "\u2014"
            try:
                with open("/etc/os-release", encoding="utf-8") as fh:
                    for line in fh:
                        if line.startswith("PRETTY_NAME="):
                            os_name = line.split("=", 1)[1].strip().strip('"')
                            break
            except OSError:
                pass

            # Uptime
            uptime_str = "\u2014"
            try:
                with open("/proc/uptime", encoding="utf-8") as fh:
                    secs = int(float(fh.read().split()[0]))
                    days, rem = divmod(secs, 86400)
                    hours, rem = divmod(rem, 3600)
                    mins, _ = divmod(rem, 60)
                    parts = []
                    if days:
                        parts.append(f"{days}d")
                    if hours:
                        parts.append(f"{hours}h")
                    parts.append(f"{mins}m")
                    uptime_str = " ".join(parts)
            except (OSError, ValueError):
                pass

            # GCC version from kernel version string (or gcc --version)
            gcc_str = "\u2014"
            try:
                with open("/proc/version", encoding="utf-8") as fh:
                    pv = fh.read()
                    m = re.search(r"gcc[^)]*?(\d+\.\d+\.\d+)", pv, re.IGNORECASE)
                    if m:
                        gcc_str = m.group(1)
            except OSError:
                pass
            if gcc_str == "\u2014":
                try:
                    out, _, rc = run_cmd(["gcc", "--version"], timeout=5)
                    if rc == 0 and out:
                        m = re.search(r"(\d+\.\d+\.\d+)", out)
                        if m:
                            gcc_str = m.group(1)
                except OSError:
                    pass

            # Secure Boot status
            secboot = "\u2014"
            try:
                sb_out, _, sb_rc = run_cmd(["mokutil", "--sb-state"], timeout=5)
                if sb_rc == 0 and sb_out:
                    if "enabled" in sb_out.lower():
                        secboot = "Enabled"
                    elif "disabled" in sb_out.lower():
                        secboot = "Disabled"
                    else:
                        secboot = sb_out.strip().split("\n")[0]
            except OSError:
                pass

            # Init system
            init_sys = "\u2014"
            try:
                pid1, _, rc1 = run_cmd(["ps", "-p", "1", "-o", "comm="], timeout=5)
                if rc1 == 0 and pid1:
                    init_sys = pid1.strip()
                    if "systemd" in init_sys:
                        init_sys = "systemd"
            except OSError:
                pass

            # Desktop environment
            desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get("DESKTOP_SESSION", "") or "\u2014"

            # Display server (Wayland / X11)
            display = "\u2014"
            xdg_session = os.environ.get("XDG_SESSION_TYPE", "")
            if xdg_session:
                display = xdg_session.capitalize()
            elif os.environ.get("WAYLAND_DISPLAY"):
                display = "Wayland"
            elif os.environ.get("DISPLAY"):
                display = "X11"

            # Shell
            shell = os.environ.get("SHELL", "\u2014")
            if shell and "/" in shell:
                shell = shell.rsplit("/", 1)[-1]

            # ── Populate top-level kernel version + arch badge + OS label ─────
            self._kern_ver_label.configure(text=kern_ver if kern_ver else "\u2014")
            if arch and arch != "\u2014":
                self._kern_arch_badge.configure(text=arch)
            self._kern_os_label.configure(text=os_name if os_name else "\u2014")

            # ── Populate the detail grid ──────────────────────────────────────
            mapping = {
                "Hostname": hostname,
                "Uptime": uptime_str,
                "GCC": gcc_str,
                "Secure Boot": secboot,
                "Init System": init_sys,
                "Desktop": desktop,
                "Display": display,
                "Shell": shell,
            }
            for key, val in mapping.items():
                if key in self._kern_labels:
                    txt = val if val else "\u2014"
                    self._kern_labels[key].configure(text=txt)
                    # Color-code secure boot
                    if key == "Secure Boot":
                        if txt == "Enabled":
                            self._kern_labels[key].configure(fg=NVIDIA_GREEN)
                        elif txt == "Disabled":
                            self._kern_labels[key].configure(fg=ORANGE)

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: LIVE MONITOR
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_monitor_tab(self):
            f = self._frames["monitor"]
            header = tk.Frame(f, bg=BG_DARK)
            header.pack(fill="x", pady=(0, 10))
            tk.Label(header, text="Live GPU Monitor", font=("Helvetica", 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(
                side="left"
            )
            self._monitor_badge = tk.Label(
                header, text="  PAUSED  ", font=("monospace", 9, "bold"), fg=TEXT_DIM, bg=BG_DARK
            )
            self._monitor_badge.pack(side="left", padx=12)

            ctrl = tk.Frame(header, bg=BG_DARK)
            ctrl.pack(side="right")
            tk.Label(ctrl, text="Interval:", font=("monospace", 9), fg=TEXT_SECOND, bg=BG_DARK).pack(side="left")
            self._mon_interval_var = tk.StringVar(value=str(self.settings.get("monitor_interval_sec", 2)))
            spin = tk.Spinbox(
                ctrl,
                from_=1,
                to=30,
                textvariable=self._mon_interval_var,
                width=3,
                font=("monospace", 10),
                bg=BG_INPUT,
                fg=TEXT_PRIMARY,
                buttonbackground=BG_CARD,
                highlightthickness=0,
                bd=1,
                insertbackground=NVIDIA_GREEN,
            )
            spin.pack(side="left", padx=4)
            tk.Label(ctrl, text="sec", font=("monospace", 9), fg=TEXT_SECOND, bg=BG_DARK).pack(side="left")

            self._mon_metrics = tk.Frame(f, bg=BG_DARK)
            self._mon_metrics.pack(fill="x", pady=(0, 10))
            self._mon_labels = {}
            for r, row_data in enumerate(
                [
                    [("Temp", 0), ("Fan", 1), ("Core MHz", 2), ("Mem MHz", 3)],
                    [("GPU %", 0), ("Mem %", 1), ("Power W", 2), ("VRAM MB", 3)],
                ]
            ):
                for label, c in row_data:
                    self._mon_labels[label] = _make_metric(self._mon_metrics, label, row=r, col=c)
                for c in range(4):
                    self._mon_metrics.columnconfigure(c, weight=1)

            tk.Label(f, text="HISTORY", font=("monospace", 8, "bold"), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(
                fill="x", pady=(6, 4)
            )
            self._mon_log = scrolledtext.ScrolledText(
                f,
                bg="#0a0b0d",
                fg=TEXT_SECOND,
                font=("monospace", 9),
                highlightthickness=1,
                highlightbackground=BORDER,
                padx=10,
                pady=8,
                wrap="word",
                state="disabled",
                height=12,
            )
            self._mon_log.pack(fill="both", expand=True)
            self._mon_log.tag_configure("data", foreground=NVIDIA_GREEN)

        def _monitor_tick(self):
            if not self.monitoring:
                self._monitor_badge.configure(text="  PAUSED  ", fg=TEXT_DIM)
                return
            self._monitor_badge.configure(text="  LIVE  ", fg=NVIDIA_GREEN)
            out, _, rc = run_cmd(
                [
                    "nvidia-smi",
                    "--query-gpu=temperature.gpu,fan.speed,clocks.current.graphics,clocks.current.memory,"
                    "utilization.gpu,utilization.memory,power.draw,memory.used",
                    "--format=csv,noheader,nounits",
                ]
            )
            if rc == 0 and out:
                vals = [v.strip() for v in out.split("\n")[0].split(",")]
                if len(vals) >= 8:
                    mapping = {
                        "Temp": f"{vals[0]}\u00B0C",
                        "Fan": f"{vals[1]}%",
                        "Core MHz": vals[2],
                        "Mem MHz": vals[3],
                        "GPU %": f"{vals[4]}%",
                        "Mem %": f"{vals[5]}%",
                        "Power W": f"{vals[6]}W",
                        "VRAM MB": f"{vals[7]} MiB",
                    }
                    for k, v in mapping.items():
                        if k in self._mon_labels:
                            self._mon_labels[k].configure(text=v)
                    ts = datetime.now().strftime("%H:%M:%S")
                    line = (
                        f"{ts}  T:{vals[0]}\u00B0C  Fan:{vals[1]}%  "
                        f"Core:{vals[2]}  Mem:{vals[3]}  GPU:{vals[4]}%  "
                        f"Pwr:{vals[6]}W  VRAM:{vals[7]}M\n"
                    )
                    self._mon_log.configure(state="normal")
                    self._mon_log.insert("end", line, "data")
                    self._mon_log.see("end")
                    self._mon_log.configure(state="disabled")
            try:
                interval = max(1, int(self._mon_interval_var.get())) * 1000
            except ValueError:
                interval = 2000
            self._monitor_id = self._schedule(self._monitor_tick, ms=interval)

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: PROCESSES
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_processes_tab(self):
            f = self._frames["processes"]
            header = tk.Frame(f, bg=BG_DARK)
            header.pack(fill="x", pady=(0, 10))
            tk.Label(header, text="GPU Processes", font=("Helvetica", 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(
                side="left"
            )
            self._make_action_btn(
                header,
                "\u21BB Refresh",
                lambda: threading.Thread(target=self._refresh_processes_ui, daemon=True).start(),
            ).pack(side="right")

            cols = ("pid", "process", "gpu_mem")
            self._proc_tree = ttk.Treeview(f, columns=cols, show="headings", height=14)
            self._proc_tree.heading("pid", text="PID")
            self._proc_tree.heading("process", text="Process")
            self._proc_tree.heading("gpu_mem", text="GPU Memory (MiB)")
            self._proc_tree.column("pid", width=80, anchor="center")
            self._proc_tree.column("process", width=400)
            self._proc_tree.column("gpu_mem", width=140, anchor="center")
            self._proc_tree.pack(fill="both", expand=True, pady=(0, 8))

            btn_row = tk.Frame(f, bg=BG_DARK)
            btn_row.pack(fill="x")
            self._make_action_btn(
                btn_row, "Kill Selected (SIGTERM)", self._kill_selected_process, fg_color=ORANGE
            ).pack(side="left")
            self._make_action_btn(
                btn_row, "Force Kill (SIGKILL)", lambda: self._kill_selected_process(sig=signal.SIGKILL), fg_color=RED
            ).pack(side="left", padx=8)

        def _refresh_processes_ui(self):
            self._detect_processes()

            def _do():
                for item in self._proc_tree.get_children():
                    self._proc_tree.delete(item)
                if self.processes:
                    for p in self.processes:
                        self._proc_tree.insert("", "end", values=(p["pid"], p["name"], p["mem"]))
                else:
                    self._proc_tree.insert("", "end", values=("\u2014", "No GPU processes running", "\u2014"))

            self._schedule(_do)

        def _kill_selected_process(self, sig=signal.SIGTERM):
            sel = self._proc_tree.selection()
            if not sel:
                messagebox.showinfo("No Selection", "Select a process first.")
                return
            vals = self._proc_tree.item(sel[0])["values"]
            pid = str(vals[0])
            if pid == "\u2014":
                return
            name = sig.name if hasattr(sig, "name") else str(sig)
            if messagebox.askyesno("Kill Process", f"Send {name} to PID {pid}?"):
                try:
                    os.kill(int(pid), sig)
                    self._log(f"Sent {name} to PID {pid}", "success")
                except OSError as e:
                    self._log(f"Failed to kill PID {pid}: {e}", "error")
                    messagebox.showerror("Error", str(e))
                threading.Thread(target=self._refresh_processes_ui, daemon=True).start()

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: DRIVERS
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_drivers_tab(self):
            f = self._frames["drivers"]
            header = tk.Frame(f, bg=BG_DARK)
            header.pack(fill="x", pady=(0, 12))
            tk.Label(
                header, text="Available Drivers", font=("Helvetica", 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK
            ).pack(side="left")
            self._make_action_btn(
                header, "\u21BB Refresh", lambda: threading.Thread(target=self._detect_all, daemon=True).start()
            ).pack(side="right")
            self._make_action_btn(header, "Auto-Install (Recommended)", self._auto_install_driver).pack(
                side="right", padx=8
            )

            canvas_frame = tk.Frame(f, bg=BG_DARK)
            canvas_frame.pack(fill="both", expand=True)
            self._drivers_canvas = tk.Canvas(canvas_frame, bg=BG_DARK, highlightthickness=0)
            scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=self._drivers_canvas.yview)
            self._drivers_inner = tk.Frame(self._drivers_canvas, bg=BG_DARK)
            self._drivers_inner.bind(
                "<Configure>", lambda e: self._drivers_canvas.configure(scrollregion=self._drivers_canvas.bbox("all"))
            )
            self._drivers_canvas.create_window((0, 0), window=self._drivers_inner, anchor="nw", tags="inner")
            self._drivers_canvas.configure(yscrollcommand=scrollbar.set)
            self._drivers_canvas.bind("<Configure>", lambda e: self._drivers_canvas.itemconfig("inner", width=e.width))
            self._drivers_canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            tk.Label(
                self._drivers_inner,
                text="Detecting available drivers...",
                font=("monospace", 10),
                fg=TEXT_DIM,
                bg=BG_DARK,
            ).pack(pady=40)

        def _auto_install_driver(self):
            if self.busy:
                return
            if messagebox.askyesno("Auto-Install", "Run 'sudo ubuntu-drivers install'?"):
                self.busy = True
                self._switch_tab("terminal")
                self._term_badge.configure(text="  WORKING  ", fg=ORANGE)
                self._progress_var.set(0)
                self._progress_label.configure(text="Auto-installing recommended driver...")

                def _do():
                    self._log("sudo ubuntu-drivers install", "cmd")
                    rc = run_cmd_stream(["sudo", "ubuntu-drivers", "install"], self._log)
                    self._schedule(lambda: self._progress_var.set(100))
                    if rc == 0:
                        self._log("Auto-install completed. Reboot recommended.", "success")
                        self._finish_action(True)
                    else:
                        self._log("Auto-install failed.", "error")
                        self._finish_action(False)

                threading.Thread(target=_do, daemon=True).start()

        def _populate_drivers_list(self):
            for w in self._drivers_inner.winfo_children():
                w.destroy()
            if not self.available_drivers:
                tk.Label(
                    self._drivers_inner,
                    text="No drivers found.\nsudo apt install ubuntu-drivers-common",
                    font=("monospace", 10),
                    fg=TEXT_DIM,
                    bg=BG_DARK,
                    justify="left",
                ).pack(pady=30, anchor="w")
                return
            cur = self.installed_driver.get()
            for drv in self.available_drivers:
                is_current = cur and drv["version"] in cur
                row = tk.Frame(
                    self._drivers_inner,
                    bg=BG_CARD,
                    highlightbackground=GREEN_SELECT if is_current else BORDER,
                    highlightthickness=1,
                    padx=14,
                    pady=8,
                )
                row.pack(fill="x", pady=2)
                left = tk.Frame(row, bg=BG_CARD)
                left.pack(side="left", fill="x", expand=True)
                top = tk.Frame(left, bg=BG_CARD)
                top.pack(fill="x")
                tk.Label(
                    top,
                    text=drv["package"],
                    font=("monospace", 11, "bold"),
                    fg=NVIDIA_GREEN if is_current else TEXT_PRIMARY,
                    bg=BG_CARD,
                ).pack(side="left")
                badge_fg = NVIDIA_GREEN if drv["type"] == "Production" else CYAN
                tk.Label(top, text=f"  {drv['type']}  ", font=("monospace", 8, "bold"), fg=badge_fg, bg=BG_CARD).pack(
                    side="left", padx=4
                )
                if drv["recommended"]:
                    tk.Label(
                        top, text=" \u2605 RECOMMENDED ", font=("monospace", 8, "bold"), fg=PURPLE, bg=BG_CARD
                    ).pack(side="left")
                if is_current:
                    tk.Label(
                        top, text=" \u25CF INSTALLED ", font=("monospace", 8, "bold"), fg=NVIDIA_GREEN, bg=BG_CARD
                    ).pack(side="left")
                tk.Label(
                    left, text=drv["description"][:100], font=("monospace", 9), fg=TEXT_DIM, bg=BG_CARD, anchor="w"
                ).pack(fill="x", pady=(2, 0))
                if not is_current:
                    _make_green_btn(
                        row, "Install" if cur == "None" else "Switch", lambda d=drv: self._install_driver(d)
                    ).pack(side="right", padx=(8, 0))

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: NVIDIA.COM .RUN FILE INSTALLER
        # ═══════════════════════════════════════════════════════════════════════════

        # Known latest drivers from nvidia.com (updated periodically)
        NVIDIA_RUN_DRIVERS = [
            {
                "version": "595.45.04",
                "branch": "Beta",
                "date": "2026-03-05",
                "size": "423.19 MB",
                "info": "Beta driver with latest bug fixes and new features preview",
            },
            {
                "version": "590.48.01",
                "branch": "New Feature Branch",
                "date": "2025-12-18",
                "size": "416.27 MB",
                "info": "Early adopter access to latest driver features (formerly SLB)",
            },
            {
                "version": "570.133.07",
                "branch": "Production",
                "date": "2025-11-20",
                "size": "395.40 MB",
                "info": "Recommended/Certified production driver",
            },
            {
                "version": "565.77",
                "branch": "Production",
                "date": "2025-09-10",
                "size": "362.50 MB",
                "info": "Previous production branch",
            },
            {
                "version": "550.142",
                "branch": "Legacy",
                "date": "2025-06-15",
                "size": "335.20 MB",
                "info": "Legacy production branch (R550)",
            },
        ]

        # NVIDIA .run file download URL patterns
        NVIDIA_DL_URL = "https://us.download.nvidia.com/XFree86/Linux-x86_64/{ver}/NVIDIA-Linux-x86_64-{ver}.run"
        NVIDIA_DL_URL_ALT = "https://download.nvidia.com/XFree86/Linux-x86_64/{ver}/NVIDIA-Linux-x86_64-{ver}.run"

        def _build_runfile_tab(self):
            f = self._frames["runfile"]

            # Header
            header = tk.Frame(f, bg=BG_DARK)
            header.pack(fill="x", pady=(0, 8))
            tk.Label(
                header, text="NVIDIA.com .run Installer", font=("Helvetica", 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK
            ).pack(side="left")

            desc = tk.Label(
                f,
                text=(
                    "Download and install drivers directly from nvidia.com using .run files.\n"
                    "These include Beta and New Feature Branch drivers not yet in Ubuntu repos.\n"
                    "Warning: .run installers bypass apt and may conflict with packaged drivers."
                ),
                font=("monospace", 9),
                fg=TEXT_SECOND,
                bg=BG_DARK,
                justify="left",
            )
            desc.pack(anchor="w", pady=(0, 10))

            # ── Known drivers from nvidia.com ──
            _make_section_label(f, "AVAILABLE ON NVIDIA.COM (LINUX x86_64)")

            # Scrollable area for driver cards
            run_canvas_frame = tk.Frame(f, bg=BG_DARK)
            run_canvas_frame.pack(fill="both", expand=True, pady=(0, 8))
            self._run_canvas = tk.Canvas(run_canvas_frame, bg=BG_DARK, highlightthickness=0)
            run_sb = tk.Scrollbar(run_canvas_frame, orient="vertical", command=self._run_canvas.yview)
            self._run_inner = tk.Frame(self._run_canvas, bg=BG_DARK)
            self._run_inner.bind(
                "<Configure>", lambda e: self._run_canvas.configure(scrollregion=self._run_canvas.bbox("all"))
            )
            self._run_canvas.create_window((0, 0), window=self._run_inner, anchor="nw", tags="run_inner")
            self._run_canvas.configure(yscrollcommand=run_sb.set)
            self._run_canvas.bind("<Configure>", lambda e: self._run_canvas.itemconfig("run_inner", width=e.width))
            self._run_canvas.pack(side="left", fill="both", expand=True)
            run_sb.pack(side="right", fill="y")

            self._populate_runfile_list()

            # ── Manual version / local file ──
            bottom_frame = tk.Frame(f, bg=BG_DARK)
            bottom_frame.pack(fill="x", pady=(4, 0))

            _make_section_label(bottom_frame, "MANUAL INSTALL")
            manual_card = _make_card(bottom_frame, padx=14, pady=10)
            manual_card.pack(fill="x")

            # Row 1: download by version
            r1 = tk.Frame(manual_card, bg=BG_CARD)
            r1.pack(fill="x", pady=(0, 6))
            tk.Label(r1, text="Driver version:", font=("monospace", 10), fg=TEXT_PRIMARY, bg=BG_CARD).pack(side="left")
            self._run_version_var = tk.StringVar(value="595.45.04")
            tk.Entry(
                r1,
                textvariable=self._run_version_var,
                font=("monospace", 11),
                bg=BG_INPUT,
                fg=NVIDIA_GREEN,
                insertbackground=NVIDIA_GREEN,
                highlightthickness=1,
                highlightbackground=BORDER_LIGHT,
                width=16,
                bd=0,
            ).pack(side="left", padx=8)
            _make_green_btn(
                r1, "Download & Install", lambda: self._download_and_install_run(self._run_version_var.get().strip())
            ).pack(side="left", padx=(4, 0))
            self._make_action_btn(
                r1,
                "Download Only",
                lambda: self._download_run_file(self._run_version_var.get().strip()),
                fg_color=NVIDIA_GREEN,
            ).pack(side="left", padx=6)

            # Separator
            tk.Frame(manual_card, bg=BORDER, height=1).pack(fill="x", pady=6)

            # Row 2: install from local .run file
            r2 = tk.Frame(manual_card, bg=BG_CARD)
            r2.pack(fill="x")
            tk.Label(r2, text="Local .run file:", font=("monospace", 10), fg=TEXT_PRIMARY, bg=BG_CARD).pack(side="left")
            self._run_file_var = tk.StringVar()
            tk.Entry(
                r2,
                textvariable=self._run_file_var,
                font=("monospace", 10),
                bg=BG_INPUT,
                fg=TEXT_PRIMARY,
                insertbackground=NVIDIA_GREEN,
                highlightthickness=1,
                highlightbackground=BORDER_LIGHT,
                width=36,
                bd=0,
            ).pack(side="left", padx=8)
            self._make_action_btn(r2, "Browse...", self._browse_run_file).pack(side="left")
            _make_green_btn(r2, "Install .run", lambda: self._install_local_run(self._run_file_var.get().strip())).pack(
                side="left", padx=8
            )

        def _populate_runfile_list(self):
            for w in self._run_inner.winfo_children():
                w.destroy()

            cur = self.installed_driver.get()

            for drv in self.NVIDIA_RUN_DRIVERS:
                ver = drv["version"]
                is_current = cur and ver in cur

                # Branch color
                branch = drv["branch"]
                if branch == "Beta":
                    badge_fg = ORANGE
                elif branch == "New Feature Branch":
                    badge_fg = CYAN
                elif branch == "Production":
                    badge_fg = NVIDIA_GREEN
                else:
                    badge_fg = TEXT_DIM

                border = GREEN_SELECT if is_current else BORDER
                row = tk.Frame(
                    self._run_inner, bg=BG_CARD, highlightbackground=border, highlightthickness=1, padx=14, pady=10
                )
                row.pack(fill="x", pady=2)

                left = tk.Frame(row, bg=BG_CARD)
                left.pack(side="left", fill="x", expand=True)

                top = tk.Frame(left, bg=BG_CARD)
                top.pack(fill="x")
                tk.Label(
                    top,
                    text=ver,
                    font=("monospace", 12, "bold"),
                    fg=NVIDIA_GREEN if is_current else TEXT_PRIMARY,
                    bg=BG_CARD,
                ).pack(side="left")
                tk.Label(top, text=f"  {branch}  ", font=("monospace", 8, "bold"), fg=badge_fg, bg=BG_CARD).pack(
                    side="left", padx=4
                )
                if is_current:
                    tk.Label(
                        top, text=" \u25CF INSTALLED ", font=("monospace", 8, "bold"), fg=NVIDIA_GREEN, bg=BG_CARD
                    ).pack(side="left")

                detail_text = f"{drv['date']}  \u2022  {drv['size']}  \u2022  {drv['info']}"
                tk.Label(
                    left, text=detail_text, font=("monospace", 9), fg=TEXT_DIM, bg=BG_CARD, anchor="w"
                ).pack(fill="x", pady=(2, 0))

                if not is_current:
                    btn_frame = tk.Frame(row, bg=BG_CARD)
                    btn_frame.pack(side="right")
                    _make_green_btn(btn_frame, "Install", lambda v=ver: self._download_and_install_run(v)).pack(
                        pady=(0, 2)
                    )
                    self._make_action_btn(
                        btn_frame, "Download", lambda v=ver: self._download_run_file(v), fg_color=TEXT_SECOND
                    ).pack()

        def _get_run_url(self, version):
            """Construct the NVIDIA .run file download URL."""
            return self.NVIDIA_DL_URL.format(ver=version)

        def _browse_run_file(self):
            path = filedialog.askopenfilename(
                title="Select NVIDIA .run installer",
                filetypes=[("NVIDIA Installer", "*.run"), ("All Files", "*.*")],
                initialdir=str(_get_download_dir()),
            )
            if path:
                self._run_file_var.set(path)

        def _download_run_file(self, version, callback=None):
            """Download .run file from nvidia.com. Calls callback(filepath) on success."""
            if not version:
                messagebox.showinfo("Input Required", "Enter a driver version number.")
                return
            if self.busy:
                return

            url = self._get_run_url(version)
            filename = _get_run_filename(version)
            dest = _get_download_dir() / filename

            if dest.exists():
                if callback:
                    callback(str(dest))
                    return
                messagebox.showinfo("Already Downloaded", f"{filename} already exists at:\n{dest}")
                return

            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  DOWNLOADING  ", fg=CYAN)
            self._progress_var.set(0)
            self._progress_label.configure(text=f"Downloading {filename}...")

            def _do_download():
                # chunk_size is local to this function; no global needed
                self._log(f"Downloading: {url}", "cmd")
                self._log(f"Destination: {dest}", "info")

                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "NVIDIA-Driver-Manager/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        total = int(resp.headers.get("Content-Length", 0))
                        downloaded = 0
                        chunk_size = 1024 * 256  # 256KB chunks

                        self._log(f"File size: {total / 1024 / 1024:.1f} MB" if total else "File size: unknown", "info")

                        tmp_path = str(dest) + ".tmp"
                        with open(tmp_path, "wb") as fp:
                            while True:
                                chunk = resp.read(chunk_size)
                                if not chunk:
                                    break
                                fp.write(chunk)
                                downloaded += len(chunk)
                                if total > 0:
                                    pct = min(99, int(downloaded * 100 / total))
                                    # schedule UI update on main thread
                                    self._schedule(lambda p=pct: self._progress_var.set(p))
                                if downloaded % (1024 * 1024 * 10) < chunk_size:
                                    self._log(
                                        f"  {downloaded / 1024 / 1024:.0f} MB / {total / 1024 / 1024:.0f} MB", "info"
                                    )

                    # Rename tmp to final
                    shutil.move(tmp_path, str(dest))
                    # Make executable
                    os.chmod(str(dest), 0o755)

                    # Finalize progress and notify on main thread
                    self._schedule(lambda: self._progress_var.set(100))
                    self._log("Download finished.", "success")
                    if callback:
                        self._schedule(lambda: callback(str(dest)))

                except (urllib.error.URLError, OSError, ValueError) as e:
                    try:
                        tmp_path = str(dest) + ".tmp"
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except OSError:
                        pass
                    self._log(f"Download failed: {e}", "error")
                    if callback:
                        self._schedule(lambda: callback(None))
                finally:
                    # ensure busy flag is cleared
                    self.busy = False

            threading.Thread(target=_do_download, daemon=True).start()

        def _download_and_install_run(self, version):
            """Download .run file then install it."""
            if not version:
                messagebox.showinfo("Input Required", "Enter a driver version number.")
                return
            if self.busy:
                return

            dest = _get_download_dir() / _get_run_filename(version)
            if dest.exists():
                # Already downloaded, go straight to install
                if messagebox.askyesno(
                    "Install Driver",
                    f"Install NVIDIA driver {version} from .run file?\n\n"
                    f"File: {dest}\n\n"
                    f"This will:\n"
                    f"  1. Stop display manager\n"
                    f"  2. Unload current NVIDIA modules\n"
                    f"  3. Run the NVIDIA installer\n\n"
                    f"Your display may go black during installation.",
                ):
                    self._install_local_run(str(dest))
                return

            if not messagebox.askyesno(
                "Download & Install",
                f"Download driver {version} from nvidia.com and install?\n\n"
                f"URL: {self._get_run_url(version)}\n\n"
                f"After download, the installer will run. Your display may go black.",
            ):
                return

            # Download first, then install via callback
            self._download_run_file(version, callback=lambda path: self._schedule(lambda: self._install_local_run(path)))

        def _install_local_run(self, filepath):
            """Install a local .run file with comprehensive preflight checks."""
            if not filepath:
                messagebox.showinfo("No File", "Select or enter a .run file path.")
                return
            if not os.path.isfile(filepath):
                messagebox.showerror("Not Found", f"File not found:\n{filepath}")
                return
            if self.busy:
                return

            if not messagebox.askyesno(
                "Install .run Driver",
                f"Install NVIDIA driver from:\n{filepath}\n\n"
                f"Pre-flight checks will run first to detect issues.\n"
                f"Current driver will be replaced. Reboot required.",
            ):
                return

            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  PRE-FLIGHT  ", fg=CYAN)
            self._progress_var.set(0)
            self._progress_label.configure(text="Running pre-flight checks...")

            def _do_preflight_and_install():
                # ── PHASE 1: PRE-FLIGHT CHECKS ──
                self._log("=" * 60, "info")
                self._log("PRE-FLIGHT DIAGNOSTICS", "info")
                self._log("=" * 60, "info")
                issues = []  # Fatal blockers
                warnings = []  # Non-fatal warnings
                fixes_applied = []

                self._schedule(lambda: self._progress_var.set(2))

                # ── Check 1: Running as root ──
                self._log("[1/9] Checking privileges...", "info")
                if os.geteuid() != 0:
                    issues.append("Not running as root. The .run installer requires root (sudo).")
                else:
                    self._log("  Root privileges: OK", "success")

                # ── Check 2: Kernel version & compatibility ──
                self._log("[2/9] Checking kernel version...", "info")
                kernel_ver, _, _ = run_cmd(["uname", "-r"])
                self._log(f"  Kernel: {kernel_ver}", "info")

                kernel_is_rc = "-rc" in kernel_ver
                kernel_major = 0
                km = re.match(r"(\d+)\.(\d+)", kernel_ver)
                if km:
                    kernel_major = int(km.group(1))

                if kernel_is_rc:
                    issues.append(
                        f"Kernel {kernel_ver} is a release candidate (-rc).\n"
                        f"         NVIDIA proprietary drivers typically do NOT support -rc kernels.\n"
                        f"         The VMA, objtool, and mm subsystem APIs change frequently in -rc builds.\n"
                        f"         FIX: Boot a stable release kernel (e.g. 6.12.x or 6.13.x).\n"
                        f"              List installed kernels: dpkg --list 'linux-image-*'\n"
                        f"              Or install one: sudo apt install linux-image-generic"
                    )

                if kernel_major >= 7:
                    issues.append(
                        f"Kernel {kernel_ver} (major version {kernel_major}) is very new.\n"
                        f"         NVIDIA 595.45.04 may not have patches for kernel 7.x API changes:\n"
                        f"         - VMA_LOCK_OFFSET removed/changed in mm subsystem\n"
                        f"         - __is_vma_write_locked() signature changed (2 args -> 1 arg)\n"
                        f"         - objtool MITIGATION_RETHUNK enforcement on naked returns\n"
                        f"         FIX: Use kernel 6.12.x or 6.13.x, or wait for a newer NVIDIA driver."
                    )

                if not kernel_is_rc and kernel_major < 7:
                    self._log(f"  Kernel compatibility: OK (stable {kernel_ver})", "success")

                self._schedule(lambda: self._progress_var.set(5))

                # ── Check 3: Kernel headers ──
                self._log("[3/9] Checking kernel headers...", "info")
                headers_path = f"/lib/modules/{kernel_ver}/build"
                if os.path.isdir(headers_path):
                    self._log(f"  Headers found: {headers_path}", "success")
                else:
                    self._log(f"  Headers missing: {headers_path}", "error")
                    # Try auto-fix
                    self._log("  Attempting to install kernel headers...", "warn")
                    rc = run_cmd_stream(
                        ["sudo", "apt", "install", "-y", f"linux-headers-{kernel_ver}"], self._log, timeout=120
                    )
                    if rc == 0 and os.path.isdir(headers_path):
                        fixes_applied.append(f"Installed linux-headers-{kernel_ver}")
                        self._log("  Headers installed successfully.", "success")
                    else:
                        issues.append(
                            f"Kernel headers not found for {kernel_ver}.\n"
                            f"         FIX: sudo apt install linux-headers-{kernel_ver}\n"
                            f"         Or:  sudo apt install linux-headers-generic"
                        )

                self._schedule(lambda: self._progress_var.set(8))

                # ── Check 4: Build toolchain (gcc, make) ──
                self._log("[4/9] Checking build tools...", "info")
                missing_build = []
                for tool in ["gcc", "make", "cc"]:
                    _, _, rc = run_cmd(["which", tool])
                    if rc != 0:
                        missing_build.append(tool)
                if missing_build:
                    self._log(f"  Missing: {', '.join(missing_build)}", "error")
                    self._log("  Attempting to install build-essential...", "warn")
                    rc = run_cmd_stream(["sudo", "apt", "install", "-y", "build-essential"], self._log, timeout=120)
                    if rc == 0:
                        fixes_applied.append("Installed build-essential (gcc, make)")
                        self._log("  Build tools installed.", "success")
                    else:
                        issues.append(
                            f"Build tools missing: {', '.join(missing_build)}.\n"
                            f"         FIX: sudo apt install build-essential"
                        )
                else:
                    # Check compiler version vs kernel
                    gcc_ver_out, _, _ = run_cmd(["gcc", "--version"])
                    gcc_first = gcc_ver_out.split("\n")[0] if gcc_ver_out else "unknown"
                    self._log(f"  gcc: {gcc_first}", "success")

                    # Check if kernel was built with same gcc
                    proc_ver = ""
                    try:
                        with open(f"/lib/modules/{kernel_ver}/build/include/generated/compile.h", encoding="utf-8", errors="ignore") as fh:
                            proc_ver = fh.read()
                    except OSError:
                        try:
                            with open("/proc/version", encoding="utf-8") as fh:
                                proc_ver = fh.read()
                        except OSError:
                            pass
                    if proc_ver:
                        km_gcc = re.search(r"gcc.*?(\d+\.\d+\.\d+)", proc_ver)
                        my_gcc = re.search(r"(\d+\.\d+\.\d+)", gcc_first)
                        if km_gcc and my_gcc:
                            k_gcc = km_gcc.group(1)
                            u_gcc = my_gcc.group(1)
                            if k_gcc.split(".")[0] != u_gcc.split(".")[0]:
                                warnings.append(
                                    f"GCC major version mismatch: kernel={k_gcc}, yours={u_gcc}.\n"
                                    f"         This may cause module build failures."
                                )
                            elif k_gcc != u_gcc:
                                self._log(f"  Note: minor gcc version diff (kernel={k_gcc}, yours={u_gcc})", "info")
                                self._log("  Using --no-cc-version-check to allow this.", "info")

                self._schedule(lambda: self._progress_var.set(11))

                # ── Check 5: pahole / dwarves ──
                self._log("[5/9] Checking pahole (dwarves)...", "info")
                _, _, rc = run_cmd(["which", "pahole"])
                if rc != 0:
                    self._log("  pahole not found. Required for BTF generation.", "error")
                    self._log("  Installing dwarves package...", "warn")
                    rc = run_cmd_stream(["sudo", "apt", "install", "-y", "dwarves"], self._log, timeout=60)
                    if rc == 0:
                        fixes_applied.append("Installed dwarves (pahole)")
                        self._log("  pahole installed successfully.", "success")
                    else:
                        warnings.append(
                            "pahole (dwarves) not installed. BTF generation will fail.\n"
                            "         FIX: sudo apt install dwarves"
                        )
                else:
                    pahole_ver, _, _ = run_cmd(["pahole", "--version"])
                    self._log(f"  pahole: {pahole_ver}", "success")

                self._schedule(lambda: self._progress_var.set(14))

                # ── Check 6: initramfs tools ──
                self._log("[6/9] Checking initramfs tools...", "info")
                has_initramfs = False
                for tool in ["update-initramfs", "dracut", "mkinitcpio"]:
                    _, _, rc = run_cmd(["which", tool])
                    if rc == 0:
                        self._log(f"  Found: {tool}", "success")
                        has_initramfs = True
                        break
                if not has_initramfs:
                    warnings.append(
                        "No initramfs tool found (update-initramfs/dracut/mkinitcpio).\n"
                        "         Installer may not be able to update initrd."
                    )

                # ── Check 7: X server running ──
                self._log("[7/9] Checking for running X server...", "info")
                x_lock = Path("/tmp/.X0-lock")
                x_running = False
                if x_lock.exists():
                    x_running = True
                    try:
                        pid = x_lock.read_text(encoding="utf-8").strip()
                        self._log(f"  X server running (PID {pid}). Will stop display manager before install.", "warn")
                    except OSError:
                        self._log("  X server appears to be running.", "warn")
                else:
                    self._log("  No X server detected: OK", "success")

                self._schedule(lambda: self._progress_var.set(16))

                # ── Check 8: Conflicting NVIDIA packages ──
                self._log("[8/9] Checking for conflicting NVIDIA apt packages...", "info")
                pkg_out, _, pkg_rc = run_cmd(["dpkg", "-l", "nvidia-driver-*"])
                conflicting = []
                if pkg_rc == 0:
                    for line in pkg_out.split("\n"):
                        if line.startswith("ii"):
                            parts = line.split()
                            if len(parts) >= 2:
                                conflicting.append(parts[1])
                if conflicting:
                    warnings.append(
                        f"Existing NVIDIA apt packages detected: {', '.join(conflicting[:5])}\n"
                        f"         .run installers can conflict with apt-managed drivers.\n"
                        f"         Recommended: sudo apt purge 'nvidia-*' before .run install."
                    )
                    self._log(f"  Found {len(conflicting)} NVIDIA package(s) via apt", "warn")
                else:
                    self._log("  No conflicting apt packages: OK", "success")

                # ── Check 9: Disk space ──
                self._log("[9/9] Checking disk space...", "info")
                try:
                    st = os.statvfs("/")
                    free_mb = (st.f_bavail * st.f_frsize) / (1024 * 1024)
                    if free_mb < 2000:
                        warnings.append(f"Low disk space: {free_mb:.0f} MB free. Need ~2 GB for build.")
                    else:
                        self._log(f"  Free space: {free_mb / 1024:.1f} GB: OK", "success")
                except OSError:
                    pass

                # ── REPORT ──
                self._log("", "info")
                self._log("=" * 60, "info")
                self._log("PRE-FLIGHT RESULTS", "info")
                self._log("=" * 60, "info")

                if fixes_applied:
                    self._log(f"Auto-fixed {len(fixes_applied)} issue(s):", "success")
                    for fix in fixes_applied:
                        self._log(f"  \u2713 {fix}", "success")

                if warnings:
                    self._log(f"\u26A0 {len(warnings)} warning(s):", "warn")
                    for w in warnings:
                        for wline in w.split("\n"):
                            self._log(f"  {wline}", "warn")

                if issues:
                    self._log(f"\u2717 {len(issues)} FATAL issue(s) - installation will likely fail:", "error")
                    for iss in issues:
                        for iline in iss.split("\n"):
                            self._log(f"  {iline}", "error")
                    self._log("", "info")
                    self._log("Installation ABORTED due to fatal issues above.", "error")
                    self._log("Fix the issues and try again. Most common solution:", "info")
                    self._log("  Boot a stable kernel: select one from GRUB at boot time.", "info")
                    self._log("  List kernels: dpkg --list 'linux-image-*' | grep '^ii'", "info")
                    self._schedule(lambda: self._progress_var.set(100))
                    self.busy = False
                    self._schedule(lambda: self._term_badge.configure(text="  BLOCKED  ", fg=RED))
                    return

                if warnings:
                    self._log("", "info")
                    self._log("Warnings found but proceeding with installation...", "warn")
                else:
                    self._log("All checks passed!", "success")

                self._log("", "info")

                # ── PHASE 2: INSTALL ──
                self._schedule(lambda: self._term_badge.configure(text="  INSTALLING .RUN  ", fg=ORANGE))
                self._schedule(
                    lambda: self._progress_label.configure(text=f"Installing {os.path.basename(filepath)}...")
                )

                # Ensure executable
                self._log(f"chmod +x {filepath}", "cmd")
                os.chmod(filepath, 0o755)
                self._schedule(lambda: self._progress_var.set(22))

                # Stop display manager
                if x_running:
                    self._log("Stopping display manager...", "warn")
                    for dm in ["gdm3", "gdm", "sddm", "lightdm", "xdm"]:
                        run_cmd(["sudo", "systemctl", "stop", dm], timeout=10)
                    # Also kill X directly if lock file still exists
                    if Path("/tmp/.X0-lock").exists():
                        try:
                            xpid = Path("/tmp/.X0-lock").read_text(encoding="utf-8").strip()
                            self._log(f"  Killing X server PID {xpid}...", "warn")
                            run_cmd(["sudo", "kill", xpid], timeout=5)
                            time.sleep(2)
                        except OSError:
                            pass
                self._schedule(lambda: self._progress_var.set(26))

                # Unload nvidia modules
                self._log("Unloading NVIDIA kernel modules...", "info")
                for mod in ["nvidia_drm", "nvidia_modeset", "nvidia_uvm", "nvidia"]:
                    _, err, rc = run_cmd(["sudo", "rmmod", mod], timeout=5)
                    if rc == 0:
                        self._log(f"  Unloaded {mod}", "success")
                    else:
                        self._log(f"  {mod}: {err}" if err else f"  {mod} not loaded", "info")
                self._schedule(lambda: self._progress_var.set(30))

                # Build installer command
                cmd = [
                    "sudo",
                    filepath,
                    "--silent",
                    "--dkms",
                    "--no-cc-version-check",
                    "--no-questions",
                    "--ui=none",
                    "--disable-nouveau",
                ]

                if self.settings.get("open_source_modules"):
                    cmd.append("--open-kernel")
                if not self.settings.get("drm_modeset"):
                    cmd.append("--no-drm")

                self._log(" ".join(cmd), "cmd")
                self._log("Running NVIDIA installer (this may take several minutes)...", "warn")
                self._schedule(lambda: self._progress_var.set(35))

                rc = run_cmd_stream(cmd, self._log, timeout=900)
                self._schedule(lambda: self._progress_var.set(90))

                if rc == 0:
                    self._log("NVIDIA .run installer completed successfully.", "success")

                    if self.settings.get("persistence_mode"):
                        self._log("Enabling nvidia-persistenced...", "cmd")
                        run_cmd(["sudo", "systemctl", "enable", "--now", "nvidia-persistenced"])

                    if self.settings.get("drm_modeset"):
                        try:
                            subprocess.run(
                                [
                                    "sudo",
                                    "bash",
                                    "-c",
                                    'echo "options nvidia-drm modeset=1" > /etc/modprobe.d/nvidia-drm-modeset.conf',
                                ],
                                capture_output=True,
                                timeout=10,
                                check=False,
                            )
                            self._log("DRM modesetting configured.", "success")
                        except subprocess.SubprocessError:
                            pass

                    if self.settings.get("blacklist_nouveau"):
                        try:
                            # Use a shorter command literal to avoid exceeding line length
                            blacklist_cmd = (
                                'echo -e "blacklist nouveau\\noptions nouveau modeset=0" '
                                "> /etc/modprobe.d/blacklist-nouveau.conf"
                            )
                            subprocess.run(
                                ["sudo", "bash", "-c", blacklist_cmd],
                                capture_output=True,
                                timeout=10,
                                check=False,
                            )
                        except subprocess.SubprocessError:
                            pass

                    # Update initramfs
                    self._log("Updating initramfs...", "info")
                    run_cmd(["sudo", "update-initramfs", "-u"], timeout=120)

                    self._schedule(lambda: self._progress_var.set(100))
                    self._log("Driver installed. A system reboot is strongly recommended.", "warn")
                    self._log("Run 'nvidia-smi' after reboot to verify.", "info")
                    self._finish_action(True)
                else:
                    self._schedule(lambda: self._progress_var.set(95))
                    self._log(f"Installer exited with code {rc}.", "error")
                    self._log("", "info")

                    # ── POST-FAILURE ANALYSIS ──
                    # Parse /var/log/nvidia-installer.log for specific errors
                    self._log("Analyzing /var/log/nvidia-installer.log for root cause...", "info")
                    try:
                        with open("/var/log/nvidia-installer.log", encoding="utf-8", errors="ignore") as logf:
                            log_text = logf.read()

                        if "VMA_LOCK_OFFSET" in log_text:
                            self._log("ROOT CAUSE: Kernel VMA API incompatibility", "error")
                            self._log("  Kernel 7.x changed VMA_LOCK_OFFSET and __is_vma_write_locked().", "error")
                            self._log("  The NVIDIA driver does not yet support this kernel.", "error")
                            self._log("  FIX: Boot a stable 6.x kernel from GRUB.", "info")

                        if "MITIGATION_RETHUNK" in log_text or "naked.*return" in log_text:
                            self._log("ROOT CAUSE: objtool MITIGATION_RETHUNK errors", "error")
                            self._log("  Kernel enforces retbleed mitigations on module code.", "error")
                            self._log("  NVIDIA's precompiled blobs use 'naked' returns not allowed.", "error")
                            self._log("  FIX: Use a kernel without strict rethunk enforcement,", "info")
                            self._log("  or wait for NVIDIA to release a compatible driver.", "info")

                        if "pahole" in log_text and ("not found" in log_text or "version differs" in log_text):
                            self._log("CONTRIBUTING: pahole (dwarves) missing or version mismatch", "warn")
                            self._log("  FIX: sudo apt install dwarves", "info")

                        if "compiler differs" in log_text:
                            self._log("CONTRIBUTING: Compiler version mismatch", "warn")
                            self._log("  Kernel was built with a different GCC patch version.", "info")
                            self._log("  Using --no-cc-version-check should bypass this.", "info")

                        if "nv-mmap.c" in log_text and "error:" in log_text:
                            self._log("CONTRIBUTING: nv-mmap.c build errors", "error")
                            self._log("  The mm/VMA kernel API changed in your kernel version.", "error")

                    except FileNotFoundError:
                        self._log("  Could not read /var/log/nvidia-installer.log", "warn")
                    except OSError as e:
                        self._log(f"  Error reading log: {e}", "warn")

                    self._log("", "info")
                    self._log("SUMMARY: Installation failed. Most likely your kernel is too new", "error")
                    self._log("for this NVIDIA driver. Solutions:", "info")
                    self._log("  1. Boot a stable kernel: pick 6.12.x or 6.13.x from GRUB", "info")
                    self._log("  2. Install via apt instead: sudo ubuntu-drivers install", "info")
                    self._log("  3. Wait for NVIDIA to release a driver supporting your kernel", "info")
                    self._log("  4. List your kernels: dpkg --list 'linux-image-*' | grep '^ii'", "info")

                    self._schedule(lambda: self._progress_var.set(100))
                    self._finish_action(False)

                # Restart display manager
                self._log("Restarting display manager...", "info")
                for dm in ["gdm3", "gdm", "sddm", "lightdm"]:
                    _, _, rc = run_cmd(["sudo", "systemctl", "start", dm], timeout=10)
                    if rc == 0:
                        self._log(f"  Started {dm}", "success")
                        break

            threading.Thread(target=_do_preflight_and_install, daemon=True).start()

        def _download_and_install_asset(self, asset):
            """Download an asset dict from a GitHub release and install if it's a .run file."""
            if not asset:
                return
            url = asset.get("browser_download_url") or asset.get("url")
            name = asset.get("name") or "asset"
            if not url:
                messagebox.showerror("Download failed", "No download URL for the asset.")
                return

            # Destination in download dir
            dest = _get_download_dir() / name

            def _after_download(path):
                if not path:
                    messagebox.showerror("Download failed", "Failed to download update asset.")
                    return
                # Ensure it's executable
                try:
                    os.chmod(path, 0o755)
                except OSError:
                    pass
                # If it's a .run file, offer install
                if str(path).endswith(".run"):
                    if messagebox.askyesno("Install downloaded asset", f"Install {name} now?"):
                        self._install_local_run(str(path))

            # Use existing download flow but with direct URL
            if dest.exists():
                _after_download(str(dest))
                return

            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  DOWNLOADING  ", fg=CYAN)
            self._progress_var.set(0)
            self._progress_label.configure(text=f"Downloading {name}...")

            def _do():
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "nvidia-manager-updater"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        total = int(resp.headers.get("Content-Length", 0) or 0)
                        downloaded = 0
                        chunk_size = 1024 * 256
                        tmp_path = str(dest) + ".tmp"
                        with open(tmp_path, "wb") as fp:
                            while True:
                                chunk = resp.read(chunk_size)
                                if not chunk:
                                    break
                                fp.write(chunk)
                                downloaded += len(chunk)
                                if total > 0:
                                    pct = min(99, int(downloaded * 100 / total))
                                    self._schedule(lambda p=pct: self._progress_var.set(p))
                        shutil.move(tmp_path, str(dest))
                        os.chmod(str(dest), 0o755)
                        self._schedule(lambda: self._progress_var.set(100))
                        self._log("Asset download finished.", "success")
                        self._schedule(lambda: _after_download(str(dest)))
                except (urllib.error.URLError, OSError, ValueError) as e:
                    try:
                        tmp = str(dest) + ".tmp"
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except OSError:
                        pass
                    self._log(f"Asset download failed: {e}", "error")
                    self._schedule(lambda: _after_download(None))
                finally:
                    self.busy = False

            threading.Thread(target=_do, daemon=True).start()

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: CUDA / TOOLKIT
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_cuda_tab(self):
            f = self._frames["cuda"]
            _make_section_header(f, "CUDA & Toolkit")
            self._cuda_content = tk.Frame(f, bg=BG_DARK)
            self._cuda_content.pack(fill="both", expand=True)

        def _refresh_cuda_ui(self):
            for w in self._cuda_content.winfo_children():
                w.destroy()
            c = self.cuda_info
            f = self._cuda_content

            grid = tk.Frame(f, bg=BG_DARK)
            grid.pack(fill="x", pady=(0, 10))
            items = [
                ("Driver CUDA", c.get("driver_cuda", "N/A")),
                ("NVCC", c.get("nvcc", "Not installed")),
                ("cuDNN", c.get("cudnn", "Not installed")),
                ("TensorRT", c.get("tensorrt", "Not installed")),
                ("Container TK", c.get("container_toolkit", "Not installed")),
            ]
            for i, (label, val) in enumerate(items):
                card = _make_card(grid, padx=12, pady=8)
                card.grid(row=0, column=i, padx=3, pady=3, sticky="nsew")
                tk.Label(card, text=label.upper(), font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD, anchor="w").pack(
                    fill="x"
                )
                fg = NVIDIA_GREEN if val not in ("N/A", "Not installed") else TEXT_DIM
                tk.Label(card, text=val, font=("monospace", 11, "bold"), fg=fg, bg=BG_CARD, anchor="w").pack(
                    fill="x", pady=(2, 0)
                )
                grid.columnconfigure(i, weight=1)

            if c.get("installed_packages"):
                _make_section_label(f, "INSTALLED CUDA PACKAGES")
                card = _make_card(f, padx=14, pady=8)
                card.pack(fill="x", pady=(0, 8))
                for pkg in c["installed_packages"][:15]:
                    tk.Label(
                        card, text=f"  \u2022  {pkg}", font=("monospace", 9), fg=TEXT_SECOND, bg=BG_CARD, anchor="w"
                    ).pack(fill="x", pady=1)

            _make_section_label(f, "INSTALL TOOLS")
            btn_frame = tk.Frame(f, bg=BG_DARK)
            btn_frame.pack(fill="x")
            for txt, cmd in [
                (
                    "CUDA Toolkit",
                    partial(self._run_install_thread, "sudo apt install -y nvidia-cuda-toolkit", "CUDA Toolkit"),
                ),
                ("cuDNN", partial(self._run_install_thread, "sudo apt install -y libcudnn8 libcudnn8-dev", "cuDNN")),
                (
                    "TensorRT",
                    partial(self._run_install_thread, "sudo apt install -y libnvinfer10 libnvinfer-dev", "TensorRT"),
                ),
                ("Container Toolkit", self._install_container_toolkit),
            ]:
                self._make_action_btn(btn_frame, f"+ {txt}", cmd, fg_color=NVIDIA_GREEN).pack(side="left", padx=(0, 6))

        def _install_container_toolkit(self):
            if self.busy:
                return
            if not messagebox.askyesno("Install", "Install NVIDIA Container Toolkit for Docker?"):
                return
            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  WORKING  ", fg=ORANGE)
            self._progress_var.set(0)
            self._progress_label.configure(text="Installing Container Toolkit...")

            def _do():
                cmds = [
                    ["sudo", "apt", "install", "-y", "curl", "gpg"],
                    [
                        "bash",
                        "-c",
                        "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | "
                        "sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null || true",
                    ],
                    [
                        "bash",
                        "-c",
                        "curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | "
                        'sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | '
                        "sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null",
                    ],
                    ["sudo", "apt", "update"],
                    ["sudo", "apt", "install", "-y", "nvidia-container-toolkit"],
                    ["sudo", "nvidia-ctk", "runtime", "configure", "--runtime=docker"],
                ]
                for cmd in cmds:
                    self._log(" ".join(cmd[:5]) + ("..." if len(cmd) > 5 else ""), "cmd")
                    rc = run_cmd_stream(cmd, self._log, timeout=120)
                    if rc != 0:
                        self._log("Step failed, continuing...", "warn")
                self._schedule(lambda: self._progress_var.set(100))
                self._log("Container Toolkit installed. Restart Docker to activate.", "success")
                self._finish_action(True)

            threading.Thread(target=_do, daemon=True).start()

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: COMPUTE & APIS  (Vulkan · OpenCL · Level Zero · NPU · ROCm)
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_vulkan_tab(self):
            f = self._frames["vulkan"]
            header = tk.Frame(f, bg=BG_DARK)
            header.pack(fill="x", pady=(0, 6))
            tk.Label(header, text="Compute & APIs", font=("Helvetica", 14, "bold"),
                     fg=TEXT_PRIMARY, bg=BG_DARK).pack(side="left")
            self._make_action_btn(
                header, "\u21BB Re-scan",
                lambda: threading.Thread(target=self._detect_all, daemon=True).start()
            ).pack(side="right")

            # ── Scrollable canvas ──
            canvas_frame = tk.Frame(f, bg=BG_DARK)
            canvas_frame.pack(fill="both", expand=True)
            self._compute_canvas = tk.Canvas(canvas_frame, bg=BG_DARK, highlightthickness=0)
            compute_sb = tk.Scrollbar(canvas_frame, orient="vertical", command=self._compute_canvas.yview)
            self._compute_inner = tk.Frame(self._compute_canvas, bg=BG_DARK)
            self._compute_inner.bind(
                "<Configure>",
                lambda e: self._compute_canvas.configure(scrollregion=self._compute_canvas.bbox("all"))
            )
            self._compute_canvas.create_window((0, 0), window=self._compute_inner, anchor="nw", tags="inner")
            self._compute_canvas.configure(yscrollcommand=compute_sb.set)
            self._compute_canvas.bind(
                "<Configure>", lambda e: self._compute_canvas.itemconfig("inner", width=e.width)
            )
            self._compute_canvas.pack(side="left", fill="both", expand=True)
            compute_sb.pack(side="right", fill="y")
            # Mouse wheel scroll
            self._compute_canvas.bind_all("<MouseWheel>", lambda e: self._compute_canvas.yview_scroll(
                -1 if e.delta > 0 else 1, "units"))
            self._compute_canvas.bind_all("<Button-4>", lambda e: self._compute_canvas.yview_scroll(-1, "units"))
            self._compute_canvas.bind_all("<Button-5>", lambda e: self._compute_canvas.yview_scroll(1, "units"))

        def _refresh_vulkan_ui(self):
            for w in self._compute_inner.winfo_children():
                w.destroy()
            f = self._compute_inner

            def _sec(title, color=NVIDIA_GREEN):
                """Render a section divider."""
                row = tk.Frame(f, bg=BG_DARK)
                row.pack(fill="x", pady=(14, 4))
                tk.Label(row, text=title, font=("monospace", 9, "bold"),
                         fg=color, bg=BG_DARK, anchor="w").pack(side="left")
                tk.Frame(row, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0))

            def _kv_card(parent, pairs, cols=4):
                """Render a grid of labeled metric cards."""
                kv_grid = tk.Frame(parent, bg=BG_DARK)
                kv_grid.pack(fill="x", pady=(0, 6))
                for col in range(cols):
                    kv_grid.columnconfigure(col, weight=1)
                for kv_i, (kv_lbl, kv_val, kv_ok) in enumerate(pairs):
                    kv_c = _make_card(kv_grid, padx=10, pady=6)
                    kv_c.grid(row=kv_i // cols, column=kv_i % cols, padx=2, pady=2, sticky="nsew")
                    tk.Label(kv_c, text=kv_lbl.upper(), font=("monospace", 7), fg=TEXT_DIM,
                             bg=BG_CARD, anchor="w").pack(fill="x")
                    fg = NVIDIA_GREEN if kv_ok else TEXT_DIM
                    tk.Label(kv_c, text=kv_val or "—", font=("monospace", 10, "bold"),
                             fg=fg, bg=BG_CARD, anchor="w").pack(fill="x", pady=(2, 0))

            def _install_row(*btns):
                """Render a row of install buttons.

                Each entry is either ``(text, cmd)`` or
                ``(text, cmd, disabled)`` where *disabled* is a bool.
                When disabled the button is shown with a ✔ prefix, dimmed
                colors and ``state="disabled"`` so it cannot be clicked.
                """
                row = tk.Frame(f, bg=BG_DARK)
                row.pack(fill="x", pady=(4, 2))
                for entry in btns:
                    txt, cmd = entry[0], entry[1]
                    disabled = entry[2] if len(entry) > 2 else False
                    if disabled:
                        btn = tk.Button(
                            row,
                            text=f"✔ {txt.lstrip('+ ')}",
                            font=("monospace", 9),
                            fg=TEXT_DIM,
                            bg=BG_CARD,
                            activeforeground=TEXT_DIM,
                            activebackground=BG_CARD,
                            bd=0,
                            highlightthickness=1,
                            highlightbackground=BORDER,
                            padx=10,
                            pady=3,
                            cursor="arrow",
                            state="disabled",
                            command=lambda: None,
                        )
                    else:
                        btn = self._make_action_btn(row, txt, cmd, fg_color=NVIDIA_GREEN)
                    btn.pack(side="left", padx=(0, 6))

            # ── API Status Overview ──
            _sec("▸  COMPUTE API STATUS")
            v = self.vulkan_info
            ocl = self.opencl_info
            lz = self.levelzero_info
            npu = self.npu_info
            rocm = self.rocm_info

            vk_ok   = bool(v.get("devices"))
            ocl_ok  = ocl.get("available", False)
            lz_ok   = lz.get("available", False)
            npu_ok  = bool(npu.get("devices") or npu.get("openvino_devices"))
            rocm_ok = rocm.get("available", False)
            hc_ok   = self.hashcat_info.get("available", False)

            overview = [
                ("Vulkan",     "✔  Active" if vk_ok   else "✘  Not detected", vk_ok),
                ("OpenCL",     "✔  Active" if ocl_ok  else "✘  Not detected", ocl_ok),
                ("Level Zero", "✔  Active" if lz_ok   else "✘  Not detected", lz_ok),
                ("NPU/VPU",    "✔  Active" if npu_ok  else "✘  Not detected", npu_ok),
                ("AMD ROCm",   "✔  Active" if rocm_ok else "✘  Not detected", rocm_ok),
                ("hashcat",    "✔  Active" if hc_ok   else "✘  Not found",    hc_ok),
            ]
            _kv_card(f, overview, cols=6)

            # ═════════════════════════════════════════
            #  VULKAN
            # ═════════════════════════════════════════
            _sec("▸  VULKAN")
            if v.get("devices"):
                for dev in v["devices"]:
                    is_cpu_dev = dev.get("type", "").upper() == "CPU"
                    border = BORDER if is_cpu_dev else (GREEN_BORDER if vk_ok else BORDER)
                    dcard = _make_card(f, padx=12, pady=8, border_color=border)
                    dcard.pack(fill="x", pady=(0, 4))
                    # Header row: name + type badge
                    hrow = tk.Frame(dcard, bg=BG_CARD)
                    hrow.pack(fill="x")
                    name = dev.get("name") or dev.get("label") or "Unknown Device"
                    name_fg = TEXT_DIM if is_cpu_dev else TEXT_PRIMARY
                    tk.Label(hrow, text=name, font=("monospace", 11, "bold"),
                             fg=name_fg, bg=BG_CARD, anchor="w").pack(side="left")
                    dev_type = dev.get("type", "")
                    if dev_type:
                        type_fg = {"dGPU": NVIDIA_GREEN, "iGPU": CYAN,
                                   "CPU": TEXT_DIM, "vGPU": PURPLE}.get(dev_type, TEXT_SECOND)
                        tk.Label(hrow, text=f"  [{dev_type}]",
                                 font=("monospace", 9), fg=type_fg, bg=BG_CARD).pack(side="left")
                    vendor = dev.get("vendor", "")
                    if vendor:
                        tk.Label(hrow, text=vendor, font=("monospace", 9),
                                 fg=TEXT_DIM, bg=BG_CARD).pack(side="right")
                    # Detail row
                    detail = tk.Frame(dcard, bg=BG_CARD)
                    detail.pack(fill="x", pady=(3, 0))
                    fields = [
                        ("API",         dev.get("api_version")),
                        ("Driver",      dev.get("driver_info") or dev.get("driver_version")),
                        ("Driver name", dev.get("driver_name")),
                        ("Conformance", dev.get("conformance")),
                        ("Vendor ID",   dev.get("vendor_id")),
                        ("Device ID",   dev.get("device_id")),
                    ]
                    for lbl, val in fields:
                        if val:
                            tk.Label(detail, text=f"{lbl}: {val}",
                                     font=("monospace", 8), fg=TEXT_SECOND, bg=BG_CARD).pack(side="left", padx=(0, 14))
                # Instance-level summary
                summary_parts = []
                if v.get("instance_extensions"):
                    summary_parts.append(f"Instance extensions: {v['instance_extensions']}")
                if v.get("instance_layers"):
                    summary_parts.append(f"Layers: {v['instance_layers']}")
                if summary_parts:
                    tk.Label(f, text="  " + "   |   ".join(summary_parts),
                             font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 4))
            else:
                tk.Label(f, text="  Vulkan not detected. Install vulkan-tools.",
                         font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 4))

            _install_row(
                ("+ vulkan-tools", partial(self._run_install_thread, "sudo apt install -y vulkan-tools vulkan-validationlayers libvulkan1", "Vulkan Tools")),
                ("+ libvulkan-dev", partial(self._run_install_thread, "sudo apt install -y libvulkan-dev spirv-tools", "Vulkan Dev")),
                ("+ Mesa Vulkan", partial(self._run_install_thread, "sudo apt install -y mesa-vulkan-drivers", "Mesa Vulkan")),
                ("Run vulkaninfo", partial(self._run_install_thread, "vulkaninfo --summary", "vulkaninfo")),
            )

            # ═════════════════════════════════════════
            #  OPENCL
            # ═════════════════════════════════════════
            _sec("▸  OPENCL", color=CYAN)
            platforms = ocl.get("platforms", [])
            if platforms:
                for plat in platforms:
                    pcard = _make_card(f, padx=12, pady=8, border_color=BORDER_LIGHT)
                    pcard.pack(fill="x", pady=(0, 6))
                    hdr = tk.Frame(pcard, bg=BG_CARD)
                    hdr.pack(fill="x")
                    tk.Label(hdr, text=f"\u25C6 {plat.get('name','?')}",
                             font=("monospace", 10, "bold"), fg=CYAN, bg=BG_CARD, anchor="w").pack(side="left")
                    tk.Label(hdr, text=plat.get("version", ""),
                             font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD).pack(side="right")
                    if plat.get("vendor"):
                        tk.Label(pcard, text=f"  Vendor: {plat['vendor']}",
                                 font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD, anchor="w").pack(fill="x")
                    for dev in plat.get("devices", []):
                        drow = tk.Frame(pcard, bg=BG_CARD, pady=3)
                        drow.pack(fill="x")
                        tk.Frame(pcard, bg=BORDER, height=1).pack(fill="x", padx=4)
                        tk.Label(drow, text=f"  \u25B8 {dev.get('name','?')} [{dev.get('type','?')}]",
                                 font=("monospace", 9, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD, anchor="w").pack(fill="x")
                        meta = []
                        cu = dev.get("compute_units")
                        if cu and str(cu) != "?":
                            meta.append(f"CUs: {cu}")
                        clk = dev.get("clock_mhz")
                        if clk and str(clk) != "?":
                            meta.append(f"Clock: {clk} MHz")
                        mem = dev.get("global_mem_mb")
                        if mem and str(mem) != "?":
                            meta.append(f"Mem: {mem} MiB")
                        lmem = dev.get("local_mem_kb")
                        if lmem and str(lmem) != "?":
                            meta.append(f"LMem: {lmem} KiB")
                        ocl_ver = dev.get("opencl_version")
                        if ocl_ver and str(ocl_ver) != "?":
                            meta.append(f"OpenCL: {ocl_ver}")
                        if meta:
                            tk.Label(drow, text="    " + "  |  ".join(meta),
                                     font=("monospace", 8), fg=TEXT_SECOND, bg=BG_CARD, anchor="w").pack(fill="x")
            else:
                tk.Label(f, text="  No OpenCL platforms detected.",
                         font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 4))

            _install_row(
                ("+ opencl-icd (CPU)", partial(self._run_install_thread, "sudo apt install -y intel-opencl-icd ocl-icd-opencl-dev opencl-headers", "Intel OpenCL ICD")),
                ("+ NVIDIA OpenCL", partial(self._run_install_thread, "sudo apt install -y nvidia-opencl-icd-525 ocl-icd-libopencl1", "NVIDIA OpenCL")),
                ("+ clinfo", partial(self._run_install_thread, "sudo apt install -y clinfo", "clinfo")),
                ("+ pyopencl", partial(self._run_install_thread, "pip install pyopencl", "pyopencl")),
                ("Run clinfo", partial(self._run_install_thread, "clinfo -l", "clinfo")),
            )

            # ═════════════════════════════════════════
            #  INTEL LEVEL ZERO
            # ═════════════════════════════════════════
            _sec("▸  INTEL LEVEL ZERO  (oneAPI / iGPU / Arc)", color=PURPLE)
            if lz.get("available"):
                devs = lz.get("devices", [])
                if devs:
                    for dev in devs:
                        dcard = _make_card(f, padx=12, pady=8, border_color=BORDER_LIGHT)
                        dcard.pack(fill="x", pady=(0, 4))
                        tk.Label(dcard, text=f"\u25C6 {dev.get('name','?')}",
                                 font=("monospace", 10, "bold"), fg=PURPLE, bg=BG_CARD, anchor="w").pack(fill="x")
                        details = []
                        for k, label in [("type","Type"),("vendor_id","Vendor"),
                                         ("eu_count","EU Count"),("subdevices","Sub-devices"),("memory","Memory")]:
                            if dev.get(k):
                                details.append(f"{label}: {dev[k]}")
                        if details:
                            tk.Label(dcard, text="  " + "  |  ".join(details),
                                     font=("monospace", 8), fg=TEXT_SECOND, bg=BG_CARD, anchor="w").pack(fill="x", pady=(2,0))
                else:
                    tk.Label(f, text="  Level Zero runtime present (no device details parsed).",
                             font=("monospace", 9), fg=TEXT_SECOND, bg=BG_DARK, anchor="w").pack(fill="x")
            else:
                tk.Label(f, text="  Level Zero not detected. Requires Intel GPU and ze_info.",
                         font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 4))

            _install_row(
                ("+ Level Zero (build from source)", self._install_level_zero_from_source),
                ("+ oneAPI Base Kit (build from source)", self._install_oneapi_from_source),
                ("+ Intel IGC (build from source)", self._install_igc_from_source),
                ("+ oneAPI Base Kit (apt)", partial(self._run_install_thread, "sudo apt install -y intel-basekit", "Intel oneAPI")),
                ("+ Intel GPU drivers", partial(self._run_install_thread, "sudo apt install -y intel-media-va-driver-non-free vainfo intel-gpu-tools", "Intel GPU")),
            )

            # ═════════════════════════════════════════
            #  NPU / VPU / ACCELERATORS
            # ═════════════════════════════════════════
            _sec("▸  NPU / VPU / AI ACCELERATORS", color=ORANGE)
            npu_devs = npu.get("devices", [])
            ov_devs = npu.get("openvino_devices", [])
            if npu_devs or ov_devs or npu.get("driver"):
                if npu.get("driver"):
                    tk.Label(f, text=f"  Driver: {npu['driver']}",
                             font=("monospace", 9, "bold"), fg=NVIDIA_GREEN, bg=BG_DARK, anchor="w").pack(fill="x")
                for dev in npu_devs:
                    dcard = _make_card(f, padx=12, pady=6, border_color=BORDER_LIGHT)
                    dcard.pack(fill="x", pady=(0, 3))
                    tk.Label(dcard, text=f"\u25C6 {dev.get('type','NPU')}",
                             font=("monospace", 9, "bold"), fg=ORANGE, bg=BG_CARD, anchor="w").pack(side="left")
                    tk.Label(dcard, text=dev.get("path",""),
                             font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD, anchor="e").pack(side="right")
                if ov_devs:
                    ov_ver = npu.get("openvino_version", "")
                    ov_hdr = f"  OpenVINO{' ' + ov_ver if ov_ver else ''} devices:"
                    tk.Label(f, text=ov_hdr, font=("monospace", 9, "bold"),
                             fg=ORANGE, bg=BG_DARK, anchor="w").pack(fill="x", pady=(6, 2))
                    for dev in ov_devs:
                        dcard = _make_card(f, padx=12, pady=6)
                        dcard.pack(fill="x", pady=(0, 3))
                        hrow = tk.Frame(dcard, bg=BG_CARD)
                        hrow.pack(fill="x")
                        tk.Label(hrow, text=f"\u25B8 [{dev['name']}]",
                                 font=("monospace", 9, "bold"), fg=ORANGE, bg=BG_CARD).pack(side="left")
                        tk.Label(hrow, text=f"  {dev.get('full_name', '')}",
                                 font=("monospace", 9), fg=TEXT_PRIMARY, bg=BG_CARD).pack(side="left")
                        caps = dev.get("capabilities", [])
                        if caps:
                            tk.Label(dcard, text="    " + "  ".join(caps),
                                     font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD, anchor="w").pack(fill="x")
            else:
                tk.Label(f, text="  No NPU/VPU detected. Intel NPU requires Meteor Lake / Core Ultra CPU.",
                         font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 4))

            # Detect OpenVINO install state at render time (fast – no subprocess)
            import importlib.util as _ilu  # pylint: disable=import-outside-toplevel
            _ov_installed = _ilu.find_spec("openvino") is not None
            _onnx_installed = _ilu.find_spec("onnxruntime") is not None
            _nncf_installed = _ilu.find_spec("nncf") is not None

            _install_row(
                ("+ OpenVINO", partial(self._run_install_thread, "pip install openvino", "OpenVINO"), _ov_installed),
                ("+ Intel NPU driver", partial(self._run_install_thread, "sudo snap install intel-npu-driver", "Intel NPU driver")),
                ("+ ONNX Runtime OV", partial(self._run_install_thread, "pip install onnxruntime", "ONNX Runtime OpenVINO"), _onnx_installed),
                ("+ NNCF (compress)", partial(self._run_install_thread, "pip install nncf", "NNCF"), _nncf_installed),
            )

            # ═════════════════════════════════════════
            #  AMD ROCm
            # ═════════════════════════════════════════
            _sec("▸  AMD ROCm / HIP", color=RED)
            if rocm_ok:
                if rocm.get("version"):
                    tk.Label(f, text=f"  ROCm version: {rocm['version']}",
                             font=("monospace", 9, "bold"), fg=NVIDIA_GREEN, bg=BG_DARK, anchor="w").pack(fill="x")
                for dev in rocm.get("devices", []):
                    dcard = _make_card(f, padx=12, pady=6, border_color=BORDER_LIGHT)
                    dcard.pack(fill="x", pady=(0, 3))
                    name = dev.get("name") or dev.get("label", "Unknown AMD GPU")
                    tk.Label(dcard, text=f"\u25C6 {name}",
                             font=("monospace", 10, "bold"), fg=RED, bg=BG_CARD, anchor="w").pack(fill="x")
                    meta = []
                    for k, lbl in [("compute_units","CUs"),("clock_mhz","Clock"),("memory","Mem")]:
                        if dev.get(k):
                            meta.append(f"{lbl}: {dev[k]}")
                    if meta:
                        tk.Label(dcard, text="  " + "  |  ".join(meta),
                                 font=("monospace", 8), fg=TEXT_SECOND, bg=BG_CARD, anchor="w").pack(fill="x", pady=(2,0))
            else:
                tk.Label(f, text="  AMD ROCm not detected.",
                         font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 4))

            _install_row(
                ("+ ROCm (apt)", partial(self._run_install_thread, "sudo apt install -y rocm-hip-sdk rocm-opencl-runtime rocm-utils", "ROCm")),
                ("+ PyTorch ROCm", partial(self._run_install_thread, "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2", "PyTorch ROCm")),
                ("rocm-smi", partial(self._run_install_thread, "rocm-smi", "rocm-smi")),
            )

            # ═════════════════════════════════════════
            #  HASHCAT COMPUTE BACKENDS
            # ═════════════════════════════════════════
            hc = self.hashcat_info
            hc_ok = hc.get("available", False)
            _sec("▸  HASHCAT COMPUTE BACKENDS", color=NVIDIA_GREEN if hc_ok else TEXT_DIM)
            if hc_ok:
                ver_txt = f"hashcat v{hc.get('version','?')}"
                tk.Label(f, text=f"  {ver_txt}",
                         font=("monospace", 9, "bold"), fg=NVIDIA_GREEN, bg=BG_DARK, anchor="w").pack(fill="x")
                for backend in hc.get("backends", []):
                    b_type = backend.get("type", "?")
                    b_ver  = backend.get("version", "")
                    b_color = {"CUDA": NVIDIA_GREEN, "OPENCL": CYAN,
                               "HIP": RED, "METAL": PURPLE, "LEVEL.ZERO": PURPLE}.get(b_type, TEXT_SECOND)
                    b_label = f"  {b_type}" + (f"  v{b_ver}" if b_ver else "")
                    tk.Label(f, text=b_label, font=("monospace", 9, "bold"),
                             fg=b_color, bg=BG_DARK, anchor="w").pack(fill="x", pady=(6, 2))
                    for plat in backend.get("platforms", []):
                        for dev in plat.get("devices", []):
                            dcard = _make_card(f, padx=12, pady=7, border_color=BORDER_LIGHT)
                            dcard.pack(fill="x", pady=(0, 3))
                            # Header: Device ID + Name
                            hrow = tk.Frame(dcard, bg=BG_CARD)
                            hrow.pack(fill="x")
                            dev_id   = dev.get("id", "?")
                            alias    = dev.get("alias")
                            dev_name = dev.get("name", "Unknown device")
                            id_txt = f"#Dev {dev_id}" + (f" (alias #{alias})" if alias else "")
                            tk.Label(hrow, text=id_txt,
                                     font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD).pack(side="left")
                            tk.Label(hrow, text=dev_name,
                                     font=("monospace", 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD).pack(side="left", padx=(10, 0))
                            # Metrics row
                            m_row = tk.Frame(dcard, bg=BG_CARD)
                            m_row.pack(fill="x", pady=(3, 0))
                            metrics = [
                                ("SMs",         dev.get("processors")),
                                ("Clock",        (dev.get("clock") or dev.get("clock_mhz") or "") + " MHz"
                                                 if (dev.get("clock") or dev.get("clock_mhz")) else None),
                                ("VRAM total",   (dev.get("mem_total_mb") or "") + " MB"
                                                 if dev.get("mem_total_mb") else None),
                                ("VRAM free",    (dev.get("mem_free_mb") or "") + " MB"
                                                 if dev.get("mem_free_mb") else None),
                                ("Local mem",    (dev.get("local_mem_kb") or "") + " KB"
                                                 if dev.get("local_mem_kb") else None),
                                ("Pref threads", dev.get("preferred_threads")),
                                ("OpenCL C",     dev.get("opencl_c_version")),
                                ("Driver",       dev.get("driver_version")),
                                ("PCI",          dev.get("pci_addr")),
                                ("Vendor",       dev.get("vendor")),
                                ("Type",         dev.get("type")),
                            ]
                            for lbl, val in metrics:
                                if val and str(val).strip():
                                    tk.Label(m_row, text=f"{lbl}: {val}",
                                             font=("monospace", 8), fg=TEXT_SECOND,
                                             bg=BG_CARD).pack(side="left", padx=(0, 12))
                _install_row(
                    ("+ hashcat", partial(self._run_install_thread, "sudo apt install -y hashcat", "hashcat"), hc_ok),
                    ("hashcat -I", partial(self._run_install_thread, "hashcat -I", "hashcat"), not hc_ok),
                    ("hashcat benchmark", partial(self._run_install_thread, "hashcat -b --quiet", "hashcat benchmark"), not hc_ok),
                )
            else:
                tk.Label(f, text="  hashcat not found.",
                         font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 2))
                _install_row(
                    ("+ hashcat", partial(self._run_install_thread, "sudo apt install -y hashcat", "hashcat")),
                    ("hashcat -I", partial(self._run_install_thread, "hashcat -I", "hashcat"), True),
                    ("hashcat benchmark", partial(self._run_install_thread, "hashcat -b --quiet", "hashcat benchmark"), True),
                )

            # ═════════════════════════════════════════
            #  CPU
            # ═════════════════════════════════════════
            cpu = self.cpu_info
            _sec("▸  CPU / HOST PROCESSOR", color=TEXT_SECOND)
            if cpu.get("model"):
                cpu_card = _make_card(f, padx=12, pady=8)
                cpu_card.pack(fill="x", pady=(0, 6))
                # Model line
                tk.Label(cpu_card, text=cpu["model"],
                         font=("monospace", 10, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD, anchor="w").pack(fill="x")
                # Quick metrics
                m_row = tk.Frame(cpu_card, bg=BG_CARD)
                m_row.pack(fill="x", pady=(4, 0))
                metrics = [
                    ("Vendor",   cpu.get("vendor")),
                    ("Arch",     cpu.get("arch")),
                    ("Physical cores", str(cpu.get("cores_physical") or "?")),
                    ("Logical CPUs",   cpu.get("cores_logical")),
                    ("Threads/core",   cpu.get("threads_per_core")),
                    ("Sockets",        cpu.get("sockets")),
                    ("Max MHz",        cpu.get("freq_max_mhz")),
                    ("Cur MHz",        cpu.get("freq_cur_mhz")),
                    ("NUMA nodes",     cpu.get("numa_nodes")),
                    ("Microcode",      cpu.get("microcode")),
                ]
                for lbl, val in metrics:
                    if val:
                        tk.Label(m_row, text=f"{lbl}: {val}",
                                 font=("monospace", 8), fg=TEXT_SECOND, bg=BG_CARD).pack(side="left", padx=(0, 14))
                # Cache
                cache = cpu.get("cache", {})
                if cache:
                    c_row = tk.Frame(cpu_card, bg=BG_CARD)
                    c_row.pack(fill="x", pady=(2, 0))
                    for level, size in cache.items():
                        tk.Label(c_row, text=f"{level}: {size}",
                                 font=("monospace", 8), fg=TEXT_DIM, bg=BG_CARD).pack(side="left", padx=(0, 14))
                # ISA features
                feats = cpu.get("features", [])
                if feats:
                    tk.Frame(cpu_card, bg=BORDER, height=1).pack(fill="x", pady=(5, 3))
                    feat_lbl = tk.Label(cpu_card, text="  ISA: " + "  ".join(f.upper() for f in feats),
                                        font=("monospace", 8), fg=CYAN, bg=BG_CARD, anchor="w", wraplength=800, justify="left")
                    feat_lbl.pack(fill="x")
                # Vulnerabilities (collapsed unless mitigated)
                vulns = cpu.get("vulnerabilities", {})
                if vulns:
                    tk.Frame(cpu_card, bg=BORDER, height=1).pack(fill="x", pady=(5, 3))
                    v_row = tk.Frame(cpu_card, bg=BG_CARD)
                    v_row.pack(fill="x")
                    vuln_count_bad = sum(1 for s in vulns.values()
                                         if "vulnerable" in s.lower() and "not affected" not in s.lower())
                    vuln_summary = (f"\u26A0 {vuln_count_bad} unmitigated vulnerabilit{'y' if vuln_count_bad==1 else 'ies'}"
                                    if vuln_count_bad else "\u2713 All CPU vulnerabilities mitigated")
                    vuln_fg = ORANGE if vuln_count_bad else NVIDIA_GREEN
                    tk.Label(v_row, text=vuln_summary, font=("monospace", 8),
                             fg=vuln_fg, bg=BG_CARD, anchor="w").pack(side="left")
            else:
                tk.Label(f, text="  CPU info not available (lscpu not found).",
                         font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(0, 4))

            # ═════════════════════════════════════════
            #  PYTHON COMPUTE LIBRARIES
            # ═════════════════════════════════════════
            _sec("▸  PYTHON COMPUTE LIBRARIES", color=TEXT_SECOND)
            py_libs = self._check_python_compute_libs()
            grid = tk.Frame(f, bg=BG_DARK)
            grid.pack(fill="x", pady=(0, 6))
            for i, (lib, ver, ok) in enumerate(py_libs):
                c = _make_card(grid, padx=10, pady=6)
                c.grid(row=i // 5, column=i % 5, padx=2, pady=2, sticky="nsew")
                grid.columnconfigure(i % 5, weight=1)
                tk.Label(c, text=lib, font=("monospace", 8, "bold"),
                         fg=NVIDIA_GREEN if ok else TEXT_DIM, bg=BG_CARD, anchor="w").pack(fill="x")
                tk.Label(c, text=ver, font=("monospace", 8),
                         fg=TEXT_SECOND if ok else TEXT_DIM, bg=BG_CARD, anchor="w").pack(fill="x")

            _numba_installed = _ilu.find_spec("numba") is not None
            _cupy_installed = _ilu.find_spec("cupy") is not None
            _jax_installed = _ilu.find_spec("jax") is not None
            _pytorch_installed = (
                _ilu.find_spec("torch") is not None
                and _ilu.find_spec("torchvision") is not None
            )
            _tensorflow_installed = _ilu.find_spec("tensorflow") is not None

            _install_row(
                ("+ PyTorch + CUDA", lambda: self._run_install_thread(
                    "pip install torch torchvision torchaudio", "PyTorch"), _pytorch_installed),
                ("+ CuPy", lambda: self._run_install_thread("pip install cupy-cuda12x", "CuPy"), _cupy_installed),
                ("+ Numba", lambda: self._run_install_thread("pip install numba", "Numba"), _numba_installed),
                ("+ JAX (CUDA)", lambda: self._run_install_thread(
                    'pip install "jax[cuda12]"', "JAX"), _jax_installed),
                ("+ TensorFlow", lambda: self._run_install_thread(
                    'pip install "tensor"', "TensorFlow"), _tensorflow_installed),
            )

            # bottom padding
            tk.Frame(f, bg=BG_DARK, height=20).pack()

        @staticmethod
        def _check_python_compute_libs():
            """Return list of (name, version_str, installed_bool) for compute libs."""
            results = []
            checks = [
                ("torch",           lambda: __import__("torch").__version__),
                ("torchvision",     lambda: __import__("torchvision").__version__),
                ("tensorflow",      lambda: __import__("tensorflow").__version__),
                ("jax",             lambda: __import__("jax").__version__),
                ("pyopencl",        lambda: __import__("pyopencl").VERSION_TEXT),
                ("cupy",            lambda: __import__("cupy").__version__),
                ("numba",           lambda: __import__("numba").__version__),
                ("onnxruntime",     lambda: __import__("onnxruntime").__version__),
                ("openvino",        lambda: __import__("openvino").__version__),
                ("numpy",           lambda: __import__("numpy").__version__),
                ("scipy",           lambda: __import__("scipy").__version__),
                ("scikit-learn",    lambda: __import__("sklearn").__version__),
                ("triton",          lambda: __import__("triton").__version__),
                ("cuda-python",     lambda: __import__("cuda.bindings", fromlist=["__version__"]).__version__),
            ]
            for name, getter in checks:
                try:
                    ver = getter()
                    results.append((name, ver, True))
                except (ImportError, AttributeError):
                    results.append((name, "not installed", False))
            return results

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: POWER / CLOCKS
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_power_tab(self):
            f = self._frames["power"]
            _make_section_header(f, "Power & Clock Management")

            # Power info
            self._power_info_frame = tk.Frame(f, bg=BG_DARK)
            self._power_info_frame.pack(fill="x", pady=(0, 10))
            self._power_labels = {}
            for i, lb in enumerate(["Power Draw", "Power Limit", "Default Limit", "Max Limit", "Min Limit"]):
                self._power_labels[lb] = _make_metric(self._power_info_frame, lb, row=0, col=i)
                self._power_info_frame.columnconfigure(i, weight=1)

            # Power Limit Slider
            self._power_limit_var = tk.IntVar(value=0)
            power_limit_label = tk.Label(f, text="Power Limit (W):")
            power_limit_label.pack(side="top", pady=5)

            # Define update_power_limit before creating widgets that reference it.
            def update_power_limit(value) -> None:
                try:
                    ival = int(value)
                    if ival < 0:
                        ival = 0
                    elif ival > 100:
                        ival = 100
                    # update widgets if they exist
                    try:
                        power_limit_slider.set(ival)
                    except Exception:
                        pass
                    try:
                        power_limit_entry.delete(0, tk.END)
                        power_limit_entry.insert(0, str(ival))
                    except Exception:
                        pass
                    self._power_limit_var.set(ival)
                    try:
                        self._apply_power_limit()
                    except Exception:
                        pass
                except (ValueError, TypeError):
                    pass

            power_limit_slider = tk.Scale(f, from_=0, to=100, orient="horizontal", command=update_power_limit)
            power_limit_slider.pack(side="top", pady=5)

            power_limit_entry = tk.Entry(f, width=10)
            power_limit_entry.pack(side="top", pady=5)

            def _on_power_entry_return(_event):
                update_power_limit(power_limit_entry.get())

            power_limit_entry.bind("<Return>", _on_power_entry_return)

            # Fan control
            _make_section_label(f, "FAN CONTROL")
            fan_card = _make_card(f, padx=14, pady=8)
            fan_card.pack(fill="x", pady=(0, 10))
            # Manual toggle: when off, the scale and apply button are disabled to avoid accidental use
            self._fan_manual_var = tk.BooleanVar(value=self.settings.get("fan_control_manual", False))
            # Provide a callback so the UI updates immediately when the toggle changes
            _make_toggle_row(
                fan_card,
                "Manual fan control (requires Coolbits)",
                self._fan_manual_var,
                callback=self._update_fan_controls,
            )

            # Fan speed variable and controls
            self._fan_speed_var = tk.IntVar(value=int(self.settings.get("fan_speed_pct", 50)))
            fan_row = tk.Frame(fan_card, bg=BG_CARD, pady=4)
            fan_row.pack(fill="x")
            tk.Label(fan_row, text="Fan Speed:", font=("monospace", 10), fg=TEXT_PRIMARY, bg=BG_CARD).pack(side="left")
            self._fan_val_label = tk.Label(
                fan_row,
                text=f"{self._fan_speed_var.get()}%",
                font=("monospace", 10, "bold"),
                fg=NVIDIA_GREEN,
                bg=BG_CARD,
            )
            self._fan_val_label.pack(side="right")

            # Keep a reference to the Scale and Apply button so we can enable/disable them
            self._fan_scale = tk.Scale(
                fan_card,
                from_=0,
                to=100,
                orient="horizontal",
                variable=self._fan_speed_var,
                bg=BG_CARD,
                fg=TEXT_PRIMARY,
                troughcolor=BG_INPUT,
                highlightthickness=0,
                activebackground=NVIDIA_GREEN,
                font=("monospace", 8),
                command=lambda v: self._fan_val_label.configure(text=f"{int(float(v))}%"),
                resolution=1,
            )
            self._fan_scale.pack(fill="x", pady=(2, 4))

            self._fan_apply_btn = _make_green_btn(fan_card, "Apply Fan Speed", self._apply_fan_speed)
            self._fan_apply_btn.pack(anchor="e")

            # Keep label in sync if the variable is changed programmatically and update control state
            try:
                # trace_add is preferred on modern Python; fallback to trace if necessary
                if hasattr(self._fan_speed_var, "trace_add"):
                    self._fan_speed_var.trace_add(
                        "write", lambda *a: self._fan_val_label.configure(text=f"{self._fan_speed_var.get()}%")
                    )
                    self._fan_manual_var.trace_add("write", lambda *a: self._update_fan_controls())
                else:
                    self._fan_speed_var.trace(
                        "w", lambda *a: self._fan_val_label.configure(text=f"{self._fan_speed_var.get()}%")
                    )
                    self._fan_manual_var.trace("w", lambda *a: self._update_fan_controls())
            except tk.TclError:
                pass

            # Ensure initial enabled/disabled state matches the saved setting
            self._update_fan_controls()

            # Clock offsets
            _make_section_label(f, "CLOCK OFFSETS (requires Coolbits)")
            clk_card = _make_card(f, padx=14, pady=10)
            clk_card.pack(fill="x")
            for lbl, var_key, from_, to_ in [
                ("Core Clock Offset (MHz)", "clock_offset_core", -500, 500),
                ("Memory Clock Offset (MHz)", "clock_offset_mem", -2000, 2000),
            ]:
                row = tk.Frame(clk_card, bg=BG_CARD, pady=3)
                row.pack(fill="x")
                tk.Label(
                    row,
                    text=lbl,
                    font=("monospace", 10),
                    fg=TEXT_PRIMARY,
                    bg=BG_CARD,
                ).pack(side="left")
                var = tk.IntVar(value=int(self.settings.get(var_key, 0)))
                setattr(self, f"_{var_key}_var", var)
                tk.Spinbox(
                    row,
                    from_=from_,
                    to=to_,
                    textvariable=var,
                    width=6,
                    font=("monospace", 10),
                    bg=BG_INPUT,
                    fg=TEXT_PRIMARY,
                    buttonbackground=BG_CARD,
                    highlightthickness=0,
                    bd=1,
                    insertbackground=NVIDIA_GREEN,
                ).pack(side="right")
            _make_green_btn(clk_card, "Apply Clock Offsets", self._apply_clock_offsets).pack(anchor="e", pady=(6, 0))

        def _apply_power_limit(self):
            watts = self._power_limit_var.get()
            if watts <= 0:
                watts = int(float(self.gpu_info.get("power_default", 0)))
                if watts <= 0:
                    messagebox.showinfo("Info", "Could not determine default power limit.")
                    return
            cmd = ["sudo", "nvidia-smi", "-pl", str(watts)]
            self._log(" ".join(cmd), "cmd")
            _, err, rc = run_cmd(cmd)
            if rc == 0:
                self._log(f"Power limit set to {watts}W.", "success")
                self.settings["power_limit_watts"] = watts
                self._save_settings()
            else:
                self._log(f"Failed: {err}", "error")

        def _apply_fan_speed(self):
            if not self._fan_manual_var.get():
                messagebox.showinfo("Info", "Enable manual fan control toggle first.\nAlso requires Coolbits in Xorg.")
                return
            speed = self._fan_speed_var.get()
            for cmd in [
                ["nvidia-settings", "-a", "GPUFanControlState=1"],
                ["nvidia-settings", "-a", f"GPUTargetFanSpeed={speed}"],
            ]:
                self._log(" ".join(cmd), "cmd")
                _, err, rc = run_cmd(cmd)
                if rc != 0:
                    self._log(f"Failed: {err}", "error")
                    return
            self._log(f"Fan speed set to {speed}%.", "success")
            self.settings["fan_speed_pct"] = speed
            self.settings["fan_control_manual"] = True
            self._save_settings()

        def _apply_clock_offsets(self):
            core = self._clock_offset_core_var.get()
            mem = self._clock_offset_mem_var.get()
            for cmd in [
                ["nvidia-settings", "-a", f"GPUGraphicsClockOffsetAllPerformanceLevels={core}"],
                ["nvidia-settings", "-a", f"GPUMemoryTransferRateOffsetAllPerformanceLevels={mem}"],
            ]:
                self._log(" ".join(cmd), "cmd")
                _, err, rc = run_cmd(cmd)
                if rc != 0:
                    self._log(f"Failed: {err}", "error")
                    return
            self._log(f"Clock offsets: Core {core:+d} MHz, Mem {mem:+d} MHz.", "success")
            self.settings["clock_offset_core"] = core
            self.settings["clock_offset_mem"] = mem
            self._save_settings()

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: PRIME / OPTIMUS
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_prime_tab(self):
            f = self._frames["prime"]
            _make_section_header(f, "PRIME / Optimus GPU Switching")
            tk.Label(
                f,
                text=(
                    "Switch between NVIDIA discrete GPU and integrated graphics.\n"
                    "Useful for laptops with hybrid graphics (NVIDIA Optimus)."
                ),
                font=("monospace", 9),
                fg=TEXT_SECOND,
                bg=BG_DARK,
                justify="left",
            ).pack(anchor="w", pady=(0, 10))

            self._prime_status_label = tk.Label(
                f,
                text="Current PRIME profile: Detecting...",
                font=("monospace", 11, "bold"),
                fg=NVIDIA_GREEN,
                bg=BG_DARK,
            )
            self._prime_status_label.pack(anchor="w", pady=(0, 12))

            for mode_key, mode_name, mode_desc in [
                ("nvidia", "NVIDIA (Performance)", "Discrete NVIDIA GPU for all rendering. Best performance."),
                (
                    "on-demand",
                    "On-Demand (Hybrid)",
                    "Integrated GPU default, offload to NVIDIA with __NV_PRIME_RENDER_OFFLOAD=1.",
                ),
                ("intel", "Intel (Power Save)", "Only integrated graphics. NVIDIA GPU powered off. Best battery."),
            ]:
                card = _make_card(f, padx=14, pady=10)
                card.pack(fill="x", pady=2)
                top = tk.Frame(card, bg=BG_CARD)
                top.pack(fill="x")
                tk.Label(
                    top, text=mode_name, font=("monospace", 11, "bold"), fg=TEXT_PRIMARY, bg=BG_CARD
                ).pack(side="left")
                _make_green_btn(top, "Switch", lambda m=mode_key: self._set_prime_mode(m)).pack(side="right")
                tk.Label(card, text=mode_desc, font=("monospace", 9), fg=TEXT_DIM, bg=BG_CARD, anchor="w").pack(
                    fill="x", pady=(3, 0)
                )

            _make_section_label(f, "RENDER OFFLOAD TEST")
            test_card = _make_card(f, padx=14, pady=10)
            test_card.pack(fill="x")
            btn_row = tk.Frame(test_card, bg=BG_CARD, pady=4)
            btn_row.pack(fill="x")
            self._make_action_btn(btn_row, "Test Default GPU", self._test_default_gpu).pack(side="left")
            self._make_action_btn(btn_row, "Test NVIDIA Offload", self._test_offload_gpu).pack(side="left", padx=8)
            self._prime_test_label = tk.Label(
                test_card, text="", font=("monospace", 9), fg=NVIDIA_GREEN, bg=BG_CARD, anchor="w"
            )
            self._prime_test_label.pack(fill="x", pady=(4, 0))

        def _detect_prime_mode(self):
            out, _, rc = run_cmd(["prime-select", "query"])
            if rc == 0 and out:
                self._prime_status_label.configure(text=f"Current PRIME profile: {out}", fg=NVIDIA_GREEN)
            else:
                self._prime_status_label.configure(text="PRIME not available (prime-select not found)", fg=ORANGE)

        def _set_prime_mode(self, mode):
            if messagebox.askyesno("Switch PRIME", f"Switch to '{mode}'?\nLogout/reboot required."):
                self._log(f"sudo prime-select {mode}", "cmd")
                _, err, rc = run_cmd(["sudo", "prime-select", mode])
                if rc == 0:
                    self._log(f"PRIME set to '{mode}'. Reboot required.", "success")
                    self.settings["prime_mode"] = mode
                    self._save_settings()
                    self._detect_prime_mode()
                else:
                    self._log(f"Failed: {err}", "error")

        def _test_default_gpu(self):
            out, _, rc = run_cmd(["glxinfo"])
            if rc == 0:
                for line in out.split("\n"):
                    if "OpenGL renderer" in line:
                        self._prime_test_label.configure(text=f"Default: {line.strip()}", fg=TEXT_PRIMARY)
                        return
            self._prime_test_label.configure(text="glxinfo not found. sudo apt install mesa-utils", fg=ORANGE)

        def _test_offload_gpu(self):
            env = os.environ.copy()
            env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
            env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
            try:
                r = subprocess.run(["glxinfo"], capture_output=True, text=True, env=env, timeout=10, check=False)
                for line in r.stdout.split("\n"):
                    if "OpenGL renderer" in line:
                        self._prime_test_label.configure(text=f"Offload: {line.strip()}", fg=NVIDIA_GREEN)
                        return
            except (OSError, subprocess.SubprocessError) as e:
                self._prime_test_label.configure(text=str(e), fg=RED)

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: XORG CONFIG
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_xorg_tab(self):
            f = self._frames["xorg"]
            _make_section_header(f, "Xorg Configuration")
            tk.Label(
                f,
                text="Generate Xorg config for NVIDIA with Coolbits, compositing, and Optimus support.",
                font=("monospace", 9),
                fg=TEXT_SECOND,
                bg=BG_DARK,
                justify="left",
            ).pack(anchor="w", pady=(0, 8))

            opt_card = _make_card(f, padx=14, pady=4)
            opt_card.pack(fill="x", pady=(0, 8))
            self._xorg_coolbits_var = tk.BooleanVar(value=True)
            self._xorg_triple_var = tk.BooleanVar(value=False)
            self._xorg_comp_pipe_var = tk.BooleanVar(value=True)
            self._xorg_modeset_var = tk.BooleanVar(value=True)
            self._xorg_allow_empty_var = tk.BooleanVar(value=False)
            _make_toggle_row(opt_card, "Coolbits=31 (OC, fan, voltage control)", self._xorg_coolbits_var)
            _make_toggle_row(opt_card, "Triple Buffering", self._xorg_triple_var)
            _make_toggle_row(opt_card, "ForceFullCompositionPipeline (anti-tearing)", self._xorg_comp_pipe_var)
            _make_toggle_row(opt_card, "nvidia-drm modeset=1", self._xorg_modeset_var)
            _make_toggle_row(opt_card, "AllowEmptyInitialConfiguration (Optimus)", self._xorg_allow_empty_var)

            btn_row = tk.Frame(f, bg=BG_DARK)
            btn_row.pack(fill="x", pady=(0, 6))
            _make_green_btn(btn_row, "Generate Config", self._generate_xorg).pack(side="left")
            self._make_action_btn(btn_row, "View /etc/X11/xorg.conf", self._view_xorg_conf).pack(side="left", padx=6)
            self._make_action_btn(btn_row, "nvidia-xconfig", self._run_nvidia_xconfig).pack(side="left", padx=6)
            self._make_action_btn(btn_row, "Save to File", self._save_xorg, fg_color=NVIDIA_GREEN).pack(side="right")

            self._xorg_text = scrolledtext.ScrolledText(
                f,
                bg="#0a0b0d",
                fg=NVIDIA_GREEN,
                font=("monospace", 10),
                highlightthickness=1,
                highlightbackground=BORDER,
                padx=10,
                pady=8,
                wrap="none",
                state="disabled",
                cursor="arrow",
            )
            self._xorg_text.pack(fill="both", expand=True)

        def _generate_xorg(self):
            lines = [
                "# Auto-generated by NVIDIA Driver Manager",
                f'# {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                "",
                'Section "Device"',
                '    Identifier     "Device0"',
                '    Driver         "nvidia"',
                '    VendorName     "NVIDIA Corporation"',
            ]
            bus = self.gpu_info.get("bus_id", "")
            if bus:
                m = re.match(r"\d+:(\d+):(\d+)\.(\d+)", bus)
                if m:
                    lines.append(f'    BusID          "PCI:{int(m.group(1))}:{int(m.group(2))}:{int(m.group(3))}"')
            if self._xorg_coolbits_var.get():
                lines.append('    Option         "Coolbits" "31"')
            if self._xorg_triple_var.get():
                lines.append('    Option         "TripleBuffer" "true"')
            if self._xorg_allow_empty_var.get():
                lines.append('    Option         "AllowEmptyInitialConfiguration"')
            lines += ["EndSection", ""]
            if self._xorg_comp_pipe_var.get():
                lines += [
                    'Section "Screen"',
                    '    Identifier     "Screen0"',
                    '    Device         "Device0"',
                    '    Option         "metamodes" "nvidia-auto-select +0+0 {ForceFullCompositionPipeline=On}"',
                    "EndSection",
                    "",
                ]
            if self._xorg_modeset_var.get():
                lines += ["# /etc/modprobe.d/nvidia.conf:", "# options nvidia-drm modeset=1"]
            self._xorg_text.delete("1.0", "end")
            self._xorg_text.insert("1.0", "\n".join(lines))


                                        # This GUI module is large; we use a focused module-level
                                        # pylint:disable at the file top to relax structural checks.
        def _view_xorg_conf(self):
            try:
                with open("/etc/X11/xorg.conf", encoding="utf-8", errors="ignore") as fp:
                    self._xorg_text.delete("1.0", "end")
                    self._xorg_text.insert("1.0", fp.read())
            except FileNotFoundError:
                self._xorg_text.delete("1.0", "end")
                self._xorg_text.insert(
                    "1.0", "# /etc/X11/xorg.conf does not exist.\n# Generate one or use nvidia-xconfig."
                )
            except PermissionError:
                self._xorg_text.delete("1.0", "end")
                self._xorg_text.insert("1.0", "# Permission denied. Run as root.")

        def _run_nvidia_xconfig(self):
            if messagebox.askyesno("nvidia-xconfig", "Run 'sudo nvidia-xconfig'? Overwrites /etc/X11/xorg.conf."):
                self._log("sudo nvidia-xconfig", "cmd")
                _, err, rc = run_cmd(["sudo", "nvidia-xconfig"])
                if rc == 0:
                    self._log("nvidia-xconfig done.", "success")
                    self._view_xorg_conf()
                else:
                    self._log(f"Failed: {err}", "error")

        def _save_xorg(self):
            content = self._xorg_text.get("1.0", "end").strip()
            if not content:
                messagebox.showinfo("Empty", "Generate a config first.")
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".conf",
                initialfile="20-nvidia.conf",
                filetypes=[("Xorg Config", "*.conf"), ("All", "*.*")],
                initialdir="/etc/X11/xorg.conf.d/",
            )
            if path:
                try:
                    with open(path, "w", encoding="utf-8") as fp:
                        fp.write(content)
                    self._log(f"Saved to {path}", "success")
                except PermissionError:
                    proc = subprocess.run(
                        ["sudo", "tee", path], input=content, capture_output=True, text=True, timeout=10, check=False
                    )
                    if proc.returncode == 0:
                        self._log(f"Saved to {path} (sudo)", "success")
                    else:
                        self._log(f"Failed: {proc.stderr}", "error")

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: KERNEL MODULES
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_kernel_tab(self):
            f = self._frames["kernel"]
            _make_section_header(f, "Kernel Module Parameters")
            tk.Label(
                f,
                text="Configure NVreg parameters, nouveau blacklist, and DKMS.\nChanges written to /etc/modprobe.d/ require reboot.",
                font=("monospace", 9),
                fg=TEXT_SECOND,
                bg=BG_DARK,
                justify="left",
            ).pack(anchor="w", pady=(0, 8))

            _make_section_label(f, "NOUVEAU DRIVER")
            nc = _make_card(f, padx=14, pady=6)
            nc.pack(fill="x", pady=(0, 8))
            self._nouveau_var = tk.BooleanVar(value=self.settings.get("blacklist_nouveau", True))
            _make_toggle_row(nc, "Blacklist nouveau (required for NVIDIA driver)", self._nouveau_var)
            _make_green_btn(nc, "Apply Blacklist", self._apply_nouveau_blacklist).pack(anchor="e", pady=(4, 2))

            _make_section_label(f, "NVREG PARAMETERS")
            nv = _make_card(f, padx=14, pady=6)
            nv.pack(fill="x", pady=(0, 8))
            self._nvreg_psr_var = tk.BooleanVar(value=self.settings.get("nvreg_psr", False))
            self._nvreg_preserve_var = tk.BooleanVar(value=self.settings.get("nvreg_preserve_video_memory", False))
            self._nvreg_recovery_var = tk.BooleanVar(value=self.settings.get("nvreg_gpu_recovery", True))
            _make_toggle_row(nv, "NVreg_EnablePCIeRelaxedOrderingMode", self._nvreg_psr_var)
            _make_toggle_row(nv, "NVreg_PreserveVideoMemoryAllocations (suspend/resume)", self._nvreg_preserve_var)
            _make_toggle_row(nv, "NVreg_EnableGpuFirmware (GSP firmware)", self._nvreg_recovery_var)

            thresh_row = tk.Frame(nv, bg=BG_CARD, pady=4)
            thresh_row.pack(fill="x")
            tk.Label(
                thresh_row,
                text="NVreg_TemperatureThreshold (\u00B0C)",
                font=("monospace", 10),
                fg=TEXT_PRIMARY,
                bg=BG_CARD,
            ).pack(side="left")
            self._nvreg_temp_var = tk.IntVar(value=int(self.settings.get("nvreg_temp_threshold", 97)))
            tk.Spinbox(
                thresh_row,
                from_=70,
                to=105,
                textvariable=self._nvreg_temp_var,
                width=4,
                font=("monospace", 10),
                bg=BG_INPUT,
                fg=TEXT_PRIMARY,
                buttonbackground=BG_CARD,
                highlightthickness=0,
                bd=1,
                insertbackground=NVIDIA_GREEN,
            ).pack(side="right")
            _make_green_btn(nv, "Write NVreg Config", self._write_nvreg_config).pack(anchor="e", pady=(6, 2))

            _make_section_label(f, "DKMS STATUS")
            self._dkms_text = scrolledtext.ScrolledText(
                f,
                bg="#0a0b0d",
                fg=TEXT_SECOND,
                font=("monospace", 9),
                highlightthickness=1,
                highlightbackground=BORDER,
                padx=10,
                pady=6,
                wrap="word",
                state="disabled",
                height=5,
            )
            self._dkms_text.pack(fill="both", expand=True, pady=(0, 4))
            self._make_action_btn(f, "\u21BB Check DKMS", self._check_dkms).pack(anchor="w")

        def _apply_nouveau_blacklist(self):
            path = "/etc/modprobe.d/blacklist-nouveau.conf"
            content = (
                "blacklist nouveau\noptions nouveau modeset=0\n"
                if self._nouveau_var.get()
                else "# nouveau not blacklisted\n"
            )
            self._log(f"Writing {path}", "cmd")
            proc = subprocess.run(["sudo", "tee", path], input=content, capture_output=True, text=True, timeout=10, check=False)
            if proc.returncode == 0:
                self._log("Nouveau blacklist updated.", "success")
                self.settings["blacklist_nouveau"] = self._nouveau_var.get()
                self._save_settings()
                self._log("sudo update-initramfs -u", "cmd")
                run_cmd(["sudo", "update-initramfs", "-u"], timeout=120)
                self._log("initramfs updated. Reboot required.", "success")
            else:
                self._log(f"Failed: {proc.stderr}", "error")

        def _write_nvreg_config(self):
            path = "/etc/modprobe.d/nvidia-nvreg.conf"
            opts = []
            if self._nvreg_psr_var.get():
                opts.append("NVreg_EnablePCIeRelaxedOrderingMode=1")
            if self._nvreg_preserve_var.get():
                opts.append("NVreg_PreserveVideoMemoryAllocations=1")
                opts.append("NVreg_TemporaryFilePath=/var/tmp")
            if self._nvreg_recovery_var.get():
                opts.append("NVreg_EnableGpuFirmware=1")
            opts.append(f"NVreg_TemperatureThreshold={self._nvreg_temp_var.get()}")

            content = f"# NVreg params - NVIDIA Driver Manager\noptions nvidia {' '.join(opts)}\n"
            self._log(f"Writing {path}", "cmd")
            proc = subprocess.run(["sudo", "tee", path], input=content, capture_output=True, text=True, timeout=10, check=False)
            if proc.returncode == 0:
                self._log("NVreg config written. Reboot required.", "success")
                for k, v in [
                    ("nvreg_psr", self._nvreg_psr_var),
                    ("nvreg_preserve_video_memory", self._nvreg_preserve_var),
                    ("nvreg_gpu_recovery", self._nvreg_recovery_var),
                ]:
                    self.settings[k] = v.get()
                self.settings["nvreg_temp_threshold"] = self._nvreg_temp_var.get()
                self._save_settings()
            else:
                self._log(f"Failed: {proc.stderr}", "error")

        def _check_dkms(self):
            out, err, rc = run_cmd(["dkms", "status"])
            self._dkms_text.configure(state="normal")
            self._dkms_text.delete("1.0", "end")
            self._dkms_text.insert("1.0", out if rc == 0 and out else f"DKMS unavailable.\n{err}")
            self._dkms_text.configure(state="disabled")

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: SETTINGS
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_settings_tab(self):
            f = self._frames["settings"]
            _make_section_header(f, "General Driver Settings")
            self._setting_vars = {}
            for section_name, toggles in [
                (
                    "DRIVER INSTALLATION",
                    [
                        ("secure_boot_sign", "Sign kernel modules for Secure Boot"),
                        ("open_source_modules", "Use open-source kernel modules (open-gpu-kernel-modules)"),
                    ],
                ),
                (
                    "SERVICES",
                    [
                        ("persistence_mode", "nvidia-persistenced (keep driver loaded)"),
                        ("wayland_compat", "Wayland compatibility patches"),
                    ],
                ),
                (
                    "DISPLAY",
                    [
                        ("drm_modeset", "nvidia-drm.modeset=1 (required for Wayland)"),
                        ("coolbits", "Enable Coolbits in Xorg (for OC/fan control)"),
                    ],
                ),
            ]:
                _make_section_label(f, section_name)
                card = _make_card(f, padx=14, pady=3)
                card.pack(fill="x", pady=(0, 4))
                for key, label in toggles:
                    var = tk.BooleanVar(value=self.settings.get(key, False))
                    self._setting_vars[key] = var
                    _make_toggle_row(card, label, var, callback=lambda k=key, v=var: self._toggle_setting(k, v))

            _make_section_label(f, "POWER MANAGEMENT")
            pm_card = _make_card(f, padx=14, pady=8)
            pm_card.pack(fill="x")
            tk.Label(pm_card, text="PowerMizer Mode", font=("monospace", 10), fg=TEXT_PRIMARY, bg=BG_CARD).pack(
                side="left"
            )
            self._pm_var = tk.StringVar(value=self.settings.get("powermizer", "Adaptive"))
            ttk.Combobox(
                pm_card,
                textvariable=self._pm_var,
                state="readonly",
                values=["Adaptive", "Max Performance", "Power Save"],
                width=18,
            ).pack(side="right")

            _make_section_label(f, "CONFIG FILE")
            tk.Label(f, text=str(CONFIG_PATH), font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK).pack(anchor="w")

            # UPDATES section
            _make_section_label(f, "UPDATES")
            card = _make_card(f, padx=14, pady=8)
            card.pack(fill="x")
            # Toggle for enabling update checks
            self._updates_var = tk.BooleanVar(value=self.settings.get("enable_update_checks", True))
            def _toggle_updates():
                self.settings["enable_update_checks"] = bool(self._updates_var.get())
                self._save_settings()

            _make_toggle_row(card, "Enable automatic update checks", self._updates_var, callback=_toggle_updates)
            # Interval input
            interval_row = tk.Frame(card, bg=BG_CARD)
            interval_row.pack(fill="x", pady=(6, 0))
            tk.Label(interval_row, text="Check interval (seconds)", font=("monospace", 9), fg=TEXT_DIM, bg=BG_CARD).pack(
                side="left"
            )
            self._update_interval_var = tk.StringVar(value=str(self.settings.get("update_check_interval_sec", 3600)))
            interval_entry = tk.Entry(interval_row, textvariable=self._update_interval_var, width=10, bg=BG_INPUT, fg=TEXT_PRIMARY)
            interval_entry.pack(side="right")

            def _save_interval():
                try:
                    v = int(self._update_interval_var.get())
                    self.settings["update_check_interval_sec"] = max(30, v)
                    self._save_settings()
                    interval = self.settings["update_check_interval_sec"]
                    self._log(f"Update interval set to {interval}s", "info")
                except (ValueError, TypeError):
                    messagebox.showerror("Invalid", "Enter a valid integer number of seconds (>=30).")

            tk.Button(card, text="Save interval", font=("monospace", 9), command=_save_interval, bd=0, bg=BG_CARD, fg=TEXT_PRIMARY).pack(anchor="e", pady=(6, 0))

            # Check for updates now button
            btn = _make_green_btn(card, "Check for updates now", lambda: self._check_for_updates(manual=True))
            btn.pack(anchor="e", pady=(8, 0))

            # Changelog preview
            tk.Label(f, text="Changelog preview", font=("monospace", 8, "bold"), fg=TEXT_DIM, bg=BG_DARK).pack(anchor="w", pady=(8, 4))
            self._updates_preview_text = scrolledtext.ScrolledText(
                f,
                bg=BG_INPUT,
                fg=TEXT_PRIMARY,
                font=("monospace", 10),
                height=8,
                wrap="word",
                state="disabled",
            )
            self._updates_preview_text.pack(fill="both", pady=(0, 8))

        def _toggle_setting(self, key, var):
            self.settings[key] = var.get()
            self._save_settings()

        # ═══════════════════════════════════════════════════════════════════════════
        #  TAB: TERMINAL
        # ═══════════════════════════════════════════════════════════════════════════
        def _build_terminal_tab(self):
            f = self._frames["terminal"]
            header = tk.Frame(f, bg=BG_DARK)
            header.pack(fill="x", pady=(0, 6))
            tk.Label(header, text="Terminal Output", font=("Helvetica", 14, "bold"), fg=TEXT_PRIMARY, bg=BG_DARK).pack(
                side="left"
            )
            self._term_badge = tk.Label(header, text="", font=("monospace", 9, "bold"), fg=TEXT_DIM, bg=BG_DARK)
            self._term_badge.pack(side="left", padx=12)
            def _clear_terminal():
                self._terminal.configure(state="normal")
                self._terminal.delete("1.0", "end")
                self._terminal.configure(state="disabled")

            self._make_action_btn(header, "Clear", _clear_terminal).pack(side="right")

            self._progress_var = tk.DoubleVar(value=0)
            pf = tk.Frame(f, bg=BG_DARK)
            pf.pack(fill="x", pady=(0, 4))
            self._progress_label = tk.Label(pf, text="", font=("monospace", 9), fg=TEXT_DIM, bg=BG_DARK, anchor="w")
            self._progress_label.pack(fill="x")
            self._progress_bar = ttk.Progressbar(pf, variable=self._progress_var, maximum=100, mode="determinate")
            self._progress_bar.pack(fill="x", pady=(2, 0))

            self._terminal = scrolledtext.ScrolledText(
                f,
                bg="#0a0b0d",
                fg=TEXT_SECOND,
                font=("monospace", 10),
                insertbackground=NVIDIA_GREEN,
                selectbackground=GREEN_SELECT,
                highlightthickness=1,
                highlightbackground=BORDER,
                padx=12,
                pady=10,
                wrap="word",
                state="disabled",
                cursor="arrow",
            )
            self._terminal.pack(fill="both", expand=True)
            for tag, color in [
                ("info", TEXT_SECOND),
                ("success", NVIDIA_GREEN),
                ("warn", ORANGE),
                ("error", RED),
                ("cmd", CYAN),
            ]:
                self._terminal.tag_configure(tag, foreground=color)

        def _log(self, text, level="info"):
            prefix = {"info": "\u2139", "success": "\u2713", "warn": "\u26A0", "error": "\u2717", "cmd": "$"}.get(
                level, " "
            )

            def _do():
                self._terminal.configure(state="normal")
                self._terminal.insert("end", f" {prefix}  {text}\n", level)
                self._terminal.see("end")
                self._terminal.configure(state="disabled")

            self._schedule(_do)

        # ═══════════════════════════════════════════════════════════════════════════
        #  DRIVER INSTALL / REMOVE
        # ═══════════════════════════════════════════════════════════════════════════
        # ── pip helper ───────────────────────────────────────────────────────────
        @staticmethod
        def _resolve_cmd(cmd_str: str) -> list[str]:
            """Convert a command string to an argument list.

            * Replaces a leading ``pip`` / ``pip3`` token with
              ``sys.executable -m pip`` so installs always go into the same
              Python environment that is running the app (venv-aware).
            * Appends ``--break-system-packages`` when running outside a
              virtual-env so PEP 668 externally-managed guards don't block
              installs on modern Debian / Ubuntu systems.
            * Uses :func:`shlex.split` so quoted arguments (e.g.
              ``"jax[cuda12]"``) are tokenized correctly.
            """
            cmd_str = cmd_str.strip()
            # Normalise: "pip install …" / "pip3 install …"
            if re.match(r"^pip3?\s", cmd_str):
                cmd_str = sys.executable + " -m pip " + cmd_str.split(None, 1)[1]
            # If it's a pip install/uninstall, add --break-system-packages
            # when we are NOT inside a virtual-env (avoids PEP 668 errors).
            if " -m pip " in cmd_str and not (
                hasattr(sys, "real_prefix")
                or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
            ):
                # Only add if not already present
                if "--break-system-packages" not in cmd_str:
                    # Insert the flag right after "pip install" / "pip uninstall"
                    cmd_str = re.sub(
                        r"(-m pip (?:install|uninstall))",
                        r"\1 --break-system-packages",
                        cmd_str,
                    )
            try:
                return shlex.split(cmd_str)
            except ValueError:
                return cmd_str.split()

        def _install_level_zero_from_source(self):
            """Clone, build, and install Intel Level Zero from the official git repo."""
            if self.busy:
                return
            repo_url = "https://github.com/oneapi-src/level-zero.git"
            if not messagebox.askyesno(
                "Build Level Zero from source",
                f"This will clone, build, and install Intel Level Zero from:\n"
                f"{repo_url}\n\n"
                f"Requires: git, cmake, build-essential.\n"
                f"Libraries will be installed system-wide via cmake --install.",
            ):
                return
            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  BUILDING  ", fg=CYAN)
            self._progress_var.set(0)
            self._progress_label.configure(text="Building Level Zero from source...")

            def _do():
                import tempfile  # pylint: disable=import-outside-toplevel
                build_dir = os.path.join(tempfile.gettempdir(), "level-zero-build")
                src_dir = os.path.join(build_dir, "level-zero")
                success = False
                try:
                    os.makedirs(build_dir, exist_ok=True)

                    # ── Step 1: Clone ──
                    self._log("=" * 60, "info")
                    self._log("LEVEL ZERO — BUILD FROM SOURCE", "info")
                    self._log("=" * 60, "info")
                    self._log(f"Repository: {repo_url}", "info")
                    self._schedule(lambda: self._progress_var.set(5))

                    if os.path.isdir(os.path.join(src_dir, ".git")):
                        self._log("Source already cloned, pulling latest...", "info")
                        rc = run_cmd_stream(["git", "-C", src_dir, "pull", "--ff-only"],
                                            self._log, timeout=120)
                        if rc != 0:
                            self._log("git pull failed, re-cloning...", "warn")
                            shutil.rmtree(src_dir, ignore_errors=True)
                            rc = run_cmd_stream(
                                ["git", "clone", "--depth=1", repo_url, src_dir],
                                self._log, timeout=180)
                    else:
                        if os.path.exists(src_dir):
                            shutil.rmtree(src_dir, ignore_errors=True)
                        self._log("Cloning repository...", "info")
                        rc = run_cmd_stream(
                            ["git", "clone", "--depth=1", repo_url, src_dir],
                            self._log, timeout=180)

                    if rc != 0:
                        self._log("git clone failed.", "error")
                        self._finish_action(False)
                        return
                    self._schedule(lambda: self._progress_var.set(20))

                    # ── Step 2: CMake configure ──
                    self._log("Configuring with CMake...", "info")
                    cmake_build = os.path.join(src_dir, "build")
                    cmake_args = [
                        "cmake", "-B", cmake_build, "-S", src_dir,
                        "-DCMAKE_BUILD_TYPE=Release",
                        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                        "-Wno-dev",
                    ]
                    rc = run_cmd_stream(cmake_args, self._log, timeout=120)
                    if rc != 0:
                        self._log("CMake configure failed.", "error")
                        self._finish_action(False)
                        return
                    self._schedule(lambda: self._progress_var.set(35))

                    # ── Step 3: Build ──
                    nproc = os.cpu_count() or 4
                    self._log(f"Building with {nproc} parallel jobs...", "info")
                    rc = run_cmd_stream(
                        ["cmake", "--build", cmake_build, "--parallel", str(nproc)],
                        self._log, timeout=600)
                    if rc != 0:
                        self._log("Build failed.", "error")
                        self._finish_action(False)
                        return
                    self._schedule(lambda: self._progress_var.set(70))

                    # ── Step 4: Build .deb packages ──
                    self._log("Building .deb packages...", "info")
                    rc = run_cmd_stream(
                        ["cmake", "--build", cmake_build, "--target", "package"],
                        self._log, timeout=120)
                    if rc != 0:
                        self._log("Package build failed, falling back to cmake --install.", "warn")

                    self._schedule(lambda: self._progress_var.set(80))

                    # ── Step 5: Install ──
                    # Prefer .deb if available, otherwise cmake --install
                    import glob  # pylint: disable=import-outside-toplevel
                    debs = sorted(glob.glob(os.path.join(cmake_build, "level-zero*.deb")))
                    if debs:
                        self._log(f"Installing {len(debs)} .deb package(s)...", "info")
                        rc = run_cmd_stream(
                            ["sudo", "dpkg", "-i"] + debs,
                            self._log, timeout=120)
                    else:
                        self._log("Installing via cmake --install...", "info")
                        rc = run_cmd_stream(
                            ["sudo", "cmake", "--install", cmake_build],
                            self._log, timeout=120)

                    if rc != 0:
                        self._log("Install failed.", "error")
                        self._finish_action(False)
                        return
                    self._schedule(lambda: self._progress_var.set(90))

                    # ── Step 6: ldconfig ──
                    self._log("Refreshing shared library cache...", "info")
                    run_cmd_stream(["sudo", "ldconfig"], self._log, timeout=30)

                    # ── Verify ──
                    out, _, rc_v = run_cmd(["pkg-config", "--modversion", "level-zero"], timeout=5)
                    if rc_v == 0 and out:
                        self._log(f"Level Zero version: {out}", "success")
                    out2, _, _ = run_cmd(["ldconfig", "-p"], timeout=5)
                    for lib_name in ("libze_loader", "libze_intel_npu"):
                        if lib_name in (out2 or ""):
                            self._log(f"  {lib_name}: found in linker cache", "success")

                    # Check for ze_info (ships with compute-runtime, not level-zero loader)
                    ze_info_path = shutil.which("ze_info")
                    if ze_info_path is None:
                        for alt in ["/usr/local/bin/ze_info", "/usr/bin/ze_info",
                                    "/opt/intel/oneapi/compiler/latest/linux/bin/ze_info"]:
                            if os.path.isfile(alt):
                                ze_info_path = alt
                                break
                    if ze_info_path:
                        ze_info_path = str(ze_info_path)
                        self._log(f"  ze_info: {ze_info_path}", "success")
                    else:
                        self._log("  ze_info: not found (it is part of Intel compute-runtime,", "warn")
                        self._log("  not the level-zero loader. Use 'oneAPI Base Kit (build from source)'", "warn")
                        self._log("  to build compute-runtime which includes ze_info.)", "warn")

                    self._schedule(lambda: self._progress_var.set(100))
                    self._log("Level Zero built and installed from source.", "success")
                    success = True
                except OSError as exc:
                    self._log(f"Error: {exc}", "error")
                finally:
                    self._finish_action(success)

            threading.Thread(target=_do, daemon=True).start()

        def _install_oneapi_from_source(self):
            """Clone, build, and install key Intel oneAPI Base Kit components from source."""
            if self.busy:
                return

            components = [
                ("oneTBB", "https://github.com/oneapi-src/oneTBB.git"),
                ("oneDNN", "https://github.com/oneapi-src/oneDNN.git"),
                ("oneMKL", "https://github.com/oneapi-src/oneMKL.git"),
                ("compute-runtime", "https://github.com/intel/compute-runtime.git"),
            ]
            comp_list = "\n".join(f"  • {name}" for name, _ in components)
            if not messagebox.askyesno(
                "Build oneAPI Base Kit from source",
                f"This will clone, build, and install the following Intel oneAPI\n"
                f"components from their official GitHub repositories:\n\n"
                f"{comp_list}\n\n"
                f"Requires: git, cmake, build-essential, pkg-config.\n"
                f"Libraries will be installed system-wide.\n\n"
                f"This may take a long time (30+ minutes).",
            ):
                return

            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  BUILDING  ", fg=CYAN)
            self._progress_var.set(0)
            self._progress_label.configure(text="Building oneAPI from source...")

            def _do():
                import tempfile  # pylint: disable=import-outside-toplevel
                base_dir = os.path.join(tempfile.gettempdir(), "oneapi-build")
                success = False
                nproc = str(os.cpu_count() or 4)

                try:
                    os.makedirs(base_dir, exist_ok=True)
                    self._log("=" * 60, "info")
                    self._log("oneAPI BASE KIT — BUILD FROM SOURCE", "info")
                    self._log("=" * 60, "info")

                    total_components = len(components)
                    for idx, (name, repo_url) in enumerate(components):
                        pct_base = int(idx / total_components * 90)
                        pct_step = int(90 / total_components)
                        self._schedule(lambda p=pct_base: self._progress_var.set(p))

                        self._log("", "info")
                        self._log(f"── {name} ({idx + 1}/{total_components}) ──", "info")
                        self._log(f"Repository: {repo_url}", "info")

                        src_dir = os.path.join(base_dir, name)
                        cmake_build = os.path.join(src_dir, "build")

                        # ── Clone / pull ──
                        if os.path.isdir(os.path.join(src_dir, ".git")):
                            self._log("Source already cloned, pulling latest...", "info")
                            rc = run_cmd_stream(
                                ["git", "-C", src_dir, "pull", "--ff-only"],
                                self._log, timeout=120)
                            if rc != 0:
                                self._log("git pull failed, re-cloning...", "warn")
                                shutil.rmtree(src_dir, ignore_errors=True)
                                rc = run_cmd_stream(
                                    ["git", "clone", "--depth=1", repo_url, src_dir],
                                    self._log, timeout=300)
                        else:
                            if os.path.exists(src_dir):
                                shutil.rmtree(src_dir, ignore_errors=True)
                            self._log(f"Cloning {name}...", "info")
                            rc = run_cmd_stream(
                                ["git", "clone", "--depth=1", repo_url, src_dir],
                                self._log, timeout=300)

                        if rc != 0:
                            self._log(f"git clone failed for {name}.", "error")
                            self._finish_action(False)
                            return

                        self._schedule(lambda p=pct_base + pct_step // 4: self._progress_var.set(p))

                        # ── CMake configure ──
                        self._log(f"Configuring {name} with CMake...", "info")
                        os.makedirs(cmake_build, exist_ok=True)

                        cmake_args = [
                            "cmake", "-B", cmake_build, "-S", src_dir,
                            "-DCMAKE_BUILD_TYPE=Release",
                            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                            "-Wno-dev",
                        ]

                        # Component-specific CMake flags
                        if name == "oneTBB":
                            cmake_args.append("-DTBB_TEST=OFF")
                        elif name == "oneDNN":
                            cmake_args.extend(["-DDNNL_BUILD_TESTS=OFF", "-DDNNL_BUILD_EXAMPLES=OFF"])
                        elif name == "oneMKL":
                            cmake_args.extend(["-DBUILD_FUNCTIONAL_TESTS=OFF", "-DBUILD_EXAMPLES=OFF"])
                        elif name == "compute-runtime":
                            cmake_args.extend([
                                "-DSKIP_UNIT_TESTS=ON",
                                "-DSKIP_NEO_UNIT_TESTS=ON",
                                "-DBUILD_WITH_L0=ON",
                            ])

                        rc = run_cmd_stream(cmake_args, self._log, timeout=180)
                        if rc != 0:
                            self._log(f"CMake configure failed for {name}.", "error")
                            # Non-fatal: continue with next component
                            self._log(f"Skipping {name}, continuing with remaining components...", "warn")
                            continue

                        self._schedule(lambda p=pct_base + pct_step // 2: self._progress_var.set(p))

                        # ── Build ──
                        self._log(f"Building {name} with {nproc} parallel jobs...", "info")
                        rc = run_cmd_stream(
                            ["cmake", "--build", cmake_build, "--parallel", nproc],
                            self._log, timeout=1800)
                        if rc != 0:
                            self._log(f"Build failed for {name}.", "error")
                            self._log(f"Skipping {name}, continuing with remaining components...", "warn")
                            continue

                        self._schedule(lambda p=pct_base + 3 * pct_step // 4: self._progress_var.set(p))

                        # ── Install ──
                        self._log(f"Installing {name}...", "info")

                        # Try .deb packages first
                        import glob  # pylint: disable=import-outside-toplevel
                        debs = sorted(glob.glob(os.path.join(cmake_build, "*.deb")))
                        if debs:
                            self._log(f"Installing {len(debs)} .deb package(s) for {name}...", "info")
                            rc = run_cmd_stream(
                                ["sudo", "dpkg", "-i"] + debs,
                                self._log, timeout=120)
                            if rc != 0:
                                self._log("dpkg install failed, trying cmake --install...", "warn")
                                rc = run_cmd_stream(
                                    ["sudo", "cmake", "--install", cmake_build],
                                    self._log, timeout=120)
                        else:
                            rc = run_cmd_stream(
                                ["sudo", "cmake", "--install", cmake_build],
                                self._log, timeout=120)

                        if rc != 0:
                            self._log(f"Install failed for {name}.", "error")
                        else:
                            self._log(f"{name} installed successfully.", "success")

                        self._schedule(lambda p=pct_base + pct_step: self._progress_var.set(p))

                    # ── Final: ldconfig ──
                    self._log("", "info")
                    self._log("Refreshing shared library cache...", "info")
                    run_cmd_stream(["sudo", "ldconfig"], self._log, timeout=30)

                    # ── Verify key results ──
                    self._log("", "info")
                    self._log("── Verification ──", "info")

                    # Check for ze_info (shipped by compute-runtime)
                    ze_info_path = shutil.which("ze_info")
                    if ze_info_path is not None:
                        ze_info_path = str(ze_info_path)
                        self._log(f"ze_info: {ze_info_path}", "success")
                    else:
                        # Check common installation paths
                        for alt in ["/usr/local/bin/ze_info", "/usr/bin/ze_info"]:
                            if os.path.isfile(alt):
                                self._log(f"ze_info: {alt}", "success")
                                ze_info_path = alt
                                break
                        if not ze_info_path:
                            self._log("ze_info: not found (compute-runtime may not include it)", "warn")

                    # Check libraries
                    ld_out, _, _ = run_cmd(["ldconfig", "-p"], timeout=5)
                    for lib_name in ("libtbb", "libdnnl", "libze_loader", "libigdrcl"):
                        if lib_name in (ld_out or ""):
                            self._log(f"  {lib_name}: found in linker cache", "success")

                    self._schedule(lambda: self._progress_var.set(100))
                    self._log("", "info")
                    self._log("oneAPI Base Kit components built and installed from source.", "success")
                    success = True
                except OSError as exc:
                    self._log(f"Error: {exc}", "error")
                finally:
                    self._finish_action(success)

            threading.Thread(target=_do, daemon=True).start()

        def _install_igc_from_source(self):
            """Clone, build, and install Intel Graphics Compiler (IGC) from source.

            Follows the official build_ubuntu.md procedure:
            1. Install build deps (flex, bison, libz-dev, cmake, libzstd-dev).
            2. Clone IGC + all companion repos into the workspace layout that
               the IGC CMake build expects (LLVM 16.0.6, opencl-clang,
               SPIRV-LLVM-Translator, vc-intrinsics, SPIRV-Tools/Headers).
            3. Build with ``-DIGC_OPTION__LLVM_MODE=Source``.
            4. Install system-wide.
            """
            if self.busy:
                return
            if not messagebox.askyesno(
                "Build Intel IGC from source",
                "This will clone, build, and install the Intel Graphics\n"
                "Compiler (IGC) and all its dependencies from source:\n\n"
                "  • intel-graphics-compiler\n"
                "  • llvm-project  (tag llvmorg-16.0.6)\n"
                "  • opencl-clang  (branch ocl-open-160)\n"
                "  • SPIRV-LLVM-Translator  (branch llvm_release_160)\n"
                "  • vc-intrinsics\n"
                "  • SPIRV-Tools / SPIRV-Headers\n\n"
                "Requires: git, cmake ≥ 3.13, build-essential, flex, bison,\n"
                "          libz-dev, libzstd-dev, python3-mako.\n"
                "Libraries (libigc.so, libigdfcl.so) will be installed to /usr/local.\n\n"
                "This may take a very long time (30 – 90+ minutes).",
            ):
                return

            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  BUILDING  ", fg=CYAN)
            self._progress_var.set(0)
            self._progress_label.configure(text="Building Intel IGC from source...")

            def _do():
                import tempfile  # pylint: disable=import-outside-toplevel
                workspace = os.path.join(tempfile.gettempdir(), "igc-build")
                igc_dir = os.path.join(workspace, "igc")
                llvm_dir = os.path.join(workspace, "llvm-project")
                cmake_build = os.path.join(workspace, "build")
                success = False

                # Repository table — (target_dir, repo_url, branch_or_tag)
                # The directory layout MUST match what IGC's CMake expects.
                repos = [
                    (igc_dir,
                     "https://github.com/intel/intel-graphics-compiler.git",
                     None),
                    (llvm_dir,
                     "https://github.com/llvm/llvm-project.git",
                     "llvmorg-16.0.6"),
                    (os.path.join(llvm_dir, "llvm", "projects", "opencl-clang"),
                     "https://github.com/intel/opencl-clang.git",
                     "ocl-open-160"),
                    (os.path.join(llvm_dir, "llvm", "projects", "llvm-spirv"),
                     "https://github.com/KhronosGroup/SPIRV-LLVM-Translator.git",
                     "llvm_release_160"),
                    (os.path.join(workspace, "vc-intrinsics"),
                     "https://github.com/intel/vc-intrinsics.git",
                     None),
                    (os.path.join(workspace, "SPIRV-Tools"),
                     "https://github.com/KhronosGroup/SPIRV-Tools.git",
                     None),
                    (os.path.join(workspace, "SPIRV-Headers"),
                     "https://github.com/KhronosGroup/SPIRV-Headers.git",
                     None),
                ]

                try:
                    os.makedirs(workspace, exist_ok=True)

                    # ── Header ──
                    self._log("=" * 60, "info")
                    self._log("INTEL GRAPHICS COMPILER (IGC) — BUILD FROM SOURCE", "info")
                    self._log("=" * 60, "info")
                    self._log(f"Workspace: {workspace}", "info")
                    self._schedule(lambda: self._progress_var.set(2))

                    # ── Step 0: Install build deps ──
                    self._log("Installing build dependencies...", "info")
                    run_cmd_stream(
                        ["sudo", "apt-get", "install", "-y",
                         "flex", "bison", "libz-dev", "cmake", "libzstd-dev",
                         "python3-pip", "build-essential"],
                        self._log, timeout=120)
                    # mako is needed by the IGC build for codegen
                    run_cmd_stream(
                        ["sudo", "python3", "-m", "pip", "install", "--break-system-packages", "mako"],
                        self._log, timeout=60)
                    self._schedule(lambda: self._progress_var.set(5))

                    # ── Step 1: Clone / update every repository ──
                    total_repos = len(repos)
                    for idx, (dest, url, branch) in enumerate(repos):
                        pct = 5 + int((idx + 1) / total_repos * 25)  # 5 → 30
                        name = os.path.basename(dest)
                        if os.path.isdir(os.path.join(dest, ".git")):
                            self._log(f"[{idx+1}/{total_repos}] {name}: pulling latest...", "info")
                            rc = run_cmd_stream(
                                ["git", "-C", dest, "pull", "--ff-only"],
                                self._log, timeout=120)
                            if rc != 0:
                                self._log(f"  pull failed, re-cloning {name}...", "warn")
                                shutil.rmtree(dest, ignore_errors=True)
                            else:
                                self._schedule(lambda p=pct: self._progress_var.set(p))
                                continue

                        # Fresh clone
                        parent = os.path.dirname(dest)
                        os.makedirs(parent, exist_ok=True)
                        if os.path.exists(dest):
                            shutil.rmtree(dest, ignore_errors=True)

                        clone_cmd = ["git", "clone"]
                        if branch:
                            clone_cmd += ["-b", branch]
                        # Use depth=1 for everything except llvm-project
                        # (llvm-project needs the tag, depth=1 is fine with -b tag)
                        clone_cmd += ["--depth=1", url, dest]
                        self._log(f"[{idx+1}/{total_repos}] Cloning {name}"
                                  + (f"  (branch {branch})" if branch else "") + " ...", "info")
                        rc = run_cmd_stream(clone_cmd, self._log, timeout=600)
                        if rc != 0:
                            self._log(f"git clone failed for {name}.", "error")
                            self._finish_action(False)
                            return
                        self._schedule(lambda p=pct: self._progress_var.set(p))

                    self._schedule(lambda: self._progress_var.set(30))

                    # ── Step 2: CMake configure ──
                    os.makedirs(cmake_build, exist_ok=True)
                    nproc = os.cpu_count() or 4

                    # Prefer a system-installed LLVM 16 (prebuilt) if available.
                    llvm_prebuilt_path = None
                    llvm_cfg = shutil.which("llvm-config-16")
                    if llvm_cfg is not None:
                        out, _, rc_lc = run_cmd(["llvm-config-16", "--prefix"], timeout=5)
                        if rc_lc == 0 and out:
                            llvm_prebuilt_path = out.strip()
                    if not llvm_prebuilt_path and os.path.isdir("/usr/lib/llvm-16"):
                        llvm_prebuilt_path = "/usr/lib/llvm-16"

                    if llvm_prebuilt_path:
                        self._log(f"Configuring with CMake (Prebuilds mode) using LLVM at {llvm_prebuilt_path}...", "info")
                        # Create compiler wrapper that strips -Werror flags to avoid
                        # upstream projects promoting warnings to errors.
                        wrap_dir = os.path.join(workspace, "cc-wrap")
                        os.makedirs(wrap_dir, exist_ok=True)
                        cc_candidate = shutil.which("gcc")
                        cxx_candidate = shutil.which("g++")
                        real_cc = str(cc_candidate) if cc_candidate is not None else "/usr/bin/gcc"
                        real_cxx = str(cxx_candidate) if cxx_candidate is not None else "/usr/bin/g++"
                        cc_wrap = os.path.join(wrap_dir, "gcc")
                        cxx_wrap = os.path.join(wrap_dir, "g++")
                        with open(cc_wrap, "w", encoding="utf-8") as f:
                            f.write("""#!/bin/bash
args=()
for a in "$@"; do
  case "$a" in
    -Werror*|-Werror)
      # drop warning-as-error flags
      ;;
    *) args+=("$a") ;;
  esac
done
exec \"%s\" "${args[@]}"
""" % real_cc)
                        with open(cxx_wrap, "w", encoding="utf-8") as f:
                            f.write("""#!/bin/bash
args=()
for a in "$@"; do
  case "$a" in
    -Werror*|-Werror)
      ;;
    *) args+=("$a") ;;
  esac
done
exec \"%s\" "${args[@]}"
""" % real_cxx)
                        os.chmod(cc_wrap, 0o755)
                        os.chmod(cxx_wrap, 0o755)

                        cmake_args = [
                            "cmake",
                            os.path.join(igc_dir, "IGC"),
                            "-B", cmake_build,
                            "-DCMAKE_BUILD_TYPE=Release",
                            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                            "-DLLVM_ENABLE_WERROR=OFF",
                            "-DCLANG_WARNINGS_AS_ERRORS=OFF",
                            "-DCMAKE_C_FLAGS=-w -Wno-error -Wno-error=cpp",
                            "-DCMAKE_CXX_FLAGS=-w -Wno-error -Wno-error=cpp",
                            "-Wno-dev",
                            "-DIGC_OPTION__LLVM_MODE=Prebuilds",
                            f"-DLLVM_ROOT={llvm_prebuilt_path}",
                            f"-DCMAKE_C_COMPILER={cc_wrap}",
                            f"-DCMAKE_CXX_COMPILER={cxx_wrap}",
                        ]
                    else:
                        self._log("Configuring with CMake (Source mode)...", "info")
                        # Create compiler wrapper that strips -Werror flags (source mode)
                        wrap_dir = os.path.join(workspace, "cc-wrap")
                        os.makedirs(wrap_dir, exist_ok=True)
                        cc_candidate = shutil.which("gcc")
                        cxx_candidate = shutil.which("g++")
                        real_cc = str(cc_candidate) if cc_candidate is not None else "/usr/bin/gcc"
                        real_cxx = str(cxx_candidate) if cxx_candidate is not None else "/usr/bin/g++"
                        cc_wrap = os.path.join(wrap_dir, "gcc")
                        cxx_wrap = os.path.join(wrap_dir, "g++")
                        with open(cc_wrap, "w", encoding="utf-8") as f:
                            f.write("""#!/bin/bash
args=()
for a in "$@"; do
  case "$a" in
    -Werror*|-Werror)
      ;;
    *) args+=("$a") ;;
  esac
done
exec \"%s\" "${args[@]}"
""" % real_cc)
                        with open(cxx_wrap, "w", encoding="utf-8") as f:
                            f.write("""#!/bin/bash
args=()
for a in "$@"; do
  case "$a" in
    -Werror*|-Werror)
      ;;
    *) args+=("$a") ;;
  esac
done
exec \"%s\" "${args[@]}"
""" % real_cxx)
                        os.chmod(cc_wrap, 0o755)
                        os.chmod(cxx_wrap, 0o755)

                        cmake_args = [
                            "cmake",
                            os.path.join(igc_dir, "IGC"),
                            "-B", cmake_build,
                            "-DCMAKE_BUILD_TYPE=Release",
                            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                            "-DLLVM_ENABLE_WERROR=OFF",
                            "-DCLANG_WARNINGS_AS_ERRORS=OFF",
                            "-DCMAKE_C_FLAGS=-w -Wno-error -Wno-error=cpp",
                            "-DCMAKE_CXX_FLAGS=-w -Wno-error -Wno-error=cpp",
                            "-Wno-dev",
                            "-DIGC_OPTION__LLVM_MODE=Source",
                            f"-DIGC_OPTION__LLVM_SOURCES_DIR={llvm_dir}",
                            f"-DCMAKE_C_COMPILER={cc_wrap}",
                            f"-DCMAKE_CXX_COMPILER={cxx_wrap}",
                        ]

                    rc = run_cmd_stream(cmake_args, self._log, timeout=300)
                    if rc != 0:
                        self._log("CMake configure failed.", "error")
                        self._finish_action(False)
                        return
                    self._schedule(lambda: self._progress_var.set(40))

                    # ── Step 3: Build ──
                    self._log(f"Building with {nproc} parallel jobs (this will take a while)...", "info")
                    rc = run_cmd_stream(
                        ["cmake", "--build", cmake_build, "--parallel", str(nproc)],
                        self._log, timeout=5400)
                    if rc != 0:
                        self._log("Build failed.", "error")
                        self._finish_action(False)
                        return
                    self._schedule(lambda: self._progress_var.set(85))

                    # ── Step 4: Install ──
                    self._log("Installing...", "info")
                    rc = run_cmd_stream(
                        ["sudo", "cmake", "--install", cmake_build],
                        self._log, timeout=120)
                    if rc != 0:
                        self._log("Install failed.", "error")
                        self._finish_action(False)
                        return
                    self._schedule(lambda: self._progress_var.set(95))

                    # ── Step 5: ldconfig ──
                    self._log("Refreshing shared library cache...", "info")
                    run_cmd_stream(["sudo", "ldconfig"], self._log, timeout=30)

                    # ── Verify ──
                    self._log("Verifying installation...", "info")
                    ld_out, _, _ = run_cmd(["ldconfig", "-p"], timeout=5)
                    for lib in ("libigc.so", "libigdfcl.so"):
                        found = False
                        for path in ("/usr/local/lib", "/usr/lib"):
                            full = os.path.join(path, lib)
                            if os.path.isfile(full):
                                real = os.path.realpath(full)
                                self._log(f"  {lib}: {real}", "success")
                                found = True
                                break
                        if not found:
                            if lib in (ld_out or ""):
                                self._log(f"  {lib}: found in linker cache", "success")
                            else:
                                self._log(f"  {lib}: not found", "warn")

                    self._schedule(lambda: self._progress_var.set(100))
                    self._log("Intel Graphics Compiler built and installed from source.", "success")
                    success = True
                except OSError as exc:
                    self._log(f"Error: {exc}", "error")
                finally:
                    self._finish_action(success)

            threading.Thread(target=_do, daemon=True).start()

        def _run_install_thread(self, cmd_str, label):
            if self.busy:
                return
            if not messagebox.askyesno("Install", f"Install {label}?\n{cmd_str}"):
                return
            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  WORKING  ", fg=ORANGE)
            self._progress_var.set(0)
            self._progress_label.configure(text=f"Installing {label}...")

            def _do():
                self._log(cmd_str, "cmd")
                args = self._resolve_cmd(cmd_str)
                rc = run_cmd_stream(args, self._log, timeout=300)
                self._schedule(lambda: self._progress_var.set(100))
                if rc == 0:
                    self._log(f"{label} installed.", "success")
                    self._finish_action(True)
                else:
                    self._log(f"{label} failed.", "error")
                    self._finish_action(False)

            threading.Thread(target=_do, daemon=True).start()

        def _install_driver(self, drv):
            if self.busy:
                return
            pkg = drv["package"]
            msg = f"Install {pkg}?" if self.installed_driver.get() in ("None", "Detecting...") else f"Switch to {pkg}?"
            if not messagebox.askyesno("Confirm", msg):
                return
            self.busy = True
            self._switch_tab("terminal")
            self._term_badge.configure(text="  WORKING  ", fg=ORANGE)
            self._progress_var.set(0)
            self._progress_label.configure(text=f"Installing {pkg}...")
            # Use a lambda so static analyzers don't warn about the 'args' param
            threading.Thread(target=lambda p=pkg: self._do_install(p), daemon=True).start()

        def _do_install(self, package):
            self._log("sudo apt update", "cmd")
            self._schedule(lambda: self._progress_var.set(10))
            run_cmd_stream(["sudo", "apt", "update"], self._log, timeout=120)
            self._schedule(lambda: self._progress_var.set(25))

            cmd = ["sudo", "apt", "install", "-y", package]
            if self.settings.get("open_source_modules"):
                cmd.append(package + "-open")
            self._log(" ".join(cmd), "cmd")
            self._schedule(lambda: self._progress_var.set(30))
            rc = run_cmd_stream(cmd, self._log, timeout=600)
            self._schedule(lambda: self._progress_var.set(85))

            if rc != 0:
                self._log(f"Installation failed (exit {rc}).", "error")
                self._finish_action(False)
                return

            if self.settings.get("persistence_mode"):
                self._log("Enabling nvidia-persistenced...", "cmd")
                run_cmd(["sudo", "systemctl", "enable", "--now", "nvidia-persistenced"])

            if self.settings.get("drm_modeset"):
                try:
                    subprocess.run(
                        [
                            "sudo",
                            "bash",
                            "-c",
                            'echo "options nvidia-drm modeset=1" > /etc/modprobe.d/nvidia-drm-modeset.conf',
                        ],
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                    self._log("DRM modesetting enabled.", "success")
                except subprocess.SubprocessError:
                    pass

            if self.settings.get("blacklist_nouveau"):
                try:
                    blacklist_cmd = (
                        'echo -e "blacklist nouveau\\noptions nouveau modeset=0" '
                        "> /etc/modprobe.d/blacklist-nouveau.conf"
                    )
                    subprocess.run(
                        ["sudo", "bash", "-c", blacklist_cmd],
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                except subprocess.SubprocessError:
                    pass

            self._schedule(lambda: self._progress_var.set(100))
            self._log(f"{package} installed. Reboot recommended.", "success")
            self._finish_action(True)

        def _confirm_remove(self):
            if self.busy or self.installed_driver.get() in ("None", "Detecting..."):
                return
            msg = (
                "Remove all NVIDIA packages?\n"
                + "Current: "
                + str(self.installed_driver.get())
                + "\n\nFalls back to nouveau. Reboot required."
            )
            if messagebox.askyesno("Remove Driver", msg):
                self.busy = True
                self._switch_tab("terminal")
                self._term_badge.configure(text="  REMOVING  ", fg=RED)
                self._progress_var.set(0)
                self._progress_label.configure(text="Removing NVIDIA driver...")
                threading.Thread(target=self._do_remove, daemon=True).start()

        def _do_remove(self):
            self._log("sudo apt purge 'nvidia-*'", "cmd")
            self._schedule(lambda: self._progress_var.set(10))
            run_cmd_stream(["sudo", "apt", "purge", "-y", "nvidia-*"], self._log, timeout=300)
            self._schedule(lambda: self._progress_var.set(55))
            self._log("sudo apt autoremove -y", "cmd")
            run_cmd_stream(["sudo", "apt", "autoremove", "-y"], self._log, timeout=120)
            self._schedule(lambda: self._progress_var.set(100))
            self._log("All NVIDIA packages removed. Reboot required.", "success")
            self._finish_action(True, removed=True)

        def _finish_action(self, success, removed=False):
            self.busy = False

            def _do():
                self._term_badge.configure(
                    text="  COMPLETE  " if success else "  FAILED  ", fg=NVIDIA_GREEN if success else RED
                )
                if removed:
                    self.installed_driver.set("None")
                self._refresh_ui()

            self._schedule(_do)
            if success:
                threading.Thread(target=self._detect_all, daemon=True).start()

        # ═══════════════════════════════════════════════════════════════════════════
        #  UI REFRESH
        # ═══════════════════════════════════════════════════════════════════════════
        def _refresh_ui(self):
            cur = self.installed_driver.get()
            active = cur and cur not in ("None", "Detecting...")
            self._subtitle.configure(
                text=f"UBUNTU LINUX  \u2022  v{cur}  \u25CF" if active else "UBUNTU LINUX  \u2022  NO DRIVER"
            )
            # styled badge with background
            if active:
                self._status_badge.configure(
                    text="  \u25CF ACTIVE  ", fg=NVIDIA_GREEN,
                    bg="#1a2a10", highlightbackground="#2a4a10",
                )
            else:
                self._status_badge.configure(
                    text="  \u25CF NO DRIVER  ", fg=RED,
                    bg="#2a1010", highlightbackground="#5a2020",
                )

            g = self.gpu_info
            self._gpu_name_label.configure(text=g.get("name", "No GPU detected"))
            parts = [g.get("bus_id", "")]
            if "pcie_gen" in g:
                parts.append(f"PCIe Gen{g['pcie_gen']} x{g['pcie_width']}")
            self._gpu_sub_label.configure(text="  \u2022  ".join([p for p in parts if p]))

            # ── Update arc gauges ─────────────────────────────────────────────
            def _safe_float(v, fallback=0.0):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return fallback

            temp = _safe_float(g.get("temp"))
            gpu_pct = _safe_float(g.get("usage_gpu"))
            mem_pct = _safe_float(g.get("usage_mem"))
            pw_draw = _safe_float(g.get("power_draw"))
            pw_limit = _safe_float(g.get("power_limit"), 1)
            pw_pct = min(pw_draw / pw_limit * 100.0, 100.0) if pw_limit else 0

            temp_pct = min(temp / 100.0 * 100.0, 100.0)
            temp_color = CYAN if temp < 65 else (ORANGE if temp < 85 else RED)

            for gid, pct, val_text, color_override in [
                ("temp_gauge",  temp_pct, f"{g.get('temp', '--')}\u00B0C", temp_color),
                ("gpu_gauge",   gpu_pct,  f"{g.get('usage_gpu', '--')}%",  None),
                ("mem_gauge",   mem_pct,  f"{g.get('usage_mem', '--')}%",  None),
                ("power_gauge", pw_pct,   f"{g.get('power_draw', '--')} W", None),
            ]:
                cv, clr, sz = self._gauge_canvases[gid]
                draw_clr = color_override if color_override else clr
                _draw_arc_gauge(cv, pct, draw_clr, "", sz)
                lbl_widget = self._gauge_canvases.get(gid + "_lbl")
                if lbl_widget:
                    lbl_widget.configure(text=val_text)

            # ── Update VRAM bar ───────────────────────────────────────────────
            vram_used = _safe_float(g.get("vram_used"))
            vram_total = _safe_float(g.get("vram_total"), 1)
            vram_pct = vram_used / vram_total * 100.0 if vram_total else 0
            self._vram_pct_label.configure(text=f"{vram_pct:.1f}%  ({int(vram_used)} / {int(vram_total)} MiB)")
            self._vram_used_lbl.configure(text=f"Used: {int(vram_used)} MiB")
            self._vram_total_lbl.configure(text=f"Total: {int(vram_total)} MiB")
            self._redraw_vram_bar()

            # ── Update metric grid ────────────────────────────────────────────
            mmap = {
                "Fan Speed": (g.get("fan", "\u2014"), "%"),
                "Core Clock": (g.get("clock_core", "\u2014"), " MHz"),
                "Mem Clock": (g.get("clock_mem", "\u2014"), " MHz"),
                "Mem Util": (g.get("usage_mem", "\u2014"), "%"),
                "Power Draw": (g.get("power_draw", "\u2014"), " W"),
                "Power Limit": (g.get("power_limit", "\u2014"), " W"),
                "Bus ID": (g.get("bus_id", "\u2014"), ""),
                "PCIe": (f"Gen{g['pcie_gen']}x{g['pcie_width']}" if "pcie_gen" in g else "\u2014", ""),
            }
            for label, (val, unit) in mmap.items():
                if label in self._metric_labels:
                    self._metric_labels[label].configure(text=f"{val}{unit}" if val != "\u2014" else "\u2014")

            ext = self.gpu_info_extended
            self._drv_labels["Version"].configure(text=cur if active else "\u2014")
            self._drv_labels["CUDA Cap."].configure(text=ext.get("cuda_version", "\u2014"))
            self._drv_labels["VBIOS"].configure(text=g.get("vbios", "\u2014"))
            uuid = g.get("uuid", "\u2014")
            self._drv_labels["UUID"].configure(
                text=(uuid[:24] + "...") if uuid != "\u2014" and len(uuid) > 24 else uuid
            )
            self._drv_labels["Persistence"].configure(text=ext.get("persistence_mode", "\u2014"))
            self._drv_labels["Compute"].configure(text=ext.get("compute_mode", "\u2014"))

            key_map = {
                "Power Draw": "power_draw",
                "Power Limit": "power_limit",
                "Default Limit": "power_default",
                "Max Limit": "power_max",
                "Min Limit": "power_min",
            }
            for lb, key in key_map.items():
                val = g.get(key, "\u2014")
                if lb in self._power_labels:
                    self._power_labels[lb].configure(text=f"{val} W" if val != "\u2014" else "\u2014")

            self._populate_drivers_list()
            self._populate_runfile_list()
            self._refresh_cuda_ui()
            self._refresh_vulkan_ui()
            self._detect_prime_mode()

    _APP_CLASS = NvidiaDriverManager
    return _APP_CLASS
