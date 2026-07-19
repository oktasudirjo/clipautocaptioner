#!/usr/bin/env python3
"""
auto-captioner GUI
-------------------
Tkinter front-end for core.py — exposes every style/config setting so you
don't have to hand-edit YAML. Uses the same pipeline as captioner.py (CLI),
so results are identical between the two.

Usage:
    python gui.py
"""

import threading
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox

import core


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODES = ["word", "sentence"]
ALIGNMENTS = ["left", "center", "right"]
DEVICES = ["cpu", "cuda"]


class ColorPicker(ttk.Frame):
    """A small swatch + hex entry that opens a color chooser on click."""

    def __init__(self, parent, initial="#FFFFFF", **kwargs):
        super().__init__(parent, **kwargs)
        self.var = tk.StringVar(value=initial)

        self.swatch = tk.Label(self, width=3, relief="sunken", bg=initial, cursor="hand2")
        self.swatch.pack(side="left", padx=(0, 6))
        self.swatch.bind("<Button-1>", self._pick)

        self.entry = ttk.Entry(self, textvariable=self.var, width=9)
        self.entry.pack(side="left")
        self.var.trace_add("write", self._on_type)

    def _pick(self, _event=None):
        color = colorchooser.askcolor(color=self.var.get() or "#FFFFFF")
        if color and color[1]:
            self.var.set(color[1].upper())

    def _on_type(self, *_):
        val = self.var.get()
        if len(val) == 7 and val.startswith("#"):
            try:
                self.swatch.configure(bg=val)
            except tk.TclError:
                pass

    def get(self):
        return self.var.get()


class NullableColorPicker(ttk.Frame):
    """Color picker with an 'enabled' checkbox — used for highlight_color,
    which can be disabled (null) entirely."""

    def __init__(self, parent, initial="#FFD400", enabled=True, **kwargs):
        super().__init__(parent, **kwargs)
        self.enabled_var = tk.BooleanVar(value=enabled)
        self.check = ttk.Checkbutton(self, variable=self.enabled_var, command=self._toggle)
        self.check.pack(side="left")
        self.picker = ColorPicker(self, initial=initial)
        self.picker.pack(side="left")
        self._toggle()

    def _toggle(self):
        state = "normal" if self.enabled_var.get() else "disabled"
        self.picker.entry.configure(state=state)
        self.picker.swatch.configure(cursor="hand2" if self.enabled_var.get() else "arrow")

    def get(self):
        return self.picker.get() if self.enabled_var.get() else None


class CaptionerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Auto-Captioner")
        self.geometry("640x760")
        self.minsize(600, 700)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.save_srt = tk.BooleanVar(value=False)
        self.msg_queue = queue.Queue()
        self.worker = None

        self._build_ui()
        self.after(150, self._poll_queue)

    # ------------------------------------------------------------------
    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        file_tab = ttk.Frame(notebook)
        style_tab = ttk.Frame(notebook)
        transcribe_tab = ttk.Frame(notebook)
        notebook.add(file_tab, text="File")
        notebook.add(style_tab, text="Caption Style")
        notebook.add(transcribe_tab, text="Transcription")

        self._build_file_tab(file_tab)
        self._build_style_tab(style_tab)
        self._build_transcribe_tab(transcribe_tab)

        # Run bar + log, always visible below tabs
        bottom = ttk.Frame(self)
        bottom.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        self.run_btn = ttk.Button(bottom, text="Run", command=self._on_run)
        self.run_btn.pack(anchor="w", pady=(0, 6))

        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 6))

        self.log = tk.Text(bottom, height=10, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    def _build_file_tab(self, tab):
        pad = {"padx": 8, "pady": 6}

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Input video:", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.input_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse_input).pack(side="left", padx=(6, 0))

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Output video:", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.output_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse_output).pack(side="left", padx=(6, 0))

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Checkbutton(row, text="Also save a plain .srt file", variable=self.save_srt).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Config file (optional):", width=20).pack(side="left")
        self.config_path = tk.StringVar()
        ttk.Entry(row, textvariable=self.config_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Load...", command=self._load_config_file).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Save as...", command=self._save_config_file).pack(side="left", padx=(6, 0))

    def _build_style_tab(self, tab):
        pad = {"padx": 8, "pady": 5}

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Mode:", width=16).pack(side="left")
        self.mode = tk.StringVar(value="word")
        ttk.Combobox(row, textvariable=self.mode, values=MODES, state="readonly", width=12).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Words per group:", width=16).pack(side="left")
        self.words_per_group = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=1, to=10, textvariable=self.words_per_group, width=5).pack(side="left")
        ttk.Label(row, text="(word mode only; >1 enables karaoke highlight within the group)",
                  foreground="gray").pack(side="left", padx=(8, 0))

        ttk.Separator(tab).pack(fill="x", padx=8, pady=8)

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Font name:", width=16).pack(side="left")
        self.font_name = tk.StringVar(value="Arial Black")
        ttk.Entry(row, textvariable=self.font_name, width=24).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Font size:", width=16).pack(side="left")
        self.font_size = tk.IntVar(value=64)
        ttk.Spinbox(row, from_=8, to=200, textvariable=self.font_size, width=6).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        self.bold = tk.BooleanVar(value=True)
        self.italic = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Bold", variable=self.bold).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row, text="Italic", variable=self.italic).pack(side="left")

        ttk.Separator(tab).pack(fill="x", padx=8, pady=8)

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Text color:", width=16).pack(side="left")
        self.text_color = ColorPicker(row, initial="#FFFFFF")
        self.text_color.pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Outline color:", width=16).pack(side="left")
        self.outline_color = ColorPicker(row, initial="#000000")
        self.outline_color.pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Outline width:", width=16).pack(side="left")
        self.outline_width = tk.IntVar(value=3)
        ttk.Spinbox(row, from_=0, to=15, textvariable=self.outline_width, width=5).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Shadow depth:", width=16).pack(side="left")
        self.shadow = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=0, to=10, textvariable=self.shadow, width=5).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Highlight color:", width=16).pack(side="left")
        self.highlight_color = NullableColorPicker(row, initial="#FFD400", enabled=True)
        self.highlight_color.pack(side="left")
        ttk.Label(row, text="(active word in karaoke mode)", foreground="gray").pack(side="left", padx=(8, 0))

        ttk.Separator(tab).pack(fill="x", padx=8, pady=8)

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Alignment:", width=16).pack(side="left")
        self.alignment = tk.StringVar(value="center")
        ttk.Combobox(row, textvariable=self.alignment, values=ALIGNMENTS, state="readonly", width=12).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Position from bottom (%):", width=22).pack(side="left")
        self.position_pct = tk.IntVar(value=12)
        ttk.Spinbox(row, from_=0, to=90, textvariable=self.position_pct, width=6).pack(side="left")

    def _build_transcribe_tab(self, tab):
        pad = {"padx": 8, "pady": 6}

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Whisper model:", width=16).pack(side="left")
        self.whisper_model = tk.StringVar(value="small")
        ttk.Combobox(row, textvariable=self.whisper_model, values=WHISPER_MODELS,
                     state="readonly", width=12).pack(side="left")
        ttk.Label(row, text="(bigger = slower, more accurate)", foreground="gray").pack(side="left", padx=(8, 0))

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Device:", width=16).pack(side="left")
        self.device = tk.StringVar(value="cpu")
        ttk.Combobox(row, textvariable=self.device, values=DEVICES, state="readonly", width=12).pack(side="left")
        ttk.Label(row, text="(auto-falls back to CPU if CUDA unavailable)",
                  foreground="gray").pack(side="left", padx=(8, 0))

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Compute type:", width=16).pack(side="left")
        self.compute_type = tk.StringVar(value="int8")
        ttk.Combobox(row, textvariable=self.compute_type,
                     values=["int8", "float16", "float32"], state="readonly", width=12).pack(side="left")

        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Language code:", width=16).pack(side="left")
        self.language = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.language, width=8).pack(side="left")
        ttk.Label(row, text="(e.g. 'en' — leave blank to auto-detect)",
                  foreground="gray").pack(side="left", padx=(8, 0))

    # ------------------------------------------------------------------
    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select a video file",
            filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All files", "*.*")],
        )
        if path:
            self.input_path.set(path)
            if not self.output_path.get():
                p = Path(path)
                self.output_path.set(str(p.with_name(p.stem + "_captioned.mp4")))

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save captioned video as",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self.output_path.set(path)

    def _collect_config(self) -> dict:
        return {
            "whisper_model": self.whisper_model.get(),
            "language": self.language.get().strip() or None,
            "device": self.device.get(),
            "compute_type": self.compute_type.get(),
            "mode": self.mode.get(),
            "words_per_group": int(self.words_per_group.get()),
            "font_name": self.font_name.get(),
            "font_size": int(self.font_size.get()),
            "bold": bool(self.bold.get()),
            "italic": bool(self.italic.get()),
            "text_color": self.text_color.get(),
            "outline_color": self.outline_color.get(),
            "outline_width": int(self.outline_width.get()),
            "shadow": int(self.shadow.get()),
            "highlight_color": self.highlight_color.get(),
            "alignment": self.alignment.get(),
            "position_from_bottom_pct": int(self.position_pct.get()),
            "hard_subs": True,
        }

    def _apply_config(self, cfg: dict):
        self.whisper_model.set(cfg.get("whisper_model", "small"))
        self.language.set(cfg.get("language") or "")
        self.device.set(cfg.get("device", "cpu"))
        self.compute_type.set(cfg.get("compute_type", "int8"))
        self.mode.set(cfg.get("mode", "word"))
        self.words_per_group.set(cfg.get("words_per_group", 1))
        self.font_name.set(cfg.get("font_name", "Arial Black"))
        self.font_size.set(cfg.get("font_size", 64))
        self.bold.set(cfg.get("bold", True))
        self.italic.set(cfg.get("italic", False))
        self.text_color.var.set(cfg.get("text_color", "#FFFFFF"))
        self.outline_color.var.set(cfg.get("outline_color", "#000000"))
        self.outline_width.set(cfg.get("outline_width", 3))
        self.shadow.set(cfg.get("shadow", 1))
        hl = cfg.get("highlight_color")
        self.highlight_color.enabled_var.set(hl is not None)
        if hl:
            self.highlight_color.picker.var.set(hl)
        self.highlight_color._toggle()
        self.alignment.set(cfg.get("alignment", "center"))
        self.position_pct.set(cfg.get("position_from_bottom_pct", 12))

    def _load_config_file(self):
        path = filedialog.askopenfilename(title="Load config", filetypes=[("YAML", "*.yaml *.yml")])
        if not path:
            return
        try:
            cfg = core.load_config(path)
            self._apply_config(cfg)
            self.config_path.set(path)
        except Exception as e:
            messagebox.showerror("Failed to load config", str(e))

    def _save_config_file(self):
        path = filedialog.asksaveasfilename(title="Save config as", defaultextension=".yaml",
                                             filetypes=[("YAML", "*.yaml *.yml")])
        if not path:
            return
        try:
            core.save_config(self._collect_config(), path)
            self.config_path.set(path)
            self._log(f"Saved config to {path}")
        except Exception as e:
            messagebox.showerror("Failed to save config", str(e))

    # ------------------------------------------------------------------
    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_run(self):
        if self.worker and self.worker.is_alive():
            return

        input_path = self.input_path.get().strip()
        output_path = self.output_path.get().strip()

        if not input_path:
            messagebox.showwarning("Missing input", "Choose an input video file first.")
            return
        if not Path(input_path).exists():
            messagebox.showerror("File not found", f"Input file not found:\n{input_path}")
            return
        if not output_path:
            p = Path(input_path)
            output_path = str(p.with_name(p.stem + "_captioned.mp4"))
            self.output_path.set(output_path)

        cfg = self._collect_config()
        save_srt = self.save_srt.get()

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self.run_btn.configure(state="disabled")
        self.progress.start(12)

        self.worker = threading.Thread(
            target=self._worker_run, args=(input_path, output_path, cfg, save_srt), daemon=True
        )
        self.worker.start()

    def _worker_run(self, input_path, output_path, cfg, save_srt):
        try:
            core.run_pipeline(input_path, output_path, cfg, save_srt=save_srt,
                               progress_cb=lambda m: self.msg_queue.put(("log", m)))
            self.msg_queue.put(("done", output_path))
        except Exception as e:
            self.msg_queue.put(("error", str(e)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self._log(f"\nDone! Saved to: {payload}")
                    self.progress.stop()
                    self.run_btn.configure(state="normal")
                    messagebox.showinfo("Finished", f"Captioned video saved to:\n{payload}")
                elif kind == "error":
                    self._log(f"\nERROR: {payload}")
                    self.progress.stop()
                    self.run_btn.configure(state="normal")
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)


if __name__ == "__main__":
    app = CaptionerGUI()
    app.mainloop()
