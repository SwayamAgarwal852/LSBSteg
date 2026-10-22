"""LSBSteg modern desktop app (CustomTkinter). Run with:  python app_modern.py

The classic window (app.py) is unchanged and still works. This window uses
the same checks, texts and jobs from gui_logic.py. Long jobs run in a worker
thread; this main thread polls its queue with root.after() and is the only
thread that touches widgets. There is no progress percentage and no Cancel
button on purpose (the engine has no hook for them; see PLAN.md D2).

Drag and drop is optional: it needs the tkinterdnd2 package. If that is
missing or cannot load, the app works the same with the Browse buttons.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import gui_logic as logic
from gui_logic import IMAGE, VIDEO

POLL_MS = 100
TITLE = "LSB Steganography - Modern"
NOTE_COLOUR = ("#a15c00", "#f0b45a")  # (light mode, dark mode)
BAR_OK, BAR_OVER = ("#3a7ebf", "#1f6aa5"), ("#c0392b", "#e74c3c")
MODES = {"Image": IMAGE, "Video": VIDEO}
COVER_TYPES = {
    IMAGE: [("Images", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")],
    VIDEO: [("Videos", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"), ("All files", "*.*")],
}
OUTPUT_TYPES = {IMAGE: [("PNG image", "*.png")], VIDEO: [("MKV video", "*.mkv")]}
ABOUT = (
    "What this is: a tool for covert communication. The text is hidden in the last bit of the "
    "R, G, B values of an image (saved as PNG) or of the frames of a video (saved as a lossless "
    "FFV1 MKV with the original audio). A 13-byte header stores the length and a CRC32 check.\n\n"
    "What it is not: encryption. Anyone with this tool can read the message.\n\n"
    "The message is destroyed by JPEG re-saving, lossy video re-encoding (e.g. MP4, social media, "
    "messaging apps), resizing and most cropping. See README.md (Limitations) for what we measured."
)


def enable_drag_and_drop(root) -> bool:
    """Load tkdnd into this window. Any failure means 'no drag and drop', silently."""
    try:
        from tkinterdnd2 import TkinterDnD
        TkinterDnD.require(root)
        return True
    except Exception:  # missing package, missing DLL, Tcl error: Browse buttons still work
        return False


class ModernApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.worker = logic.Worker()
        self.capacity = None  # bytes, after a cover was analysed
        self.loaded_message = None  # full text of a .txt too long to show in the box
        self.result_text = ""  # full, exact decoded text (the box may show a preview)
        self.last_encode = None  # (mode, cover, stego, payload bytes, capacity, seconds)
        self._images = {}  # keep CTkImage references alive
        self._stego_preview = None  # PIL image, to restore after the difference view

        root.title(TITLE)
        root.geometry("1100x760")
        root.minsize(980, 700)
        root.report_callback_exception = lambda exc_type, exc, tb: self.show_error(exc)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.cover = tk.StringVar()
        self.output = tk.StringVar()
        self.stego = tk.StringVar()
        self.status = tk.StringVar(value="Ready.")
        self.dnd = enable_drag_and_drop(root)
        self._build()
        self._poll_id = self.root.after(POLL_MS, self.poll_worker)

    # ------------------------------------------------------------ layout

    def _build(self):
        top = ctk.CTkFrame(self.root, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(top, text="LSB Steganography", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        self.dark_switch = ctk.CTkSwitch(top, text="Dark mode", command=self.on_theme_change)
        self.dark_switch.pack(side="right")
        if ctk.get_appearance_mode() == "Dark":
            self.dark_switch.select()
        self.mode_button = ctk.CTkSegmentedButton(top, values=list(MODES), command=self.on_mode_change)
        self.mode_button.set("Image")
        self.mode_button.pack(side="right", padx=16)
        ctk.CTkLabel(top, text="Mode:").pack(side="right")

        self.tabs = ctk.CTkTabview(self.root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=6)
        self._build_hide(self.tabs.add("Hide message"))
        self._build_reveal(self.tabs.add("Reveal message"))
        self._build_results(self.tabs.add("Results / About"))

        bottom = ctk.CTkFrame(self.root, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(bottom, textvariable=self.status, anchor="w").pack(side="left", fill="x", expand=True)
        self.busy_bar = ctk.CTkProgressBar(bottom, width=200, mode="determinate")
        self.busy_bar.set(0)
        self.busy_bar.pack(side="right")

        self.buttons = [self.browse_btn, self.load_btn, self.clear_btn, self.output_btn,
                        self.encode_btn, self.stego_btn, self.decode_btn, self.copy_btn,
                        self.save_btn, self.measure_btn]

    def _build_hide(self, tab):
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(0, weight=1)
        left = ctk.CTkFrame(tab, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Cover file", anchor="w").grid(row=0, column=0, columnspan=2, sticky="w")
        ctk.CTkEntry(left, textvariable=self.cover, state="readonly").grid(row=1, column=0, sticky="ew")
        self.browse_btn = ctk.CTkButton(left, text="Browse cover...", width=130, command=self.browse_cover)
        self.browse_btn.grid(row=1, column=1, padx=(6, 0))
        self.cover_drop = self._drop_zone(left, "cover")
        self.cover_drop.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)

        self.capacity_label = ctk.CTkLabel(left, text="Capacity: choose a cover file", anchor="w")
        self.capacity_label.grid(row=3, column=0, columnspan=2, sticky="w")
        self.capacity_bar = ctk.CTkProgressBar(left, progress_color=BAR_OK)
        self.capacity_bar.set(0)
        self.capacity_bar.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.notes_label = ctk.CTkLabel(left, text="", text_color=NOTE_COLOUR, anchor="w",
                                        justify="left", wraplength=560)
        self.notes_label.grid(row=5, column=0, columnspan=2, sticky="w")

        ctk.CTkLabel(left, text="Message", anchor="w").grid(row=6, column=0, sticky="w", pady=(6, 0))
        self.message_box = ctk.CTkTextbox(left, height=150, wrap="char")
        self.message_box.grid(row=7, column=0, sticky="nsew")
        self.message_box.bind("<<Modified>>", self.on_message_change)
        side = ctk.CTkFrame(left, fg_color="transparent")
        side.grid(row=7, column=1, sticky="n", padx=(6, 0))
        self.load_btn = ctk.CTkButton(side, text="Load .txt...", width=130, command=self.load_txt)
        self.load_btn.pack(pady=(0, 6))
        self.clear_btn = ctk.CTkButton(side, text="Clear message", width=130, command=self.clear_message)
        self.clear_btn.pack()
        self.size_label = ctk.CTkLabel(left, text="", anchor="w")
        self.size_label.grid(row=8, column=0, columnspan=2, sticky="w")
        left.rowconfigure(7, weight=1)

        ctk.CTkLabel(left, text="Output file", anchor="w").grid(row=9, column=0, sticky="w", pady=(6, 0))
        ctk.CTkEntry(left, textvariable=self.output).grid(row=10, column=0, sticky="ew")
        self.output_btn = ctk.CTkButton(left, text="Choose output...", width=130, command=self.choose_output)
        self.output_btn.grid(row=10, column=1, padx=(6, 0))
        self.encode_btn = ctk.CTkButton(left, text="Encode (hide message)", height=36,
                                        command=self.start_encode)
        self.encode_btn.grid(row=11, column=0, sticky="w", pady=10)

        right = ctk.CTkFrame(tab)
        right.grid(row=0, column=1, sticky="nsew")
        self.preview_labels = {}
        for row, name in enumerate(("Cover", "Stego")):
            ctk.CTkLabel(right, text=name, font=ctk.CTkFont(weight="bold")).grid(row=2 * row, column=0, pady=(8, 0))
            label = ctk.CTkLabel(right, text="(no preview)", width=330, height=250)
            label.grid(row=2 * row + 1, column=0, padx=10)
            self.preview_labels[name] = label
        self.diff_switch = ctk.CTkSwitch(right, text="Show difference x255", command=self.on_diff_toggle,
                                         state="disabled")
        self.diff_switch.grid(row=4, column=0, pady=(6, 0))
        self.diff_caption = ctk.CTkLabel(right, text="Available after encoding.", wraplength=320,
                                         justify="left", font=ctk.CTkFont(size=12))
        self.diff_caption.grid(row=5, column=0, padx=10, pady=(0, 8))

    def _build_reveal(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(5, weight=1)
        ctk.CTkLabel(tab, text="File to decode", anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkEntry(tab, textvariable=self.stego, state="readonly").grid(row=1, column=0, sticky="ew")
        self.stego_btn = ctk.CTkButton(tab, text="Browse...", width=130, command=self.browse_stego)
        self.stego_btn.grid(row=1, column=1, padx=(6, 0))
        self.stego_drop = self._drop_zone(tab, "stego")
        self.stego_drop.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        self.decode_btn = ctk.CTkButton(tab, text="Decode (reveal message)", height=36,
                                        command=self.start_decode)
        self.decode_btn.grid(row=3, column=0, sticky="w", pady=8)
        ctk.CTkLabel(tab, text="Result", anchor="w").grid(row=4, column=0, sticky="w")
        self.result_box = ctk.CTkTextbox(tab, wrap="char", state="disabled")
        self.result_box.grid(row=5, column=0, sticky="nsew")
        side = ctk.CTkFrame(tab, fg_color="transparent")
        side.grid(row=5, column=1, sticky="n", padx=(6, 0))
        self.copy_btn = ctk.CTkButton(side, text="Copy result", width=130, command=self.copy_result)
        self.copy_btn.pack(pady=(0, 6))
        self.save_btn = ctk.CTkButton(side, text="Save result...", width=130, command=self.save_result)
        self.save_btn.pack()

    def _build_results(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.measure_btn = ctk.CTkButton(tab, text="Measure quality of the last encode",
                                         command=self.start_measure, state="disabled")
        self.measure_btn.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(tab, text="Compares the cover and the stego file with metrics.py "
                               "(MSE and PSNR). Runs only when you press the button.",
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(2, 6))
        self.metrics_box = ctk.CTkTextbox(tab, height=170, state="disabled")
        self.metrics_box.grid(row=2, column=0, sticky="nsew")
        about = ctk.CTkTextbox(tab, height=170, wrap="word")
        about.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        about.insert("1.0", ABOUT)
        about.configure(state="disabled")

    def _drop_zone(self, parent, target):
        text = ("Or drag and drop one file here" if self.dnd
                else "Drag and drop is not available; use the Browse button")
        zone = ctk.CTkFrame(parent, height=44, border_width=1)
        label = ctk.CTkLabel(zone, text=text)
        label.pack(expand=True, fill="both", padx=6, pady=6)
        if self.dnd:
            from tkinterdnd2 import DND_FILES
            # Register the frame and everything inside it: CTk draws on child widgets,
            # so the drop can land on any of them.
            for widget in [zone, *self._descendants(zone)]:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", lambda event, t=target: self.on_drop(t, event))
        return zone

    @classmethod
    def _descendants(cls, widget):
        for child in widget.winfo_children():
            yield child
            yield from cls._descendants(child)

    # ------------------------------------------------------------ small helpers

    def mode(self) -> str:
        return MODES[self.mode_button.get()]

    def show_error(self, exc):
        title, text = logic.friendly_message(exc)
        self.status.set(title + ".")
        messagebox.showerror(title, text, parent=self.root)

    def message(self) -> str:
        if self.loaded_message is not None:
            return self.loaded_message
        return self.message_box.get("1.0", "end-1c")

    def set_preview(self, name, pil_image):
        label = self.preview_labels[name]
        if pil_image is None:
            self._images.pop(name, None)
            label.configure(image="", text="(no preview)")  # "" (not None) clears a CTkLabel image
            return
        image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=pil_image.size)
        self._images[name] = image
        label.configure(image=image, text="")

    def set_textbox(self, box, text):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def set_result(self, text):
        self.result_text = text
        shown, note = logic.display_text(text)
        self.set_textbox(self.result_box, shown)
        if note:
            messagebox.showinfo("Long message", note, parent=self.root)

    def set_busy(self, busy, text=""):
        for button in self.buttons:
            button.configure(state="disabled" if busy else "normal")
        self.mode_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.diff_switch.configure(state="disabled")
            self.status.set(text)
            self.busy_bar.configure(mode="indeterminate")
            self.busy_bar.start()
        else:
            self.busy_bar.stop()
            self.busy_bar.configure(mode="determinate")
            self.busy_bar.set(0)
            self.measure_btn.configure(state="normal" if self.last_encode else "disabled")
            self.diff_switch.configure(state="normal" if self.last_encode else "disabled")

    def start_job(self, job, func, *args, text):
        self.set_busy(True, text)
        self.worker.start(job, func, *args)

    def reset_after_encode_state(self):
        self.last_encode = None
        self._stego_preview = None
        self.diff_switch.deselect()
        self.diff_switch.configure(state="disabled")
        self.diff_caption.configure(text="Available after encoding.")
        self.measure_btn.configure(state="disabled")

    # ------------------------------------------------------------ user actions

    def on_theme_change(self):
        ctk.set_appearance_mode("Dark" if self.dark_switch.get() else "Light")

    def on_mode_change(self, _value=None):
        self.cover.set("")
        self.output.set("")
        self.stego.set("")
        self.capacity = None
        self.capacity_label.configure(text="Capacity: choose a cover file")
        self.notes_label.configure(text="")
        self.set_preview("Cover", None)
        self.set_preview("Stego", None)
        self.reset_after_encode_state()
        self.on_message_change()

    def on_drop(self, target, event):
        try:
            path = logic.dropped_file(self.root.tk.splitlist(event.data))
        except logic.InputError as exc:
            self.show_error(exc)
            return event.action
        if self.worker.busy:
            self.show_error(logic.InputError("Please wait until the current task has finished."))
        elif target == "cover":
            self.select_cover(path)
        else:
            self.stego.set(path)
        return event.action

    def browse_cover(self):
        mode = self.mode()
        name = filedialog.askopenfilename(parent=self.root, title="Choose cover",
                                          filetypes=COVER_TYPES[mode])
        if name:
            self.select_cover(name)

    def select_cover(self, name):
        """Validate the cover, then analyse it (capacity, notes, preview) in the worker."""
        mode = self.mode()
        try:
            path = logic.validate_cover(mode, name)
        except logic.InputError as exc:
            self.show_error(exc)
            return
        self.cover.set(str(path))
        if not self.output.get():
            self.output.set(logic.default_output_path(mode, name))
        self.capacity = None
        self.capacity_label.configure(text="Capacity: calculating...")
        self.reset_after_encode_state()
        self.start_job("analyse", logic.analyse_cover, mode, path, text="Reading cover...")

    def browse_stego(self):
        mode = self.mode()
        name = filedialog.askopenfilename(parent=self.root, title="Choose file to decode",
                                          filetypes=OUTPUT_TYPES[mode] + COVER_TYPES[mode])
        if name:
            self.stego.set(name)

    def choose_output(self):
        mode = self.mode()
        name = filedialog.asksaveasfilename(parent=self.root, title="Save output as",
                                            defaultextension=logic.OUTPUT_EXTENSION[mode],
                                            filetypes=OUTPUT_TYPES[mode])
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
        message = self.message()
        self.size_label.configure(text=logic.message_size_text(message, self.capacity))
        usage = logic.capacity_usage(message, self.capacity)
        self.capacity_bar.set(usage.fraction if usage else 0)
        self.capacity_bar.configure(progress_color=BAR_OVER if usage and usage.over else BAR_OK)

    def start_encode(self):
        mode = self.mode()
        try:
            cover, output = logic.validate_encode(mode, self.cover.get(), self.message(),
                                                  self.output.get())
        except logic.InputError as exc:
            self.show_error(exc)
            return
        self.reset_after_encode_state()
        self.start_job("encode", logic.run_encode, mode, cover, self.message(), output,
                       text="Hiding the message..." + (" (video: this can take a while)"
                                                       if mode == VIDEO else ""))

    def start_decode(self):
        mode = self.mode()
        try:
            path = logic.validate_decode(mode, self.stego.get())
        except logic.InputError as exc:
            self.show_error(exc)
            return
        self.start_job("decode", logic.run_decode, mode, path, text="Looking for a hidden message...")

    def start_measure(self):
        if not self.last_encode:
            return
        mode, cover, stego, size, capacity, seconds = self.last_encode
        self.start_job("measure", logic.measure_quality, mode, cover, stego, size, capacity, seconds,
                       text="Measuring quality..." + (" (video: decodes both videos)"
                                                      if mode == VIDEO else ""))

    def on_diff_toggle(self):
        if not self.last_encode:
            self.diff_switch.deselect()
            return
        if self.diff_switch.get():
            mode, cover, stego = self.last_encode[:3]
            self.start_job("difference", logic.difference_crop, mode, cover, stego,
                           text="Computing the difference view...")
        else:
            self.set_preview("Stego", self._stego_preview)
            self.diff_caption.configure(text="Showing the stego file.")

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
        # Cancel every pending timer (ours and CustomTkinter's own) at Tcl level, then
        # destroy. Without this, CTk timers fire after destroy and print
        # 'invalid command name ...' to the console. after_cancel() is not used here:
        # it also deletes the Tcl command, which CTk's destroy() then fails to delete.
        for job in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", job)
        self.root.destroy()

    # ------------------------------------------------------------ worker results (main thread)

    def poll_worker(self):
        for status, job, value in self.worker.poll():
            self.set_busy(False)
            if status == "error":
                if job == "analyse":
                    self.capacity_label.configure(text="Capacity: unknown (cover could not be read)")
                if job == "difference":
                    self.diff_switch.deselect()
                self.show_error(value)
            else:
                getattr(self, f"on_{job}_done")(value)
        self._poll_id = self.root.after(POLL_MS, self.poll_worker)

    def on_analyse_done(self, report):
        self.capacity = report.capacity
        self.capacity_label.configure(text=logic.capacity_text(report.capacity))
        self.notes_label.configure(text="\n".join("Note: " + n for n in report.notes))
        self.set_preview("Cover", report.preview)
        self.set_preview("Stego", None)
        self.on_message_change()
        self.status.set("Cover loaded.")

    def on_encode_done(self, report):
        mode = self.mode()
        self.last_encode = (mode, Path(self.cover.get()), report.output,
                            len(self.message().encode("utf-8")), self.capacity, report.seconds)
        self._stego_preview = report.preview
        self.set_preview("Stego", report.preview)
        self.set_busy(False)  # enables Measure quality and the difference switch
        self.diff_caption.configure(text="Showing the stego file.")
        self.stego.set(str(report.output))  # ready to decode straight away
        self.status.set(f"Message hidden in {report.output.name} "
                        f"({logic.format_seconds(report.seconds)}).")
        messagebox.showinfo("Done", f"The message was hidden in:\n{report.output}",
                            parent=self.root)

    def on_decode_done(self, report):
        self.set_result(report.text)
        self.status.set(f"Found a hidden message of {len(report.text):,} characters "
                        f"({logic.format_seconds(report.seconds)}).")

    def on_measure_done(self, report):
        self.set_textbox(self.metrics_box, "\n".join(logic.quality_lines(report)))
        self.tabs.set("Results / About")
        self.status.set("Quality measured.")

    def on_difference_done(self, image):
        self.set_preview("Stego", image)
        w, h = image.size
        self.diff_caption.configure(text=f"Difference x255: top-left {w}x{h} pixels at 1:1. "
                                         "White/colour = a value that changed by 1; black = unchanged.")
        self.status.set("Showing the difference view.")


def main():
    root = ctk.CTk()
    ModernApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
