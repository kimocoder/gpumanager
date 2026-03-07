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

        self.run_btn = ttk.Button(control_frame, text='Run Benchmarks', command=self.run_benchmarks)
        self.run_btn.pack(side='left')
        ttk.Button(control_frame, text='Export JSON', command=self.export_json).pack(side='left')
        ttk.Button(control_frame, text='Config', command=self.open_config).pack(side='left')
        self.cancel_btn = ttk.Button(control_frame, text='Cancel', command=self.cancel_run)
        self.cancel_btn.pack(side='left')

        self.progress = ttk.Progressbar(control_frame, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True, padx=8)

        # Build controls
        build_frame = ttk.Frame(self)
        build_frame.pack(side='top', fill='x')
        ttk.Label(build_frame, text='Build script:').pack(side='left')
        self.build_path_var = tk.StringVar(value='benchmarks/vulkan_compute/build.sh')
        ttk.Entry(build_frame, textvariable=self.build_path_var, width=60).pack(side='left')
        ttk.Button(build_frame, text='Build Runner', command=self.build_runner).pack(side='left')
        ttk.Button(build_frame, text='Update Runner', command=self.update_runner).pack(side='left')

        # Treeview for textual results
        self.tree = ttk.Treeview(self, columns=("Benchmark", "Device", "Result"), show="headings")
        self.tree.heading("Benchmark", text="Benchmark")
        self.tree.heading("Device", text="Device")
        self.tree.heading("Result", text="Result")
        self.tree.pack(side='left', fill='both', expand=True)

        # Plot area
        if HAS_MATPLOTLIB:
            self.fig = Figure(figsize=(5, 4))
            self.ax = self.fig.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.fig, master=self)
            self.canvas.get_tk_widget().pack(side='right', fill='both', expand=True)
        else:
            self.ax = None

        # History controls
        hist_frame = ttk.Frame(self)
        hist_frame.pack(side='bottom', fill='x')
        ttk.Label(hist_frame, text='History Benchmark:').pack(side='left')
        self.history_bm_var = tk.StringVar()
        ttk.Entry(hist_frame, textvariable=self.history_bm_var).pack(side='left')
        ttk.Button(hist_frame, text='Show History', command=self.show_history).pack(side='left')

        # Logging area
        self.log_text = tk.Text(self, height=6)
        self.log_text.pack(side='bottom', fill='x')

    def log(self, msg: str):
        try:
            self.log_text.insert('end', msg + '\n')
            self.log_text.see('end')
        except Exception:
            pass

    def run_benchmarks(self):
        # Run benchmarks in a background thread pool to keep UI responsive
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.run_btn.config(state='disabled')
        self.cancel_requested = False
        self.progress['value'] = 0
        self.master.update()

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.future = self.executor.submit(self._run_all_benchmarks, self.test_type_var.get())
        self.master.after(200, self._check_future)

    def _run_all_benchmarks(self, test_type):
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
                    # apply per-benchmark iterations config if set
                    iterations = None
                    if hasattr(self, 'configs') and bm.name in self.configs:
                        iterations = self.configs[bm.name].get('iterations')
                    # If this is the VulkanBenchmark and a native runner is available, stream output
                    from benchmarks import vulkan_compute
                    if (bm.name == 'VulkanBenchmark'
                            and hasattr(vulkan_compute, 'has_runner')
                            and vulkan_compute.has_runner()):
                        # launch runner as stream
                        count = device.get('count', 1024*64)
                        local_size = device.get('local_size', 64)
                        shader = device.get('shader')
                        proc = vulkan_compute.run_runner_stream(
                            count=count, local_size=local_size,
                            shader=shader,
                            enable_validation=device.get('validation', False),
                            protocol=self.protocol_var.get()
                        )
                        res = {'device': device, 'result': 'runner started'}
                        if proc is not None:
                            # read stdout lines in a blocking fashion in this worker thread and forward to GUI
                            def reader(p):
                                try:
                                    while True:
                                        chunk = p.stdout.readline()
                                        if chunk == '':
                                            break
                                        sline = chunk.strip()
                                        if not sline:
                                            continue
                                        # handle netstring: <len>:<json>,
                                        parsed = None
                                        if ':' in sline and sline.endswith(','):
                                            # likely netstring
                                            colon = sline.find(':')
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
                                        # forward raw line to GUI log
                                        self.master.after(0, lambda ln=sline: self.log(ln))
                                        if parsed and 'progress' in parsed:
                                            prog = parsed['progress']
                                            iter_no = prog.get('iter')
                                            total_it = prog.get('total')
                                            if total_it and iter_no:
                                                pct = (iter_no / total_it) * 100
                                                self.master.after(0, lambda v=pct: self.progress.configure(value=v))
                                            self.master.after(
                                                0,
                                                lambda bmname=bm.name, dev=device,
                                                rpt=str(parsed): self.tree.insert(
                                                    '', 'end',
                                                    values=(bmname, str(dev), str(parsed))
                                                )
                                            )
                                except Exception as e:
                                    self.master.after(0, lambda err=e: self.log(f'reader error: {err}'))
                            reader(proc)
                        else:
                            self.master.after(0, lambda: self.log('Failed to launch native runner'))
                    else:
                        if iterations:
                            res = bm.run(device, test_type=test_type, stress_iterations=int(iterations))
                        else:
                            res = bm.run(device, test_type=test_type)
                except Exception as e:
                    res = {'device': device, 'result': f'error: {e}'}
                    # log exception
                    self.log(f'Error running {bm.name} on {device}: {e}')
                results.append({'benchmark': bm.name, 'device': device, **res})
                done += 1
                # update progress
                self.progress['value'] = (done / total) * 100
        # save to historical DB
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
            # populate tree
            for bmres in results:
                self.tree.insert(
                    '', 'end',
                    values=(
                        bmres.get('benchmark'),
                        str(bmres.get('device')),
                        bmres.get('result', bmres)
                    )
                )
            self.last_results = [(r.get('benchmark'), r.get('device'), r) for r in results]
            self.update_plot()
            self.run_btn.config(state='normal')
            self.progress['value'] = 0
            self.executor.shutdown(wait=False)
        else:
            self.master.after(200, self._check_future)

    def cancel_run(self):
        self.cancel_requested = True
        self.run_btn.config(state='normal')
        if hasattr(self, 'executor'):
            try:
                self.executor.shutdown(wait=False)
            except Exception:
                pass
        # if a native Vulkan runner is active, attempt to kill it
        try:
            import benchmarks.vulkan_compute as vkcomp
            if hasattr(vkcomp, 'kill_runner'):
                vkcomp.kill_runner()
        except Exception:
            pass

    def open_config(self):
        # open a simple dialog to edit per-benchmark config
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Config', 'Select a benchmark row first')
            return
        item = sel[0]
        vals = self.tree.item(item, 'values')
        bm_name = vals[0]
        # get existing or default config
        cfg = getattr(self, 'configs', {}).get(bm_name, {'iterations': 10})
        dlg = tk.Toplevel(self.master)
        dlg.title(f'Config: {bm_name}')
        ttk.Label(dlg, text='Iterations:').pack(side='left')
        it_var = tk.StringVar(value=str(cfg.get('iterations', 10)))
        ttk.Entry(dlg, textvariable=it_var).pack(side='left')

        def save():
            try:
                n = int(it_var.get())
            except Exception:
                messagebox.showerror('Config', 'Invalid integer')
                return
            if not hasattr(self, 'configs'):
                self.configs = {}
            self.configs[bm_name] = {'iterations': n}
            dlg.destroy()
        ttk.Button(dlg, text='Save', command=save).pack(side='left')

    def build_runner(self):
        script = self.build_path_var.get()
        if not script or not os.path.isfile(script):
            messagebox.showerror('Build', f'Build script not found: {script}')
            return
        # run build script in background thread and stream logs

        def run_build():
            self.master.after(0, lambda: self.log('Starting build...'))
            try:
                p = subprocess.Popen([script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in p.stdout:
                    self.master.after(0, lambda ln=line.rstrip(): self.log(ln))
                p.wait()
                self.master.after(0, lambda: self.log(f'Build finished with exit code {p.returncode}'))
            except Exception as e:
                self.master.after(0, lambda err=e: self.log(f'Build error: {err}'))
        threading.Thread(target=run_build, daemon=True).start()

    def update_runner(self):
        """Download the latest CI artifact named 'vulkan-runner' from GitHub Actions and extract runner and shader."""
        # Run in background thread
        def do_update():
            self.master.after(0, lambda: self.log('Checking for CI artifacts...'))
            # Determine repo from git origin if available
            repo = None
            try:
                import subprocess
                out = subprocess.check_output(['git', 'config', '--get', 'remote.origin.url'], text=True).strip()
                # parse git@github.com:owner/repo.git or https://github.com/owner/repo.git
                if out.startswith('git@'):
                    path = out.split(':', 1)[1]
                elif out.startswith('https://') or out.startswith('http://'):
                    path = out.split('github.com/', 1)[1]
                else:
                    path = out
                if path.endswith('.git'):
                    path = path[:-4]
                repo = path
            except Exception as e:
                self.master.after(0, lambda err=e: self.log(f'Could not determine git repo: {err}'))
            if not repo:
                self.master.after(0, lambda: self.log('Repository not detected; please set runner manually.'))
                return
            owner_repo = repo
            # GitHub API: list workflow run artifacts for latest successful run;
            # we will try to find artifact named 'vulkan-runner'
            api_url = (
                f'https://api.github.com/repos/{owner_repo}/actions/artifacts'
            )
            headers = {'Accept': 'application/vnd.github+json'}
            token = os.environ.get('GITHUB_TOKEN')
            if token:
                headers['Authorization'] = f'token {token}'
            req = urllib.request.Request(api_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read().decode('utf-8')
                    j = json.loads(data)
            except urllib.error.HTTPError as e:
                self.master.after(
                    0, lambda err=e: self.log(
                        f'Failed to query artifacts: HTTP {err.code}'))
                return
            except Exception as e:
                self.master.after(
                    0, lambda err=e: self.log(
                        f'Failed to query artifacts: {err}'))
                return
            artifacts = j.get('artifacts', [])
            target = None
            for a in artifacts:
                if a.get('name') == 'vulkan-runner':
                    target = a
                    break
            if not target:
                self.master.after(0, lambda: self.log('No vulkan-runner artifact found in CI artifacts.'))
                return
            download_url = target.get('archive_download_url')
            if not download_url:
                self.master.after(0, lambda: self.log('Artifact has no download URL.'))
                return
            # Download artifact zip
            self.master.after(0, lambda: self.log(f'Downloading artifact {target.get("name")} ...'))
            dreq = urllib.request.Request(download_url, headers=headers)
            try:
                with urllib.request.urlopen(dreq, timeout=60) as resp:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
                    tmp.write(resp.read())
                    tmp.flush()
                    tmp.close()
            except Exception as e:
                self.master.after(
                    0, lambda err=e: self.log(
                        f'Failed to download artifact: {err}'))
                return
            # Extract runner and shader
            try:
                z = zipfile.ZipFile(tmp.name)
                # find runner or shader in zip
                extracted = []
                dest_dir = os.path.join(os.getcwd(), 'benchmarks', 'vulkan_compute')
                for info in z.infolist():
                    name = os.path.basename(info.filename)
                    if name in ('runner', 'shader.spv'):
                        outpath = os.path.join(dest_dir, name)
                        with z.open(info) as src, open(outpath, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        extracted.append(outpath)
                        # make runner executable
                        if name == 'runner':
                            os.chmod(outpath, os.stat(outpath).st_mode | stat.S_IEXEC)
                z.close()
                os.unlink(tmp.name)
                if extracted:
                    for p in extracted:
                        self.master.after(0, lambda p=p: self.log(f'Extracted {p}'))
                    # update build path var to runner if runner extracted
                    runner_path = os.path.join(dest_dir, 'runner')
                    if os.path.exists(runner_path):
                        self.master.after(0, lambda: self.build_path_var.set(runner_path))
                        self.master.after(0, lambda: self.log('Runner updated from CI artifact.'))
                    else:
                        self.master.after(0, lambda: self.log('No runner file extracted.'))
                else:
                    self.master.after(0, lambda: self.log('No relevant files found in artifact.'))
            except Exception as e:
                self.master.after(
                    0, lambda err=e: self.log(
                        f'Error extracting artifact: {err}'))
                return
        threading.Thread(target=do_update, daemon=True).start()

    def update_plot(self):
        if not HAS_MATPLOTLIB or not hasattr(self, 'last_results'):
            return
        self.ax.clear()
        labels = []
        vals = []
        for name, device, res in self.last_results:
            labels.append(f"{name}: {device.get('name')}")
            # choose a numeric metric if available
            if 'gflops' in res:
                vals.append(res['gflops'])
            elif 'memory_bandwidth_MB_s' in res:
                vals.append(res['memory_bandwidth_MB_s'])
            elif 'gpu_utilization' in res:
                try:
                    vals.append(float(res['gpu_utilization']))
                except Exception:
                    vals.append(0)
            else:
                vals.append(0)
        x = range(len(labels))
        self.ax.bar(x, vals)
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(labels, rotation=45, ha='right')
        self.ax.set_ylabel('Metric')
        self.fig.tight_layout()
        self.canvas.draw()

    def show_history(self):
        bm = self.history_bm_var.get()
        if not bm:
            return
        rows = benchmarks.discovery.load_results(limit=200)
        # filter rows by benchmark
        vals = []
        ts = []
        for r in reversed(rows):
            if r.get('benchmark') == bm:
                result = r.get('result', {})
                # choose a numeric metric
                value = None
                for key in ('gflops', 'items_per_s', 'memory_bandwidth_MB_s', 'gpu_utilization'):
                    if key in result:
                        value = result[key]
                        break
                if value is not None:
                    vals.append(float(value))
                    ts.append(r.get('ts'))
        if not vals:
            # clear plot and show message
            if HAS_MATPLOTLIB and self.ax:
                self.ax.clear()
                self.ax.text(
                    0.5, 0.5,
                    'No historical numeric data for ' + bm,
                    ha='center')
                self.canvas.draw()
            return
        if HAS_MATPLOTLIB and self.ax:
            self.ax.clear()
            x = list(range(len(vals)))
            self.ax.plot(x, vals, marker='o')
            self.ax.set_title(f'History: {bm}')
            self.ax.set_xticks(x)
            self.ax.set_xticklabels(ts, rotation=45, ha='right')
            self.fig.tight_layout()
            self.canvas.draw()

    def export_json(self):
        if not hasattr(self, 'last_results'):
            return
        import json
        out = [r for _, _, r in self.last_results]
        with open('benchmarks/gui_export.json', 'w') as f:
            json.dump(out, f, indent=2)


# helper to run GUI standalone


def run_gui():
    root = tk.Tk()
    root.title('Benchmarking Suite')
    app = BenchmarkGUI(master=root)
    app.mainloop()
