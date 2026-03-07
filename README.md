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


License: MIT

