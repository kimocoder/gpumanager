import os
import sys
# ensure project root is on PYTHONPATH for tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from benchmarks.discovery import discover_benchmarks, export_all_results
import importlib


def test_with_mocks(monkeypatch):
    # Mock nvidia_manager.app.run_cmd to return predictable output for nvidia-smi
    try:
        app = importlib.import_module('nvidia_manager.app')
        def fake_run_cmd(cmd, timeout=15, env=None):
            if cmd[0] == 'nvidia-smi':
                return ('GeForce Mock,0', '', 0)
            return ('', '', 127)
        monkeypatch.setattr(app, 'run_cmd', fake_run_cmd)
    except Exception:
        pass

    # Mock pyopencl.get_platforms to return no devices (so OpenCL code paths are deterministic)
    try:
        import pyopencl as cl
        class FakeDevice:
            name = 'FakeDevice'
        class FakePlatform:
            def get_devices(self):
                return [FakeDevice()]
        monkeypatch.setattr(cl, 'get_platforms', lambda: [FakePlatform()])
    except Exception:
        # pyopencl not installed in CI; skip
        pass

    # Mock Vulkan runner presence to false to avoid requiring native build
    try:
        vkmod = importlib.import_module('benchmarks.vulkan_compute')
        monkeypatch.setattr(vkmod, 'has_runner', lambda: False)
    except Exception:
        pass

def test_discover_benchmarks():
    benchmarks = discover_benchmarks()
    assert len(benchmarks) > 0

def test_export_all_results_csv():
    benchmarks = discover_benchmarks()
    csv = export_all_results(benchmarks, "csv")
    assert isinstance(csv, str)
    assert len(csv) > 0

def test_export_all_results_json():
    benchmarks = discover_benchmarks()
    json_str = export_all_results(benchmarks, "json")
    assert isinstance(json_str, str)
    assert json_str.startswith("[")
