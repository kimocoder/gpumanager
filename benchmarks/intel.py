from .base import Benchmark
import subprocess
import time
import numpy as np

class IntelBenchmark(Benchmark):
    name = "IntelBenchmark"
    description = "Benchmark for Intel GPUs/CPUs."

    def detect_devices(self):
        devices = []
        try:
            # Try OpenVINO detection
            try:
                from openvino.runtime import Core
                core = Core()
                for dev in core.get_available_devices():
                    devices.append({"name": dev, "type": "openvino"})
            except Exception:
                # Fallback to lspci and CPU
                out = subprocess.check_output(["lspci"]).decode()
                for line in out.splitlines():
                    if "Intel" in line and ("VGA" in line or "GPU" in line or "Graphics" in line):
                        devices.append({"name": line.strip(), "type": "lspci"})
                # Always add a CPU entry
                devices.append({"name": "Host CPU", "type": "cpu"})
        except Exception:
            return []
        return devices

    def _cpu_gflops(self, n=1024, repeats=3):
        # Measure GFLOPS of a matrix multiplication
        a = np.random.rand(n, n).astype(np.float32)
        b = np.random.rand(n, n).astype(np.float32)
        # Warmup
        np.dot(a, b)
        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            np.dot(a, b)
            t1 = time.perf_counter()
            times.append(t1 - t0)
        avg = sum(times) / len(times)
        flops = 2.0 * (n ** 3)
        gflops = (flops / avg) / 1e9
        return gflops, avg

    def run(self, device=None, test_type="info", stress_iterations=10):
        if not device:
            return {"device": None, "result": "No device"}
        dtype = device.get("type")
        if test_type == "info":
            return {"device": device, "info": device.get("name", "N/A")}
        if dtype == "cpu":
            if test_type == "compute":
                gflops, sec = self._cpu_gflops(n=512, repeats=2)
                return {"device": device, "gflops": gflops, "time_s": sec}
            elif test_type == "stress":
                gflops, sec = self._cpu_gflops(n=256, repeats=stress_iterations)
                return {"device": device, "stress_gflops": gflops, "samples": stress_iterations}
            else:
                return {"device": device, "result": "Unknown test type for CPU"}
        else:
            # For openvino or lspci GPU entries, try to perform a lightweight memory test via pyopencl if available
            try:
                import pyopencl as cl
                # find a device matching the name
                for platform in cl.get_platforms():
                    for d in platform.get_devices():
                        if device.get("name") in d.name or device.get("type") == "openvino":
                            ctx = cl.Context([d])
                            queue = cl.CommandQueue(ctx)
                            import numpy as np
                            a = np.random.rand(1024 * 256).astype(np.float32)
                            t0 = time.perf_counter()
                            buf = cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=a)
                            cl.enqueue_copy(queue, a, buf)
                            queue.finish()
                            t1 = time.perf_counter()
                            bw = a.nbytes / (t1 - t0) / (1024 ** 2)
                            return {"device": device, "memory_bandwidth_MB_s": bw}
                return {"device": device, "result": "No matching OpenCL device"}
            except Exception:
                return {"device": device, "result": "No OpenCL available, GPU tests stubbed"}

    def report(self, results):
        device = results.get("device")
        if "gflops" in results:
            return f"Intel CPU {device.get('name')}: {results['gflops']:.2f} GFLOPS (avg time {results['time_s']:.3f}s)"
        if "stress_gflops" in results:
            return f"Intel CPU {device.get('name')}: Stress {results['stress_gflops']:.2f} GFLOPS over {results.get('samples')} runs"
        if "memory_bandwidth_MB_s" in results:
            return f"Intel Device {device.get('name')}: Memory Bandwidth {results['memory_bandwidth_MB_s']:.2f} MB/s"
        return f"Intel Device: {results.get('result', 'Unknown result')}"
