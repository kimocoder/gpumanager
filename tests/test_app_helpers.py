from pathlib import Path
import importlib.util
import types

# pylint: disable=no-member

# Load the workspace copy of nvidia_manager/app.py directly to avoid
# importing any globally installed package with the same name.
root = Path(__file__).resolve().parents[1]
app_path = root / "nvidia_manager" / "app.py"
spec = importlib.util.spec_from_file_location("nvidia_manager.app", str(app_path))
app = types.ModuleType(spec.name)
loader = spec.loader
assert loader is not None
loader.exec_module(app)


def test_parse_ubuntu_drivers_empty():
    """Test parsing empty ubuntu drivers output."""
    assert app.parse_ubuntu_drivers("") == []


def test_parse_ubuntu_drivers_sample():
    """Test parsing sample ubuntu drivers output."""
    sample = "nvidia-driver-515 - NVIDIA driver (recommended)"
    res = app.parse_ubuntu_drivers(sample)
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0]["package"].startswith("nvidia-driver-")
    assert res[0]["recommended"] is True


def test_parse_apt_drivers_sample():
    """Test parsing sample apt drivers output."""
    sample = "nvidia-driver-515/stable 515.76 amd64"
    res = app.parse_apt_drivers(sample)
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0]["package"] == "nvidia-driver-515"


def test_detect_driver_version_nvidia_smi_mock(monkeypatch):
    """Test detecting driver version with mocked nvidia-smi."""
    monkeypatch.setattr(app, "run_cmd", lambda *a, **k: ("515.76", "", 0))
    v = app.detect_driver_version_nvidia_smi()
    assert v == "515.76"
