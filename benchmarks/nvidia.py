from .base import Benchmark
import sys
sys.path.append("..")
from nvidia_manager.app import run_cmd  # noqa: E402
import time  # noqa: E402


class NvidiaBenchmark(Benchmark):
    name = "NvidiaBenchmark"
    description = "Benchmark for NVIDIA GPUs."

    def detect_devices(self):
        out, _, rc = run_cmd(["nvidia-smi", "--query-gpu=name,index", "--format=csv,noheader"])
        if rc != 0 or not out:
            return []
        devices = []
        for line in out.splitlines():
            name, idx = line.split(",")
            devices.append({"name": name.strip(), "index": idx.strip()})
        return devices

    def run(self, device=None, test_type="utilization", stress_iterations=10):
        if not device:
            return {"device": None, "result": "No device"}
        idx = device["index"]
        if test_type == "utilization":
            out, _, rc = run_cmd([
                "nvidia-smi", "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits", "-i", str(idx)
            ])
            if rc != 0 or not out:
                return {"device": device, "result": "Error"}
            return {"device": device, "gpu_utilization": out.strip()}
        elif test_type == "stress":
            utilizations = []
            for _ in range(stress_iterations):
                out, _, rc = run_cmd([
                    "nvidia-smi", "--query-gpu=utilization.gpu",
                    "--format=csv,noheader,nounits", "-i", str(idx)
                ])
                if rc == 0 and out:
                    utilizations.append(int(out.strip()))
                time.sleep(0.2)
            avg_util = sum(utilizations) / len(utilizations) if utilizations else 0
            return {"device": device, "avg_utilization": avg_util, "samples": utilizations}
        elif test_type == "memory_bandwidth":
            out, _, rc = run_cmd([
                "nvidia-smi", "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits", "-i", str(idx)
            ])
            if rc != 0 or not out:
                return {"device": device, "result": "Error"}
            used, total = out.split(",")
            return {"device": device, "memory_used": used.strip(), "memory_total": total.strip()}
        else:
            return {"device": device, "result": "Unknown test type"}

    def report(self, results):
        device = results.get("device")
        if "gpu_utilization" in results:
            util = results.get("gpu_utilization", "N/A")
            return f"NVIDIA GPU {device['name']} (index {device['index']}): Utilization {util}%"
        elif "avg_utilization" in results:
            avg = results.get("avg_utilization", "N/A")
            samples = results.get("samples", [])
            return (
                f"NVIDIA GPU {device['name']} (index {device['index']}): "
                f"Avg Utilization {avg}% over {len(samples)} samples"
            )
        elif "memory_used" in results:
            used = results.get("memory_used", "N/A")
            total = results.get("memory_total", "N/A")
            return f"NVIDIA GPU {device['name']} (index {device['index']}): Memory Used {used}MB / {total}MB"
        else:
            return f"NVIDIA GPU {device['name']} (index {device['index']}): {results.get('result', 'Unknown result')}"
