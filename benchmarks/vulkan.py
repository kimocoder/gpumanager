from .base import Benchmark
import subprocess
import time
import numpy as np
try:
    from .vulkan_compute import has_runner, run_runner, kill_runner
    HAS_VULKAN_RUNNER = True
except Exception:
    HAS_VULKAN_RUNNER = False

class VulkanBenchmark(Benchmark):
    name = "VulkanBenchmark"
    description = "Benchmark for Vulkan-supported devices."

    def detect_devices(self):
        devices = []
        try:
            out = subprocess.check_output(["vulkaninfo"], stderr=subprocess.STDOUT, text=True)
            # crude parsing: look for 'GPU id' or 'deviceName' lines
            for line in out.splitlines():
                if "deviceName" in line:
                    parts = line.split('=')
                    if len(parts) > 1:
                        devices.append({"name": parts[1].strip(), "type": "vulkan"})
        except Exception:
            # fallback stub
            devices.append({"name": "Vulkan Device (stub)", "type": "stub"})
        return devices

    def run(self, device=None, test_type="compute", stress_iterations=10):
        if not device:
            return {"device": None, "result": "No device"}
        if test_type == "compute":
            # Prefer native Vulkan runner if available
            if HAS_VULKAN_RUNNER and has_runner():
                # perform health check first
                try:
                    from .vulkan_compute import health_check
                    okhc, info = health_check(timeout=5)
                    if not okhc:
                        # health check failed; fallback
                        pass
                    else:
                        # we could inspect info (list of devices) and match names
                        # currently we proceed to run
                        pass
                except Exception:
                    pass
                # allow options via device dict or defaults
                count = device.get('count', 1024*64)
                local_size = device.get('local_size', 64)
                shader = device.get('shader')
                enable_validation = device.get('validation', False)
                ok, out = run_runner(
                    count=count, local_size=local_size, shader=shader,
                    enable_validation=bool(enable_validation)
                )
                if ok and isinstance(out, dict):
                    out['device'] = device
                    return out
            # fallback to pyopencl-based compute/memory test
            try:
                import pyopencl as cl
                for platform in cl.get_platforms():
                    for d in platform.get_devices():
                        if device.get("name") in d.name or device.get("type") == "stub":
                            ctx = cl.Context([d])
                            queue = cl.CommandQueue(ctx)
                            a = np.random.rand(512, 512).astype(np.float32)
                            t0 = time.perf_counter()
                            A = cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=a)
                            cl.enqueue_copy(queue, a, A)
                            queue.finish()
                            t1 = time.perf_counter()
                            return {"device": device, "compute_latency_s": t1 - t0}
                return {"device": device, "result": "No matching OpenCL device for Vulkan"}
            except Exception:
                return {"device": device, "result": "No OpenCL available; Vulkan compute stubbed"}
        elif test_type == "memory_bandwidth":
            try:
                import pyopencl as cl
                for platform in cl.get_platforms():
                    for d in platform.get_devices():
                        if device.get("name") in d.name or device.get("type") == "stub":
                            ctx = cl.Context([d])
                            queue = cl.CommandQueue(ctx)
                            a = np.random.rand(1024 * 256).astype(np.float32)
                            t0 = time.perf_counter()
                            buf = cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=a)
                            cl.enqueue_copy(queue, a, buf)
                            queue.finish()
                            t1 = time.perf_counter()
                            bw = a.nbytes / (t1 - t0) / (1024 ** 2)
                            return {"device": device, "memory_bandwidth_MB_s": bw}
                return {"device": device, "result": "No matching OpenCL device for Vulkan"}
            except Exception:
                return {"device": device, "result": "No OpenCL available; Vulkan memory stubbed"}
        elif test_type == "stress":
            # perform repeated compute test
            samples = []
            for _ in range(stress_iterations):
                r = self.run(device, test_type="compute")
                samples.append(r.get("compute_latency_s", None))
            return {"device": device, "samples": samples}
        else:
            return {"device": device, "result": "Unknown test type"}

    def report(self, results):
        device = results.get("device")
        if "compute_latency_s" in results:
            return f"Vulkan Device {device.get('name')}: Compute latency {results['compute_latency_s']:.6f}s"
        if "memory_bandwidth_MB_s" in results:
            return f"Vulkan Device {device.get('name')}: Memory Bandwidth {results['memory_bandwidth_MB_s']:.2f} MB/s"
        if "samples" in results:
            vals = [v for v in results['samples'] if v is not None]
            avg = sum(vals)/len(vals) if vals else 0
            return f"Vulkan Device {device.get('name')}: Stress average latency {avg:.6f}s over {len(vals)} runs"
        return f"Vulkan Device: {results.get('result', 'Unknown result')}"
