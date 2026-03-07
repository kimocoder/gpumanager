from abc import ABC, abstractmethod
import json
import csv
from io import StringIO


class Benchmark(ABC):
    """Abstract base class for all benchmarks."""
    name = "GenericBenchmark"
    description = "Generic benchmark interface."

    @abstractmethod
    def detect_devices(self):
        """Detect supported devices for this benchmark."""
        pass

    @abstractmethod
    def run(self, device=None):
        """Run the benchmark on the specified device."""
        pass

    @abstractmethod
    def report(self, results):
        """Format and return benchmark results."""
        pass

    def export_csv(self, results):
        output = StringIO()
        writer = csv.writer(output)
        if isinstance(results, list):
            for res in results:
                writer.writerow([res.get(k, "") for k in sorted(res.keys())])
        else:
            writer.writerow([results.get(k, "") for k in sorted(results.keys())])
        return output.getvalue()

    def export_json(self, results):
        return json.dumps(results, indent=2)
