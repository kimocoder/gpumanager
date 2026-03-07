"""Helpers to run the optional Vulkan compute runner.

This package provides a thin wrapper that attempts to run a prebuilt native
runner (benchmarks/vulkan_compute/runner) which must be compiled by the user
using the provided build.sh script. If the runner is not available, callers
should fall back to other methods (e.g. pyopencl-based tests).
"""
from __future__ import annotations
import os
import subprocess
from typing import Optional

HERE = os.path.dirname(__file__)
RUNNER = os.path.join(HERE, 'runner')
_proc = None


def has_runner() -> bool:
    return os.path.isfile(RUNNER) and os.access(RUNNER, os.X_OK)


def run_runner(
    count: int = 1024*64, local_size: int = 64,
    shader: Optional[str] = None, enable_validation: bool = False,
    timeout: int = 120, protocol: str = 'ndjson'
) -> tuple[bool, object]:
    """Launch the native runner as a subprocess and return (success, parsed_output_or_text).

    This function starts the runner and waits for it to complete up to `timeout` seconds.
    The global process handle is stored so it can be terminated by `kill_runner()`.
    """
    global _proc
    if not has_runner():
        return False, 'runner missing'
    args = [RUNNER, '--count', str(count), '--local-size', str(local_size), '--protocol', str(protocol)]
    if shader:
        args += ['--shader', shader]
    if enable_validation:
        args += ['--enable-validation']
    try:
        _proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = _proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # do not kill here; caller may call kill_runner()
            return False, 'timeout'
        # parse last line as JSON if possible
        out = out.strip() if out else ''
        try:
            import json
            j = json.loads(out.splitlines()[-1]) if out else {}
            return _proc.returncode == 0, j
        except Exception:
            return _proc.returncode == 0, out + ('\n' + err if err else '')
    except Exception as e:
        return False, str(e)


def health_check(timeout: int = 10) -> tuple[bool, object]:
    """Run the runner in health check mode and return (success, parsed_list_or_text)."""
    if not has_runner():
        return False, 'runner missing'
    args = [RUNNER, '--health-check']
    try:
        p = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
        out = p.stdout.strip() if p.stdout else ''
        try:
            import json
            j = json.loads(out) if out else []
            return p.returncode == 0, j
        except Exception:
            return p.returncode == 0, out + ('\n' + p.stderr if p.stderr else '')
    except Exception as e:
        return False, str(e)


def run_runner_stream(
    count: int = 1024*64, local_size: int = 64,
    shader: Optional[str] = None, enable_validation: bool = False,
    protocol: str = 'ndjson'
) -> Optional[subprocess.Popen]:
    """Launch the runner subprocess and return the Popen handle for streaming output.

    Caller may read proc.stdout/err lines. To terminate, call kill_runner().
    """
    global _proc
    if not has_runner():
        return None
    args = [RUNNER, '--count', str(count), '--local-size', str(local_size), '--protocol', str(protocol)]
    if shader:
        args += ['--shader', shader]
    if enable_validation:
        args += ['--enable-validation']
    try:
        _proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return _proc
    except Exception:
        return None


def kill_runner():
    """Terminate the running native runner if any. Returns True if a process was killed."""
    global _proc
    if _proc is None:
        return False
    try:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
        _proc = None
        return True
    except Exception:
        return False
