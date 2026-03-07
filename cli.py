import benchmarks.discovery

def run_benchmarks(export_format=None, test_type=None, iterations=None):
    benchmark_instances = benchmarks.discovery.discover_benchmarks()
    for bm in benchmark_instances:
        devices = bm.detect_devices()
        for device in devices:
            # pass through test_type and iterations when supported
            try:
                if test_type and iterations:
                    results = bm.run(device, test_type=test_type, stress_iterations=int(iterations))
                elif test_type:
                    results = bm.run(device, test_type=test_type)
                else:
                    results = bm.run(device)
            except TypeError:
                # some older stubs may not accept params
                results = bm.run(device)
            print(f"Benchmark: {bm.name}, Device: {device}")
            print(bm.report(results))
    if export_format:
        exported = benchmarks.discovery.export_all_results(benchmark_instances, export_format)
        print(f"\nExported results ({export_format}):\n{exported}")

# Add CLI entry point for benchmarking
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "benchmark":
        export_format = None
        test_type = None
        iterations = None
        if len(sys.argv) > 2:
            # allow: benchmark [format] [test_type] [iterations]
            arg2 = sys.argv[2].lower()
            if arg2 in ("csv", "json"):
                export_format = arg2
                if len(sys.argv) > 3:
                    test_type = sys.argv[3]
                if len(sys.argv) > 4:
                    iterations = sys.argv[4]
            else:
                test_type = arg2
                if len(sys.argv) > 3:
                    iterations = sys.argv[3]
        run_benchmarks(export_format, test_type, iterations)
    elif len(sys.argv) > 1 and sys.argv[1] == "run":
        # run a single benchmark specified as module:Class
        # usage: python3 cli.py run benchmarks.nvidia:NvidiaBenchmark [test_type] [iterations]
        if len(sys.argv) < 3:
            print("Usage: cli.py run module:Class [test_type] [iterations]")
            sys.exit(2)
        target = sys.argv[2]
        try:
            modname, classname = target.split(":", 1)
            mod = __import__(modname, fromlist=[classname])
            cls = getattr(mod, classname)
            inst = cls()
        except Exception as e:
            print(f"Failed to load benchmark {target}: {e}")
            sys.exit(1)
        test_type = sys.argv[3] if len(sys.argv) > 3 else None
        iterations = int(sys.argv[4]) if len(sys.argv) > 4 else None
        devices = inst.detect_devices()
        for device in devices:
            try:
                if test_type and iterations:
                    res = inst.run(device, test_type=test_type, stress_iterations=iterations)
                elif test_type:
                    res = inst.run(device, test_type=test_type)
                else:
                    res = inst.run(device)
            except TypeError:
                res = inst.run(device)
            print(inst.report(res))
    else:
        # ...existing code...
        pass
