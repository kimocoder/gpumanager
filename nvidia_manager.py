#!/usr/bin/env python3
"""
NVIDIA Driver Manager — Advanced Edition for Ubuntu Linux
A comprehensive GUI tool for NVIDIA driver management, GPU monitoring,
CUDA toolkit, power tuning, PRIME/Optimus, Xorg config, and more.

Requirements: Python 3.8+, tkinter
Run with:     sudo python3 nvidia_driver_manager.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import os
import re
import json
import urllib.request
import urllib.error
import shutil
from pathlib import Path

# ─── Color Palette (all 6-digit hex, no alpha — tkinter safe) ────────────────
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

# ─── Helpers ──────────────────────────────────────────────────────────────────


def run_cmd(cmd, timeout=15):
    """Run a shell command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", f"Command not found: {cmd[0]}", 127
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except (OSError, subprocess.SubprocessError) as e:
        return "", str(e), 1


def run_cmd_stream(cmd, log_fn, timeout=300):
    """Run a command and stream output line-by-line via log_fn. Returns exit code."""
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1) as proc:
            stdout = proc.stdout
            if stdout is None:
                log_fn("Failed to capture stdout", "error")
                return 1
            for line in iter(stdout.readline, ""):
                s = line.strip()
                if s:
                    lvl = "info"
                    sl = s.lower()
                    if "error" in sl or "failed" in sl:
                        lvl = "error"
                    elif "warning" in sl or "dkms" in sl:
                        lvl = "warn"
                    elif "done" in sl or "success" in sl or "enabled" in sl:
                        lvl = "success"
                    log_fn(s, lvl)
            proc.wait(timeout=timeout)
            return proc.returncode
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log_fn(str(e), "error")
        return 1


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═════════════════════════════════════════════════════════════════════════════


def _apply_theme():
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


class NvidiaDriverManager(tk.Tk):
    """
    Main GUI application class for NVIDIA Driver Manager.
    Handles UI setup, event logic, and driver management features.
    """
    # pylint: disable=protected-access
    def __init__(self):
        super().__init__()
        # Group UI widgets
        self.ui = {
            "clock_offset": {"mem": None, "core": None},
            "status_badge": None,
            "gpu_labels": {"name": None, "sub": None},
            "metrics_frame": None,
            "metric_labels": None,
            "drv_info_frame": None,
            "drv_labels": None,
            "monitor_badge": None,
            "mon_interval_var": None,
            "mon_metrics": None,
            "mon_labels": None,
            "mon_log": None,
            "proc_tree": None,
            "drivers_canvas": None,
            "drivers_inner": None,
            "run_canvas": None,
            "run_inner": None,
            "run_version_var": None,
            "run_file_var": None,
            "cuda_content": None,
            "power_info_frame": None,
            "power_labels": None,
            "power_limit_var": None,
            "pl_value_label": None,
            "power_scale": None,
            "fan": {"manual_var": None, "speed_var": None, "val_label": None},
            "prime": {"status_label": None, "test_label": None},
            "xorg": {
                "coolbits_var": None,
                "triple_var": None,
                "comp_pipe_var": None,
                "modeset_var": None,
                "allow_empty_var": None,
                "text": None,
            },
            "nouveau_var": None,
            "nvreg": {
                "psr_var": None,
                "preserve_var": None,
                "recovery_var": None,
                "temp_var": None,
            },
            "dkms_text": None,
            "setting_vars": None,
            "pm_var": None,
            "term_badge": None,
            "progress_var": None,
            "progress_label": None,
            "progress_bar": None,
            "terminal": None,
        }
        # Group state
        self.state = {
            "installed_driver": tk.StringVar(value="Detecting..."),
            "gpu_info": {},
            "gpu_info_extended": {},
            "available_drivers": [],
            "cuda_info": {},
            "active_tab": tk.StringVar(value="status"),
            "busy": False,
            "monitoring": False,
            "monitor_id": None,
            "settings": self._load_settings(),
            "processes": [],
        }
        self.title("NVIDIA Driver Manager — Advanced")
        self.geometry("1080x720")
        self.minsize(960, 620)
        self.configure(bg=BG_DARK)
        self.is_root = os.geteuid() == 0
        self._build_ui()
        _apply_theme()
        threading.Thread(target=self._detect_all, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_settings(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    saved = json.load(f)
                d = self._default_settings()
                d.update(saved)
                return d
        except (OSError, json.JSONDecodeError):
            pass
        return self._default_settings()

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
        self._do_preflight_and_install()

    def _do_preflight_and_install(self):
        # PHASE 1: PRE-FLIGHT CHECKS
        self._log("=" * 60, "info")
        self._log("PRE-FLIGHT DIAGNOSTICS", "info")
        self._log("=" * 60, "info")
        issues = []
        warnings = []
        fixes_applied = []
        self.after(0, lambda: self._progress_var.set(2))
        kernel_ver = self._check_privileges_and_kernel(issues)
        self.after(0, lambda: self._progress_var.set(5))
        self._check_kernel_headers(kernel_ver, issues, fixes_applied)
        self.after(0, lambda: self._progress_var.set(8))
        self._check_build_tools(kernel_ver, issues, warnings, fixes_applied)
        self.after(0, lambda: self._progress_var.set(11))
        self._check_pahole(warnings, fixes_applied)
        self.after(0, lambda: self._progress_var.set(14))
        self._check_initramfs(warnings)
        self._check_x_server()
        self.after(0, lambda: self._progress_var.set(16))
        def _do_preflight_and_install():
            issues = []
            warnings = []
            fixes_applied = []
            self._run_preflight_checks(issues, warnings, fixes_applied)
            self._report_preflight_results(issues, warnings, fixes_applied)
            if issues:
                self._handle_fatal_issues()
                return
            self._log("", "info")
            self._log("Warnings found but proceeding with installation..." if warnings else "All checks passed!", "warn" if warnings else "success")
            self._log("", "info")
            self._run_install_phase()
        # Call _do_preflight_and_install as before
        self.after(0, _do_preflight_and_install)
    # Move helper functions to class scope
    def _run_preflight_checks(self, issues, warnings, fixes_applied):
        self._log("=" * 60, "info")
        self._log("=" * 60, "info")
        self._log("PRE-FLIGHT DIAGNOSTICS", "info")
        self._log("=" * 60, "info")
        self.after(0, lambda: self._progress_var.set(2))
        kernel_ver = self._check_privileges_and_kernel(issues)
        self.after(0, lambda: self._progress_var.set(5))
        self._check_kernel_headers(kernel_ver, issues, fixes_applied)
        self.after(0, lambda: self._progress_var.set(8))
        self._check_build_tools(kernel_ver, issues, warnings, fixes_applied)
        self.after(0, lambda: self._progress_var.set(11))
        self._check_pahole(warnings, fixes_applied)
        self.after(0, lambda: self._progress_var.set(14))
        self._check_initramfs(warnings)
        self._check_x_server()
        self.after(0, lambda: self._progress_var.set(16))
        self._check_conflicting_nvidia_packages(warnings)
        self._check_disk_space(warnings)
        self.after(0, lambda: self._progress_var.set(18))
        return kernel_ver
    def _run_install_phase(self):
        self._install_nvidia_driver()
        self._restart_display_manager()
    def _check_privileges_and_kernel(self, issues):
        self._log("[1/9] Checking privileges...", "info")
        if os.geteuid() != 0:
            issues.append("Not running as root. The .run installer requires root (sudo).")
        else:
            self._log("  Root privileges: OK", "success")
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
        return kernel_ver
    def _check_kernel_headers(self, kernel_ver, issues, fixes_applied):
        self._log("[3/9] Checking kernel headers...", "info")
        headers_path = f"/lib/modules/{kernel_ver}/build"
        if os.path.isdir(headers_path):
            self._log(f"  Headers found: {headers_path}", "success")
        else:
            self._log(f"  Headers missing: {headers_path}", "error")
            self._log("  Attempting to install kernel headers...", "warn")
            rc = run_cmd_stream(["sudo", "apt", "install", "-y", f"linux-headers-{kernel_ver}"], self._log, timeout=120)
            if rc == 0 and os.path.isdir(headers_path):
                fixes_applied.append(f"Installed linux-headers-{kernel_ver}")
                self._log("  Headers installed successfully.", "success")
            else:
                issues.append(
                    f"Kernel headers not found for {kernel_ver}.\n"
                    f"         FIX: sudo apt install linux-headers-{kernel_ver}\n"
                    f"         Or:  sudo apt install linux-headers-generic"
                )
    def _check_build_tools(self, kernel_ver, issues, warnings, fixes_applied):
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
            gcc_ver_out, _, _ = run_cmd(["gcc", "--version"])
            gcc_first = gcc_ver_out.split("\n")[0] if gcc_ver_out else "unknown"
            self._log(f"  gcc: {gcc_first}", "success")
            warnings.extend(self._parse_gcc_versions(kernel_ver, gcc_first))

    def _parse_gcc_versions(self, kernel_ver, gcc_first):
        warnings = []
        proc_ver = ""
        try:
            with open(f"/lib/modules/{kernel_ver}/build/include/generated/compile.h", encoding="utf-8") as fh:
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
        return warnings
    def _check_pahole(self, warnings, fixes_applied):
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
    def _check_initramfs(self, warnings):
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
    def _check_x_server(self):
        self._log("[7/9] Checking for running X server...", "info")
        x_lock = Path("/tmp/.X0-lock")
        if x_lock.exists():
            try:
                pid = x_lock.read_text(encoding="utf-8").strip()
                self._log(f"  X server running (PID {pid}). Will stop display manager before install.", "warn")
            except OSError:
                self._log("  X server appears to be running.", "warn")
        else:
            self._log("  No X server detected: OK", "success")
    def _check_conflicting_nvidia_packages(self, warnings):
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
    def _check_disk_space(self, warnings):
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
    def _report_preflight_results(self, issues, warnings, fixes_applied):
        self._log("", "info")
        self._log("=" * 60, "info")
        self._log("PRE-FLIGHT RESULTS", "info")
        self._log("=" * 60, "info")
        if fixes_applied:
            self._log(f"Auto-fixed {len(fixes_applied)} issue(s):", "success")
            for fix in fixes_applied:
                self._log(f"  \u2713 {fix}", "success")
        if warnings:
            self._log(f"\u26a0 {len(warnings)} warning(s):", "warn")
            for w in warnings:
                for wline in w.split("\n"):
                    self._log(f"  {wline}", "warn")
        if issues:
            self._log(f"\u2717 {len(issues)} FATAL issue(s) - installation will likely fail:", "error")
            for iss in issues:
                for iline in iss.split("\n"):
                    self._log(f"  {iline}", "error")
    def _handle_fatal_issues(self):
        self._log("", "info")
        self._log("Installation ABORTED due to fatal issues above.", "error")
        self._log("Fix the issues and try again. Most common solution:", "info")
        self._log("  Boot a stable kernel: select one from GRUB at boot time.", "info")
        self._log("  List kernels: dpkg --list 'linux-image-*' | grep '^ii'", "info")
        self.after(0, lambda: self._progress_var.set(100))
        self.busy = False
        self.after(0, lambda: self._term_badge.configure(text="  BLOCKED  ", fg=RED))
    def _install_nvidia_driver(self):
        self.after(0, lambda: self._term_badge.configure(text="  INSTALLING .RUN  ", fg=ORANGE))
        self.after(0, lambda: self._progress_label.configure(text=f"Installing {os.path.basename(self.filepath)}..."))
        self._log(f"Downloading: {self.url}", "cmd")
        self._log(f"Destination: {self.dest}", "info")
        if not self._download_file(self.url, self.dest, self.callback):
            try:
                raise urllib.error.HTTPError(self.url, 404, "Not Found", None, None)
            except urllib.error.HTTPError as e:
                self._log(f"HTTP Error {e.code}: {e.reason}", "error")
                if e.code == 404:
                    alt_url = self.NVIDIA_DL_URL_ALT.format(ver=self.version)
                    self._log(f"Trying alternate URL: {alt_url}", "info")
                    self._download_file(alt_url, self.dest, self.callback)
        rc = run_cmd_stream(self.cmd, self._log, timeout=900)
        self.after(0, lambda: self._progress_var.set(90))
        if rc == 0:
            self._log("NVIDIA .run installer completed successfully.", "success")
            self._post_install_config()
            self._finish_action(True)
        else:
            self.after(0, lambda: self._progress_var.set(95))
            self._log(f"Installer exited with code {rc}.", "error")
            self._log("", "info")
            self._analyze_install_log()
            self.after(0, lambda: self._progress_var.set(100))
            self._finish_action(False)
    def _download_file(self, req_url, dest_path, callback=None):
        chunk_size = 1024 * 256
        try:
            req = urllib.request.Request(req_url, headers={"User-Agent": "NVIDIA-Driver-Manager/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                self._log(f"File size: {total / 1024 / 1024:.1f} MB" if total else "File size: unknown", "info")
                with open(str(dest_path) + ".tmp", "wb") as fp:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        fp.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(99, int(downloaded * 100 / total))
                            self.after(0, lambda p=pct: self._progress_var.set(p))
                            if downloaded % (1024 * 1024 * 10) < chunk_size:
                                self._log(f"  {downloaded / 1024 / 1024:.0f} MB / {total / 1024 / 1024:.0f} MB", "info")
                shutil.move(str(dest_path) + ".tmp", str(dest_path))
                os.chmod(str(dest_path), 0o755)
                self.after(0, lambda: self._progress_var.set(100))
                self._log(f"Download complete: {dest_path}", "success")
                self.busy = False
                if callback:
                    callback(str(dest_path))
                else:
                    self.after(0, lambda: self._term_badge.configure(text="  COMPLETE  ", fg=NVIDIA_GREEN))
                return True
        except (OSError, urllib.error.URLError) as e:
            self._log(f"Download failed: {e}", "error")
            return False
    def _post_install_config(self):
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
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
                self._log("DRM modesetting configured.", "success")
            except OSError:
                pass
        if self.settings.get("blacklist_nouveau"):
            try:
                subprocess.run(
                    [
                        "sudo",
                        "bash",
                        "-c",
                        (
                            'echo -e "blacklist nouveau\noptions nouveau modeset=0" '
                            '> /etc/modprobe.d/blacklist-nouveau.conf'
                        ),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            except OSError:
                pass
        self._log("Updating initramfs...", "info")
        run_cmd(["sudo", "update-initramfs", "-u"], timeout=120)
        self.after(0, lambda: self._progress_var.set(100))
        self._log("Driver installed. A system reboot is strongly recommended.", "warn")
        self._log("Run 'nvidia-smi' after reboot to verify.", "info")
    def _analyze_install_log(self):
        self._log("Analyzing /var/log/nvidia-installer.log for root cause...", "info")
        try:
            with open("/var/log/nvidia-installer.log", encoding="utf-8") as logf:
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
    def _restart_display_manager(self):
        self._log("Restarting display manager...", "info")
        for dm in ["gdm3", "gdm", "sddm", "lightdm"]:
            _, _, rc = run_cmd(["sudo", "systemctl", "start", dm], timeout=10)
            if rc == 0:
                self._log(f"  Started {dm}", "success")
                break
