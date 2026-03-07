NVIDIA Driver Manager
==========================

A GUI tool for managing NVIDIA drivers, monitoring GPUs, and installing NVIDIA .run installers on Debian/Ubuntu based systems.
Copyright 2026 - Christian 'kimocoder' B.
christian@aircrack-ng.org


Pre-requisites
- Python 3.9+
- tkinter

Setup pre-requisites

```bash
sudo apt update
sudo apt install python3 python3-venv python3-dev python3-tk
```

Install (development):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run

```bash
nvidia-manager
```


## Benchmarking Suite

- Supports NVIDIA, OpenCL, Intel, Vulkan (stub), and plugin benchmarks
- Run benchmarks via CLI: `python3 cli.py benchmark [csv|json]`
- View results in GUI (Treeview widget)
- Extensible via plugins in `benchmarks/plugins/`
- Historical result comparison and persistent storage
- Automated test coverage in `tests/`

## Cross-Platform Dependency Checks

- Linux: Requires `nvidia-smi`, `pyopencl`, `openvino`, `lspci`, `tkinter`
- Windows: Requires `pyopencl`, `openvino`, `tkinter` (NVIDIA tools may differ)
- macOS: Requires `pyopencl`, `openvino`, `tkinter` (GPU support limited)

Install dependencies:

```bash
pip install pyopencl openvino
```

If running tests, set PYTHONPATH:

```bash
export PYTHONPATH=.
pytest tests/
```


License: MIT
