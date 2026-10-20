"""LSBSteg desktop app (Tkinter). Run with:  python app.py

This file only builds and updates widgets. All checks, texts and the
actual work live in gui_logic.py (tested without a window). Long jobs run
in a worker thread; this main thread polls its queue with root.after()
and is the only thread that touches widgets.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

import gui_logic as logic
from gui_logic import IMAGE, VIDEO

POLL_MS = 100
COVER_TYPES = {
    IMAGE: [("Images", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")],
    VIDEO: [("Videos", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"), ("All files", "*.*")],
}
OUTPUT_TYPES = {IMAGE: [("PNG image", "*.png")], VIDEO: [("MKV video", "*.mkv")]}


class StegoApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.worker = logic.Worker()
        self.capacity = None  # bytes, after a cover was analysed
        self.loaded_message = None  # full text of a .txt too long to show in the box
        self.result_text = ""  # full, exact decoded text (the box may show a preview)
        self._photos = {}  # keep PhotoImage references alive

        root.title("LSB Steganography - Image and Video")
        root.minsize(760, 640)
        # Errors inside Tk callbacks: friendly box instead of a console traceback.
        root.report_callback_exception = lambda exc_type, exc, tb: self.show_error(exc)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.mode = tk.StringVar(value=IMAGE)
        self.cover = tk.StringVar()
        self.output = tk.StringVar()
        self.stego = tk.StringVar()
        self.capacity_label = tk.StringVar(value="Capacity: choose a cover file")
        self.size_label = tk.StringVar(value="")
        self.notes_label = tk.StringVar(value="")
        self.status = tk.StringVar(value="Ready.")
        self._build()
        self._poll_id = self.root.after(POLL_MS, self.poll_worker)

    # ------------------------------------------------------------ layout

    def _build(self):
        f = ttk.Frame(self.root, padding=8)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        modes = ttk.Frame(f)
        modes.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(modes, text="Mode:").pack(side="left")
        for value, text in ((IMAGE, "Image"), (VIDEO, "Video")):
            ttk.Radiobutton(modes, text=text, value=value, variable=self.mode,
                            command=self.on_mode_change).pack(side="left", padx=6)

        # --- encode section
        ttk.Label(f, text="Cover file:").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.cover, state="readonly").grid(row=1, column=1, sticky="ew")
        self.browse_btn = ttk.Button(f, text="Browse cover...", command=self.browse_cover)
        self.browse_btn.grid(row=1, column=2, sticky="ew", padx=4)
        ttk.Label(f, textvariable=self.capacity_label).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(f, textvariable=self.notes_label, foreground="#a15c00",
                  wraplength=720, justify="left").grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Label(f, text="Message:").grid(row=4, column=0, sticky="nw")
        self.message_box = self._text_with_scrollbar(f, height=5)
        self.message_box.master.grid(row=4, column=1, sticky="nsew")
        self.message_box.bind("<<Modified>>", self.on_message_change)
        side = ttk.Frame(f)
        side.grid(row=4, column=2, sticky="n", padx=4)
        self.load_btn = ttk.Button(side, text="Load .txt...", command=self.load_txt)
        self.load_btn.pack(fill="x")
        self.clear_btn = ttk.Button(side, text="Clear message", command=self.clear_message)
        self.clear_btn.pack(fill="x", pady=2)
        ttk.Label(f, textvariable=self.size_label).grid(row=5, column=1, columnspan=2, sticky="w")

        ttk.Label(f, text="Output file:").grid(row=6, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.output).grid(row=6, column=1, sticky="ew")
        self.output_btn = ttk.Button(f, text="Choose output...", command=self.choose_output)
        self.output_btn.grid(row=6, column=2, sticky="ew", padx=4)
        self.encode_btn = ttk.Button(f, text="Encode (hide message)", command=self.start_encode)
        self.encode_btn.grid(row=7, column=1, sticky="w", pady=4)

        ttk.Separator(f).grid(row=8, column=0, columnspan=3, sticky="ew", pady=4)

        # --- decode section
        ttk.Label(f, text="File to decode:").grid(row=9, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.stego, state="readonly").grid(row=9, column=1, sticky="ew")
        self.stego_btn = ttk.Button(f, text="Browse...", command=self.browse_stego)
        self.stego_btn.grid(row=9, column=2, sticky="ew", padx=4)
        self.decode_btn = ttk.Button(f, text="Decode (reveal message)", command=self.start_decode)
        self.decode_btn.grid(row=10, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Result:").grid(row=11, column=0, sticky="nw")
        self.result_box = self._text_with_scrollbar(f, height=5)
        self.result_box.master.grid(row=11, column=1, sticky="nsew")
        self.result_box.configure(state="disabled")
        side = ttk.Frame(f)
        side.grid(row=11, column=2, sticky="n", padx=4)
        self.copy_btn = ttk.Button(side, text="Copy result", command=self.copy_result)
        self.copy_btn.pack(fill="x")
        self.save_btn = ttk.Button(side, text="Save result...", command=self.save_result)
        self.save_btn.pack(fill="x", pady=2)

        # --- previews
        previews = ttk.Frame(f)
        previews.grid(row=12, column=0, columnspan=3, pady=6)
        self.preview_labels = {}
        for col, name in enumerate(("Cover", "Stego")):
            box = ttk.LabelFrame(previews, text=name, width=330, height=260)
            box.grid(row=0, column=col, padx=6)
            box.grid_propagate(False)
            label = ttk.Label(box, text="(no preview)", anchor="center")
            label.place(relx=0.5, rely=0.5, anchor="center")
            self.preview_labels[name] = label

        # --- status bar
        bottom = ttk.Frame(f)
        bottom.grid(row=13, column=0, columnspan=3, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status, relief="sunken", anchor="w").grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(bottom, mode="determinate", length=160)
        self.progress.grid(row=0, column=1, padx=4)
        f.rowconfigure(4, weight=1)
        f.rowconfigure(11, weight=1)

        self.buttons = [self.browse_btn, self.load_btn, self.clear_btn, self.output_btn,
                        self.encode_btn, self.stego_btn, self.decode_btn, self.copy_btn,
                        self.save_btn]

    @staticmethod
    def _text_with_scrollbar(parent, height):
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, height=height, wrap="char", undo=True)
        bar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        return text

    # ------------------------------------------------------------ small helpers

    def show_error(self, exc):
        title, text = logic.friendly_message(exc)
        self.status.set(title + ".")
        messagebox.showerror(title, text, parent=self.root)

    def message(self) -> str:
        if self.loaded_message is not None:
            return self.loaded_message
        return self.message_box.get("1.0", "end-1c")

    def set_preview(self, name, pil_image):
        if pil_image is None:
            self._photos.pop(name, None)
            self.preview_labels[name].configure(image="", text="(no preview)")
            return
        photo = ImageTk.PhotoImage(pil_image)  # created here, in the main thread
        self._photos[name] = photo
        self.preview_labels[name].configure(image=photo, text="")

    def set_result(self, text):
        self.result_text = text
        shown, note = logic.display_text(text)
        self.result_box.configure(state="normal")
        self.result_box.delete("1.0", "end")
        self.result_box.insert("1.0", shown)
        self.result_box.configure(state="disabled")
        if note:
            messagebox.showinfo("Long message", note, parent=self.root)

    def set_busy(self, busy, text=""):
        for button in self.buttons:
            button.configure(state="disabled" if busy else "normal")
        if busy:
            self.status.set(text)
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            # An idle indeterminate bar still shows a block; empty it instead.
            self.progress.configure(mode="determinate", value=0)

    def start_job(self, job, func, *args, text):
        self.set_busy(True, text)
        self.worker.start(job, func, *args)

    # ------------------------------------------------------------ user actions

    def on_mode_change(self):
        self.cover.set("")
        self.output.set("")
        self.stego.set("")
        self.capacity = None
        self.capacity_label.set("Capacity: choose a cover file")
        self.notes_label.set("")
        self.set_preview("Cover", None)
        self.set_preview("Stego", None)
        self.on_message_change()

    def browse_cover(self):
        mode = self.mode.get()
        name = filedialog.askopenfilename(parent=self.root, title="Choose cover",
                                          filetypes=COVER_TYPES[mode])
        if name:
            self.select_cover(name)

    def select_cover(self, name):
        """Validate the cover, then analyse it (capacity, notes, preview) in the worker."""
        mode = self.mode.get()
        try:
            path = logic.validate_cover(mode, name)
        except logic.InputError as exc:
            self.show_error(exc)
            return
        self.cover.set(str(path))
        if not self.output.get():
            self.output.set(logic.default_output_path(mode, name))
        self.capacity = None
        self.capacity_label.set("Capacity: calculating...")
        self.start_job("analyse", logic.analyse_cover, mode, path, text="Reading cover...")

    def browse_stego(self):
        mode = self.mode.get()
        types = OUTPUT_TYPES[mode] + COVER_TYPES[mode]
        name = filedialog.askopenfilename(parent=self.root, title="Choose file to decode",
                                          filetypes=types)
        if name:
            self.stego.set(name)

    def choose_output(self):
        mode = self.mode.get()
        ext = logic.OUTPUT_EXTENSION[mode]
        name = filedialog.asksaveasfilename(parent=self.root, title="Save output as",
                                            defaultextension=ext, filetypes=OUTPUT_TYPES[mode])
        if name:
            self.output.set(name)

    def load_txt(self):
        name = filedialog.askopenfilename(parent=self.root, title="Load message",
                                          filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if name:
            self.load_message_file(name)

    def load_message_file(self, name):
        try:
            text = logic.read_text_file(name)
        except Exception as exc:  # e.g. not UTF-8 -> friendly box
            self.show_error(exc)
            return
        self.clear_message()
        if logic.is_safe_to_display(text):
            self.message_box.insert("1.0", text)
        else:
            # Too long for the Text widget: keep it in memory, show a summary.
            self.loaded_message = text
            self.message_box.insert("1.0", f"[Message loaded from {Path(name).name}: "
                                           f"{len(text):,} characters - too long to show here. "
                                           "Press 'Clear message' to type instead.]")
            self.message_box.configure(state="disabled")
        self.on_message_change()

    def clear_message(self):
        self.loaded_message = None
        self.message_box.configure(state="normal")
        self.message_box.delete("1.0", "end")
        self.on_message_change()

    def on_message_change(self, _event=None):
        self.message_box.edit_modified(False)  # re-arm the <<Modified>> event
        self.size_label.set(logic.message_size_text(self.message(), self.capacity))

    def start_encode(self):
        mode = self.mode.get()
        try:
            cover, output = logic.validate_encode(mode, self.cover.get(), self.message(),
                                                  self.output.get())
        except logic.InputError as exc:
            self.show_error(exc)
            return
        self.start_job("encode", logic.run_encode, mode, cover, self.message(), output,
                       text="Hiding the message..." + (" (video: this can take a while)"
                                                       if mode == VIDEO else ""))

    def start_decode(self):
        mode = self.mode.get()
        try:
            path = logic.validate_decode(mode, self.stego.get())
        except logic.InputError as exc:
            self.show_error(exc)
            return
        self.start_job("decode", logic.run_decode, mode, path, text="Looking for a hidden message...")

    def copy_result(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.result_text)
        self.status.set(f"Copied {len(self.result_text):,} characters to the clipboard.")

    def save_result(self):
        name = filedialog.asksaveasfilename(parent=self.root, title="Save result as",
                                            defaultextension=".txt",
                                            filetypes=[("Text files", "*.txt")])
        if name:
            try:
                Path(name).write_text(self.result_text, encoding="utf-8", newline="")
                self.status.set(f"Saved result to {Path(name).name}.")
            except OSError as exc:
                self.show_error(exc)

    def on_close(self):
        if self.worker.busy:
            # Stopping mid-way would leave ffmpeg and a temporary file behind.
            messagebox.showinfo("Please wait", "A task is still running. Close the window "
                                "when it has finished.", parent=self.root)
            return
        self.close()

    def close(self):
        # Cancel the pending poll first: a timer left behind would fire after the
        # window is gone ('invalid command name ...poll_worker' on the console).
        self.root.after_cancel(self._poll_id)
        self.root.destroy()

    # ------------------------------------------------------------ worker results (main thread)

    def poll_worker(self):
        for status, job, value in self.worker.poll():
            self.set_busy(False)
            if status == "error":
                if job == "analyse":
                    self.capacity_label.set("Capacity: unknown (cover could not be read)")
                self.show_error(value)
            else:
                getattr(self, f"on_{job}_done")(value)
        self._poll_id = self.root.after(POLL_MS, self.poll_worker)

    def on_analyse_done(self, report):
        self.capacity = report.capacity
        self.capacity_label.set(logic.capacity_text(report.capacity))
        self.notes_label.set("\n".join("Note: " + n for n in report.notes))
        self.set_preview("Cover", report.preview)
        self.set_preview("Stego", None)
        self.on_message_change()
        self.status.set("Cover loaded.")

    def on_encode_done(self, report):
        self.set_preview("Stego", report.preview)
        self.stego.set(str(report.output))  # ready to decode straight away
        self.status.set(f"Message hidden in {report.output.name} "
                        f"({logic.format_seconds(report.seconds)}).")
        messagebox.showinfo("Done", f"The message was hidden in:\n{report.output}",
                            parent=self.root)

    def on_decode_done(self, report):
        self.set_preview("Stego", report.preview)
        self.set_result(report.text)
        self.status.set(f"Found a hidden message of {len(report.text):,} characters "
                        f"({logic.format_seconds(report.seconds)}).")


def main():
    root = tk.Tk()
    StegoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
