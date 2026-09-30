import math
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


MODE_OPTIONS = [
    ("0 - Combo", 0),
    ("1 - Triangle", 1),
    ("2 - Rectangle", 2),
    ("3 - Ellipse", 3),
    ("4 - Circle", 4),
    ("5 - Rotated Rectangle", 5),
    ("6 - Beziers", 6),
    ("7 - Rotated Ellipse", 7),
    ("8 - Polygon", 8),
]

STEP_LINE_RE = re.compile(r"^(\d+):\s+t=([0-9.]+),\s+score=([0-9.]+),")
WRITE_LINE_RE = re.compile(r"^writing\s+(.+)$")


class PrimitiveDesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Primitive Desktop")
        self.root.geometry("1120x760")

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.runner_path = tk.StringVar()
        self.shape_count = tk.IntVar(value=120)
        self.mode_text = tk.StringVar(value=MODE_OPTIONS[1][0])
        self.alpha = tk.IntVar(value=128)
        self.repeat = tk.IntVar(value=0)
        self.input_size = tk.IntVar(value=256)
        self.output_size = tk.IntVar(value=1024)
        self.workers = tk.IntVar(value=0)
        self.nth = tk.IntVar(value=1)

        self.status_text = tk.StringVar(value="Ready")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.frame_text = tk.StringVar(value="Frame: 0 / 0")
        self.score_text = tk.StringVar(value="Score: -")

        self.command_queue: queue.Queue = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.worker_thread: threading.Thread | None = None
        self.running = False
        self.total_frames = 0
        self.preview_image = None
        self.preview_source_path: Path | None = None
        self.tempdir_obj: tempfile.TemporaryDirectory | None = None
        self.preview_pattern = ""

        self._build_ui()
        self.root.after(100, self._drain_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        config_frame = ttk.LabelFrame(main, text="User Choices", padding=10)
        config_frame.pack(fill=tk.X)

        self._row_file_input(config_frame)
        self._row_runner(config_frame)
        self._row_file_output(config_frame)
        self._row_algorithm(config_frame)
        self._row_sizes(config_frame)
        self._row_runtime(config_frame)

        action_row = ttk.Frame(config_frame)
        action_row.grid(row=6, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        action_row.columnconfigure(0, weight=1)
        self.start_btn = ttk.Button(action_row, text="Start", command=self.start)
        self.start_btn.grid(row=0, column=1, padx=4)
        self.cancel_btn = ttk.Button(action_row, text="Cancel", command=self.cancel, state=tk.DISABLED)
        self.cancel_btn.grid(row=0, column=2, padx=4)

        status_frame = ttk.LabelFrame(main, text="Progress", padding=10)
        status_frame.pack(fill=tk.X, pady=(10, 0))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status_text).grid(row=0, column=0, sticky="w")
        ttk.Progressbar(status_frame, variable=self.progress_value, maximum=100).grid(
            row=1, column=0, sticky="ew", pady=(6, 6)
        )
        ttk.Label(status_frame, textvariable=self.frame_text).grid(row=2, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.score_text).grid(row=3, column=0, sticky="w")

        content = ttk.Frame(main)
        content.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)

        logs_frame = ttk.LabelFrame(content, text="Live Logs", padding=8)
        logs_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(logs_frame, wrap="word", height=20)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(logs_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set, state=tk.DISABLED)

        preview_frame = ttk.LabelFrame(content, text="Live Preview", padding=8)
        preview_frame.grid(row=0, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview_label = ttk.Label(preview_frame, text="Preview appears while running", anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        self.preview_label.bind("<Configure>", self._on_preview_resize)

    def _row_file_input(self, parent: ttk.LabelFrame) -> None:
        ttk.Label(parent, text="Input image").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=self.input_path)
        entry.grid(row=0, column=1, columnspan=4, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse", command=self.browse_input).grid(row=0, column=5, sticky="ew", pady=4)
        for i in range(1, 5):
            parent.columnconfigure(i, weight=1)

    def _row_file_output(self, parent: ttk.LabelFrame) -> None:
        ttk.Label(parent, text="Save final output").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=self.output_path)
        entry.grid(row=2, column=1, columnspan=4, sticky="ew", pady=4)
        ttk.Button(parent, text="Choose", command=self.browse_output).grid(row=2, column=5, sticky="ew", pady=4)

    def _row_runner(self, parent: ttk.LabelFrame) -> None:
        ttk.Label(parent, text="Primitive executable (optional)").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        entry = ttk.Entry(parent, textvariable=self.runner_path)
        entry.grid(row=1, column=1, columnspan=4, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse", command=self.browse_runner).grid(row=1, column=5, sticky="ew", pady=4)

    def _row_algorithm(self, parent: ttk.LabelFrame) -> None:
        ttk.Label(parent, text="Shapes").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Spinbox(parent, from_=1, to=5000, textvariable=self.shape_count, width=8).grid(
            row=3, column=1, sticky="w", pady=4
        )
        ttk.Label(parent, text="Mode").grid(row=3, column=2, sticky="e", padx=(12, 8), pady=4)
        mode_box = ttk.Combobox(parent, textvariable=self.mode_text, values=[name for name, _ in MODE_OPTIONS], state="readonly")
        mode_box.grid(row=3, column=3, sticky="ew", pady=4)
        ttk.Label(parent, text="Alpha").grid(row=3, column=4, sticky="e", padx=(12, 8), pady=4)
        ttk.Spinbox(parent, from_=0, to=255, textvariable=self.alpha, width=8).grid(row=3, column=5, sticky="w", pady=4)

    def _row_sizes(self, parent: ttk.LabelFrame) -> None:
        ttk.Label(parent, text="Resize input (r)").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Spinbox(parent, from_=0, to=4096, textvariable=self.input_size, width=8).grid(
            row=4, column=1, sticky="w", pady=4
        )
        ttk.Label(parent, text="Output size (s)").grid(row=4, column=2, sticky="e", padx=(12, 8), pady=4)
        ttk.Spinbox(parent, from_=64, to=8192, textvariable=self.output_size, width=8).grid(
            row=4, column=3, sticky="w", pady=4
        )
        ttk.Label(parent, text="Repeat (rep)").grid(row=4, column=4, sticky="e", padx=(12, 8), pady=4)
        ttk.Spinbox(parent, from_=0, to=100, textvariable=self.repeat, width=8).grid(row=4, column=5, sticky="w", pady=4)

    def _row_runtime(self, parent: ttk.LabelFrame) -> None:
        ttk.Label(parent, text="Workers (j)").grid(row=5, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Spinbox(parent, from_=0, to=256, textvariable=self.workers, width=8).grid(row=5, column=1, sticky="w", pady=4)
        ttk.Label(parent, text="Preview interval (nth)").grid(row=5, column=2, sticky="e", padx=(12, 8), pady=4)
        ttk.Spinbox(parent, from_=1, to=1000, textvariable=self.nth, width=8).grid(row=5, column=3, sticky="w", pady=4)

    def browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose input image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All files", "*.*")],
        )
        if path:
            self.input_path.set(path)

    def browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Choose where to save final image",
            defaultextension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("JPEG image", "*.jpg *.jpeg"),
                ("SVG file", "*.svg"),
                ("GIF animation", "*.gif"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.output_path.set(path)

    def browse_runner(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose primitive executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.runner_path.set(path)

    def _selected_mode(self) -> int:
        for name, mode in MODE_OPTIONS:
            if name == self.mode_text.get():
                return mode
        return 1

    def _resolve_command_base(self) -> list[str]:
        user_runner = self.runner_path.get().strip()
        if user_runner:
            p = Path(user_runner)
            if p.exists() and p.is_file():
                return [str(p)]

        primitive_bin = os.environ.get("PRIMITIVE_BIN")
        if primitive_bin:
            p = Path(primitive_bin)
            if p.exists() and p.is_file():
                return [str(p)]
            env_hit = shutil.which(primitive_bin)
            if env_hit:
                return [env_hit]

        in_path = shutil.which("primitive")
        if in_path:
            return [in_path]

        # Common local build locations when running from this repository.
        repo_dir = Path(__file__).resolve().parent
        for candidate in [repo_dir / "primitive.exe", repo_dir / "primitive"]:
            if candidate.exists() and candidate.is_file():
                return [str(candidate)]

        go_bin = shutil.which("go")
        if not go_bin:
            go_bin = shutil.which("go.exe")
        if not go_bin:
            goroot = os.environ.get("GOROOT")
            if goroot:
                candidate = Path(goroot) / "bin" / "go.exe"
                if candidate.exists() and candidate.is_file():
                    go_bin = str(candidate)
        if not go_bin:
            candidate = Path("C:/Program Files/Go/bin/go.exe")
            if candidate.exists() and candidate.is_file():
                go_bin = str(candidate)
        if not go_bin:
            candidate = Path("C:/Program Files (x86)/Go/bin/go.exe")
            if candidate.exists() and candidate.is_file():
                go_bin = str(candidate)

        if go_bin:
            return [go_bin, "run", "."]

        raise RuntimeError(
            "Could not find primitive runner. Choose primitive.exe in the app, build primitive.exe in this folder, "
            "or install Go (default path C:/Program Files/Go is auto-detected)."
        )

    def _validate(self) -> bool:
        in_file = self.input_path.get().strip()
        if not in_file:
            messagebox.showerror("Missing input", "Choose an input image first.")
            return False
        if not Path(in_file).exists():
            messagebox.showerror("Invalid input", "The selected input file does not exist.")
            return False

        out_file = self.output_path.get().strip()
        if out_file:
            ext = Path(out_file).suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".svg", ".gif"}:
                messagebox.showerror("Invalid output", "Output must end in .png, .jpg, .jpeg, .svg, or .gif")
                return False
        return True

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def start(self) -> None:
        if self.running:
            return
        if not self._validate():
            return

        self.tempdir_obj = tempfile.TemporaryDirectory(prefix="primitive_gui_")
        self.preview_pattern = str(Path(self.tempdir_obj.name) / "frame_%06d.png")

        try:
            command = self._build_command()
        except Exception as exc:
            self.status_text.set("Not ready")
            messagebox.showerror("Cannot start", str(exc))
            self._append_log(f"Start blocked: {exc}")
            if self.tempdir_obj is not None:
                self.tempdir_obj.cleanup()
                self.tempdir_obj = None
            return

        self.running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.progress_value.set(0.0)
        self.score_text.set("Score: -")
        self.total_frames = max(1, int(self.shape_count.get()))
        self.frame_text.set(f"Frame: 0 / {self.total_frames}")
        self.status_text.set("Starting...")
        self.preview_label.configure(text="Preparing preview...", image="")
        self.preview_image = None
        self.preview_source_path = None

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

        self._append_log("$ " + " ".join(command))

        self.worker_thread = threading.Thread(target=self._run_process, args=(command,), daemon=True)
        self.worker_thread.start()

    def _build_command(self) -> list[str]:
        base = self._resolve_command_base()
        cmd = [
            *base,
            "-i",
            self.input_path.get().strip(),
            "-o",
            self.preview_pattern,
            "-n",
            str(int(self.shape_count.get())),
            "-m",
            str(self._selected_mode()),
            "-a",
            str(int(self.alpha.get())),
            "-rep",
            str(int(self.repeat.get())),
            "-r",
            str(int(self.input_size.get())),
            "-s",
            str(int(self.output_size.get())),
            "-j",
            str(int(self.workers.get())),
            "-nth",
            str(int(self.nth.get())),
            "-v",
        ]

        out_file = self.output_path.get().strip()
        if out_file:
            cmd.extend(["-o", out_file])
        return cmd

    def _run_process(self, command: list[str]) -> None:
        cwd = str(Path(__file__).resolve().parent)
        try:
            self.process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self.command_queue.put(("error", f"Failed to start process: {exc}"))
            self.command_queue.put(("done", 1))
            return

        assert self.process.stdout is not None
        for raw in self.process.stdout:
            line = raw.rstrip("\n")
            self.command_queue.put(("log", line))

            step_match = STEP_LINE_RE.match(line)
            if step_match:
                frame = int(step_match.group(1))
                score = step_match.group(3)
                self.command_queue.put(("step", frame, score))

            write_match = WRITE_LINE_RE.match(line)
            if write_match:
                self.command_queue.put(("preview", write_match.group(1).strip()))

        code = self.process.wait()
        self.command_queue.put(("done", code))

    def _drain_queue(self) -> None:
        try:
            while True:
                event = self.command_queue.get_nowait()
                kind = event[0]

                if kind == "log":
                    self._append_log(event[1])
                elif kind == "step":
                    frame = event[1]
                    score = event[2]
                    pct = min(100.0, (frame / self.total_frames) * 100.0)
                    self.progress_value.set(pct)
                    self.frame_text.set(f"Frame: {frame} / {self.total_frames}")
                    self.score_text.set(f"Score: {score}")
                    self.status_text.set("Running")
                elif kind == "preview":
                    self._set_preview(event[1])
                elif kind == "error":
                    self.status_text.set("Error")
                    self._append_log(event[1])
                elif kind == "done":
                    self._finish_run(event[1])
        except queue.Empty:
            pass

        self.root.after(100, self._drain_queue)

    def _set_preview(self, image_path: str) -> None:
        p = Path(image_path)
        if not p.exists() or p.suffix.lower() != ".png":
            return
        self.preview_source_path = p
        self._render_preview_to_label()

    def _on_preview_resize(self, _event: tk.Event) -> None:
        # Re-render from original source so preview follows window resizing.
        if self.preview_source_path is not None:
            self._render_preview_to_label()

    def _render_preview_to_label(self) -> None:
        if self.preview_source_path is None:
            return
        p = self.preview_source_path
        if not p.exists():
            return

        target_w = max(1, self.preview_label.winfo_width())
        target_h = max(1, self.preview_label.winfo_height())
        if target_w <= 1 or target_h <= 1:
            return

        if Image is not None and ImageTk is not None:
            try:
                src = Image.open(p).convert("RGBA")
                sw, sh = src.size
                scale = max(target_w / sw, target_h / sh)
                rw = max(1, int(math.ceil(sw * scale)))
                rh = max(1, int(math.ceil(sh * scale)))
                resized = src.resize((rw, rh), Image.Resampling.LANCZOS)

                # Center-crop so image fills the full preview box.
                left = max(0, (rw - target_w) // 2)
                top = max(0, (rh - target_h) // 2)
                cropped = resized.crop((left, top, left + target_w, top + target_h))

                img = ImageTk.PhotoImage(cropped)
                self.preview_image = img
                self.preview_label.configure(image=img, text="")
                return
            except Exception:
                pass

        # Tk fallback (without Pillow): best-effort fit while preserving aspect ratio.
        try:
            img = tk.PhotoImage(file=str(p))
        except Exception:
            return

        w = max(1, img.width())
        h = max(1, img.height())
        scale = max(w / target_w, h / target_h)
        if scale > 1:
            subsample = int(math.ceil(scale))
            img = img.subsample(subsample, subsample)

        self.preview_image = img
        self.preview_label.configure(image=img, text="")

    def _finish_run(self, code: int) -> None:
        self.running = False
        self.process = None
        self.start_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)

        if code == 0:
            self.progress_value.set(100.0)
            self.status_text.set("Completed")
            if self.output_path.get().strip():
                self._append_log("Saved final output to: " + self.output_path.get().strip())
            else:
                self._append_log("No final file saved (you left output empty).")
        else:
            self.status_text.set(f"Stopped (exit code {code})")

        # Temporary preview frames are deleted automatically after each run.
        if self.tempdir_obj is not None:
            self.tempdir_obj.cleanup()
            self.tempdir_obj = None

    def cancel(self) -> None:
        if not self.running:
            return
        self.status_text.set("Cancelling...")
        self._append_log("Cancelling process...")
        if self.process is not None:
            try:
                self.process.terminate()
            except Exception as exc:
                self._append_log(f"Cancel warning: {exc}")

    def _on_close(self) -> None:
        if self.process is not None and self.running:
            try:
                self.process.terminate()
            except Exception:
                pass
        if self.tempdir_obj is not None:
            self.tempdir_obj.cleanup()
            self.tempdir_obj = None
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = PrimitiveDesktopApp(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()