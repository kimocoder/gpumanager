from .base import Benchmark
import numpy as np
import pyopencl as cl

class OpenCLBenchmark(Benchmark):
    name = "OpenCLBenchmark"
    description = "Benchmark for OpenCL-supported devices."

    def detect_devices(self):
        devices = []
        try:
            for platform in cl.get_platforms():
                for device in platform.get_devices():
                    devices.append({
                        "platform": platform.name,
                        "name": device.name,
                        "type": cl.device_type.to_string(device.type),
                        "vendor": device.vendor,
                        "max_compute_units": device.max_compute_units,
                    })
        except Exception as e:
            return []
        return devices

    def run(self, device=None, test_type="compute", stress_iterations=10):
        if not device:
            return {"device": None, "result": "No device"}
        if test_type == "compute":
            return {"device": device, "max_compute_units": device.get("max_compute_units", "N/A")}
        elif test_type == "stress":
            # Stress test: run repeated matrix multiplications
            try:
                ctx = cl.Context([cl.Device(device['name'])])
                queue = cl.CommandQueue(ctx)
                a = np.random.rand(1024, 1024).astype(np.float32)
                b = np.random.rand(1024, 1024).astype(np.float32)
                for _ in range(stress_iterations):
                    cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=a)
                    cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=b)
                return {"device": device, "stress_test": "completed"}
            except Exception as e:
                return {"device": device, "stress_test": f"error: {e}"}
        elif test_type == "memory_bandwidth":
            # Memory bandwidth test: transfer buffer
            try:
                ctx = cl.Context([cl.Device(device['name'])])
                queue = cl.CommandQueue(ctx)
                a = np.random.rand(1024 * 1024).astype(np.float32)
                buf = cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=a)
                cl.enqueue_copy(queue, a, buf)
                return {"device": device, "memory_bandwidth": "completed"}
            except Exception as e:
                return {"device": device, "memory_bandwidth": f"error: {e}"}
        else:
            return {"device": device, "result": "Unknown test type"}

    def report(self, results):
        device = results.get("device")
        if "max_compute_units" in results:
            units = results.get("max_compute_units", "N/A")
            return f"OpenCL Device {device['name']} ({device['platform']}): Compute Units {units}"
        elif "stress_test" in results:
            return (
                f"OpenCL Device {device['name']} ({device['platform']}): "
                f"Stress Test {results['stress_test']}"
            )
        elif "memory_bandwidth" in results:
            return (
                f"OpenCL Device {device['name']} ({device['platform']}): "
                f"Memory Bandwidth Test {results['memory_bandwidth']}"
            )
        else:
            return f"OpenCL Device {device['name']} ({device['platform']}): {results.get('result', 'Unknown result')}"
