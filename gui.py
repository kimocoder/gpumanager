from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import benchmarks.discovery
import os
import subprocess
import threading
import concurrent.futures
import json
import urllib.request
import urllib.error
import zipfile
import tempfile
import stat
import shutil

# Matplotlib integration
try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False

class BenchmarkGUI(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack(fill='both', expand=True)
        self.create_widgets()

    def create_widgets(self):
        control_frame = ttk.Frame(self)
        control_frame.pack(side='top', fill='x')

        ttk.Label(control_frame, text="Test Type:").pack(side='left')
        self.test_type_var = tk.StringVar(value='compute')
        ttk.Combobox(
            control_frame, textvariable=self.test_type_var,
            values=['compute', 'stress', 'memory_bandwidth']
        ).pack(side='left')

        ttk.Label(control_frame, text="Protocol:").pack(side='left')
        self.protocol_var = tk.StringVar(value='ndjson')
        ttk.Combobox(
            control_frame, textvariable=self.protocol_var,
            values=['ndjson', 'netstring'], width=10
        ).pack(side='left')

        ttk.Label(control_frame, text="Iterations:").pack(side='left')
        self.iterations_var = tk.StringVar(value='10')
        ttk.Entry(
            control_frame, textvariable=self.iterations_var, width=6
        ).pack(side='left')

        ttk.Label(control_frame, text="Launcher:").pack(side='left')
        self.launcher_var = tk.StringVar(value='native')
        ttk.Combobox(
            control_frame, textvariable=self.launcher_var,
            values=['native', 'mangohud', 'goverlay'], width=12
        ).pack(side='left')

        self.run_btn = ttk.Button(control_frame, text='Run Benchmarks', command=self.run_benchmarks)
        self.run_btn.pack(side='left')
        self.cancel_btn = ttk.Button(control_frame, text='Cancel', command=self.cancel_run)
        self.cancel_btn.pack(side='left')
        self.clear_btn = ttk.Button(control_frame, text='Clear', command=self.clear_results)
        self.clear_btn.pack(side='left')
        self.export_csv_btn = ttk.Button(control_frame, text='Export CSV', command=self.export_csv)
        self.export_csv_btn.pack(side='left')
        self.export_json_btn = ttk.Button(control_frame, text='Export JSON', command=self.export_json)
        self.export_json_btn.pack(side='left')

        self.progress = ttk.Progressbar(control_frame, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True, padx=8)

        self.tree = ttk.Treeview(self, columns=("Benchmark", "Device", "Result"), show="headings")
        self.tree.heading("Benchmark", text="Benchmark")
        self.tree.heading("Device", text="Device")
        self.tree.heading("Result", text="Result")
        self.tree.pack(side='left', fill='both', expand=True)

        self.log_text = tk.Text(self, height=8)
        self.log_text.pack(side='bottom', fill='x')
        # Shortcuts
        try:
            self.master.bind('<Control-r>', lambda e: self.run_btn.invoke())
            self.master.bind('<Control-c>', lambda e: self.cancel_btn.invoke())
            self.master.bind('<Control-e>', lambda e: self.export_csv)
        except Exception:
            pass

    def log(self, msg: str):
        try:
            self.log_text.insert('end', msg + '\n')
            self.log_text.see('end')
        except Exception:
            pass

    def run_benchmarks(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.run_btn.config(state='disabled')
        self.cancel_btn.config(state='normal')
        self.clear_btn.config(state='disabled')
        self.export_csv_btn.config(state='disabled')
        self.export_json_btn.config(state='disabled')
        self.cancel_requested = False
        self.progress['value'] = 0
        self.master.update()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.future = self.executor.submit(self._run_all_benchmarks)
        self.master.after(200, self._check_future)

    def _run_all_benchmarks(self):
        benches = benchmarks.discovery.discover_benchmarks()
        results = []
        total = sum(len(bm.detect_devices()) for bm in benches)
        if total == 0:
            total = 1
        done = 0
        for bm in benches:
            if self.cancel_requested:
                break
            devices = bm.detect_devices()
            for device in devices:
                if self.cancel_requested:
                    break
                try:
                    iterations = int(self.iterations_var.get())
                    test_type = self.test_type_var.get()
                    protocol = self.protocol_var.get()
                    from benchmarks import vulkan_compute
                    if (
                        bm.name == 'VulkanBenchmark' and
                        hasattr(vulkan_compute, 'has_runner') and
                        vulkan_compute.has_runner()
                    ):
                        count = device.get('count', 1024*64)
                        local_size = device.get('local_size', 64)
                        shader = device.get('shader')
                        launcher = (
                            self.launcher_var.get()
                            if hasattr(self, 'launcher_var') else None
                        )
                        try:
                            proc = vulkan_compute.run_runner_stream(
                                count=count, local_size=local_size, shader=shader,
                                enable_validation=device.get('validation', False),
                                protocol=protocol, launcher=launcher
                            )
                        except TypeError:
                            proc = vulkan_compute.run_runner_stream(
                                count=count, local_size=local_size, shader=shader,
                                enable_validation=device.get('validation', False),
                                protocol=protocol
                            )
                        if proc is not None:
                            def reader(p):
                                try:
                                    while not self.cancel_requested:
                                        chunk = p.stdout.readline()
                                        if chunk == '':
                                            break
                                        sline = chunk.strip()
                                        if not sline:
                                            continue
                                        parsed = None
                                        if ':' in sline and sline.endswith(','):
                                            colon = sline.find(':')
                                            lenpart = sline[:colon]
                                            jsonpart = sline[colon+1:-1]
                                            try:
                                                import json as _json
                                                parsed = _json.loads(jsonpart)
                                            except Exception:
                                                parsed = None
                                        else:
                                            try:
                                                import json as _json
                                                parsed = _json.loads(sline)
                                            except Exception:
                                                parsed = None
                                        self.master.after(0, lambda l=sline: self.log(l))
                                        if parsed and 'progress' in parsed:
                                            prog = parsed['progress']
                                            iter_no = prog.get('iter')
                                            total_it = prog.get('total')
                                            if total_it and iter_no:
                                                pct = (iter_no / total_it) * 100
                                                self.master.after(
                                                    0,
                                                    lambda v=pct: self.progress.configure(value=v)
                                                )
                                            self.master.after(
                                                0,
                                                lambda bmname=bm.name, dev=device, rpt=str(parsed):
                                                self.tree.insert(
                                                    '', 'end',
                                                    values=(bmname, str(dev), str(parsed))
                                                )
                                            )
                                except Exception as e:
                                    self.master.after(0, lambda: self.log(f'reader error: {e}'))
                            reader(proc)
                        else:
                            self.master.after(0, lambda: self.log('Failed to launch native runner'))
                    else:
                        res = bm.run(device, test_type=test_type, stress_iterations=iterations)
                        self.master.after(
                            0,
                            lambda bmname=bm.name, dev=device, rpt=str(res):
                            self.tree.insert('', 'end', values=(bmname, str(dev), str(res)))
                        )
                except Exception as e:
                    self.master.after(0, lambda: self.log(f'Error running {bm.name} on {device}: {e}'))
                done += 1
                self.progress['value'] = (done / total) * 100
        try:
            benchmarks.discovery.save_results(results)
        except Exception:
            pass
        return results

    def _check_future(self):
        if self.future.done():
            try:
                results = self.future.result()
            except Exception as e:
                results = []
                self.log(f'Benchmark thread error: {e}')
            self.run_btn.config(state='normal')
            self.cancel_btn.config(state='disabled')
            self.clear_btn.config(state='normal')
            self.export_csv_btn.config(state='normal')
            self.export_json_btn.config(state='normal')
            self.progress['value'] = 0
            self.executor.shutdown(wait=False)
        else:
            self.master.after(200, self._check_future)

    def cancel_run(self):
        self.cancel_requested = True
        self.run_btn.config(state='normal')
        self.cancel_btn.config(state='disabled')
        self.clear_btn.config(state='normal')
        self.export_csv_btn.config(state='normal')
        self.export_json_btn.config(state='normal')
        try:
            import benchmarks.vulkan_compute as vkcomp
            if hasattr(vkcomp, 'kill_runner'):
                vkcomp.kill_runner()
        except Exception:
            pass
        try:
            self.progress['value'] = 0
        except Exception:
            pass

    def clear_results(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.log_text.delete('1.0', 'end')
        self.progress['value'] = 0

    def export_csv(self):
        import csv
        from tkinter import filedialog
        rows = [self.tree.item(i, 'values') for i in self.tree.get_children()]
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile=f"benchmarks_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not path:
            return
        with open(path, 'w', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(["Benchmark", "Device", "Result"])
            for r in rows:
                w.writerow(r)
        self.log(f'Exported CSV to {path}')

    def export_json(self):
        import json
        from tkinter import filedialog
        rows = [self.tree.item(i, 'values') for i in self.tree.get_children()]
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")],
            initialfile=f"benchmarks_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        if not path:
            return
        out = [{'benchmark': r[0], 'device': r[1], 'result': r[2]} for r in rows]
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2)
        self.log(f'Exported JSON to {path}')

    def export_log(self):
        from tkinter import filedialog
        try:
            path = filedialog.asksaveasfilename(defaultextension=".log", filetypes=[("Log files", "*.log")], initialfile=f"benchmarks_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            if not path:
                return
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(self.log_text.get('1.0', 'end'))
            self.log(f'Exported log to {path}')
        except Exception as e:
            self.log(f'Log export failed: {e}')

# helper to run GUI standalone
def run_gui():
    root = tk.Tk()
    root.title('Benchmarking Suite')
    app = BenchmarkGUI(master=root)
    app.mainloop()
