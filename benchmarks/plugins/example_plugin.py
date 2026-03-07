from benchmarks.base import Benchmark


class ExamplePluginBenchmark(Benchmark):
    name = "ExamplePluginBenchmark"
    description = "Example plugin benchmark."

    def detect_devices(self):
        return [{"name": "Plugin Device", "type": "plugin"}]

    def run(self, device=None, test_type="plugin", stress_iterations=10):
        return {"device": device, "result": "plugin stub"}

    def report(self, results):
        device = results.get("device")
        return f"Plugin Device: {device['name']} (plugin stub)"
