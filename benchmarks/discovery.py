import importlib
import os
import importlib.util
import json
import sqlite3
from datetime import datetime

from .base import Benchmark

BENCHMARK_MODULES = [
    'vulkan',
    'opencl',
    'nvidia',
    'intel',
]

HISTORICAL_DB = "benchmarks/historical_results.sqlite3"


def load_plugins(plugin_dir="benchmarks/plugins"):
    plugins = []
    if not os.path.isdir(plugin_dir):
        return plugins
    for fname in os.listdir(plugin_dir):
        if fname.endswith(".py"):
            spec = importlib.util.spec_from_file_location(fname[:-3], os.path.join(plugin_dir, fname))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and issubclass(obj, Benchmark) and obj is not Benchmark:
                    plugins.append(obj())
    return plugins


def discover_benchmarks():
    benchmarks = []
    for module_name in BENCHMARK_MODULES:
        module = importlib.import_module(f'.{module_name}', 'benchmarks')
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, Benchmark) and obj is not Benchmark:
                benchmarks.append(obj())
    benchmarks += load_plugins()
    return benchmarks


def export_all_results(benchmarks, export_format="csv"):
    all_results = []
    for bm in benchmarks:
        devices = bm.detect_devices()
        for device in devices:
            result = bm.run(device)
            all_results.append(result)
    if export_format == "csv":
        return benchmarks[0].export_csv(all_results) if benchmarks else ""
    elif export_format == "json":
        return benchmarks[0].export_json(all_results) if benchmarks else ""
    else:
        return "Unsupported format"


def _ensure_db():
    conn = sqlite3.connect(HISTORICAL_DB)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            benchmark TEXT NOT NULL,
            device TEXT NOT NULL,
            result_json TEXT NOT NULL
        )
    ''')
    conn.commit()
    return conn


def save_results(results):
    try:
        conn = _ensure_db()
        cur = conn.cursor()
        ts = datetime.utcnow().isoformat() + 'Z'
        for r in results:
            # r expected to be a dict with device and benchmark info
            bench = r.get('benchmark', 'unknown')
            device = json.dumps(r.get('device', {}))
            result = json.dumps(r)
            cur.execute(
                'INSERT INTO runs (ts, benchmark, device, result_json) VALUES (?,?,?,?)',
                (ts, bench, device, result)
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_results(limit=100):
    try:
        conn = _ensure_db()
        cur = conn.cursor()
        cur.execute('SELECT ts, benchmark, device, result_json FROM runs ORDER BY id DESC LIMIT ?', (limit,))
        rows = cur.fetchall()
        conn.close()
        return [{'ts': r[0], 'benchmark': r[1], 'device': json.loads(r[2]), 'result': json.loads(r[3])} for r in rows]
    except Exception:
        return []


def compare_results(new_results, limit=100):
    old = load_results(limit)
    comparison = {'new': new_results, 'historical': old}
    return comparison
