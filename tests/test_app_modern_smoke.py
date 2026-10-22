"""Smoke tests for app_modern.py: build the real CustomTkinter window, drive it from code, destroy it.

Message boxes are replaced by recorders so nothing blocks. This proves the
wiring (validation -> worker thread -> queue -> widgets); it is NOT a
replacement for clicking through GUI_CHECKLIST.md by hand.
"""

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ctk = pytest.importorskip("customtkinter")
import app_modern  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def run_window_in_subprocess(block_dnd: bool):
    """Create and destroy the modern window in a fresh Python; return (proc, dnd flag)."""
    code = textwrap.dedent(f"""
        import sys
        if {block_dnd}:
            sys.modules["tkinterdnd2"] = None  # makes 'import tkinterdnd2' fail
        import customtkinter as ctk, app_modern
        root = ctk.CTk(); root.withdraw()
        window = app_modern.ModernApp(root)
        for _ in range(30):
            root.update(); root.after(10)
        print("dnd=" + str(window.dnd))
        window.close()
    """)
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                          timeout=120)
    if proc.returncode != 0 and "display" in proc.stderr.lower():
        pytest.skip(f"no display available: {proc.stderr.strip()}")
    return proc


@pytest.mark.parametrize("block_dnd", [False, True], ids=["with_dnd", "without_tkinterdnd2"])
def test_window_create_and_destroy_leaves_stderr_empty(block_dnd):
    proc = run_window_in_subprocess(block_dnd)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""  # no 'invalid command name ...' from CTk timers, no warnings
    if block_dnd:
        assert "dnd=False" in proc.stdout  # app still starts; Browse buttons are the way in


@pytest.fixture
def gui(monkeypatch):
    try:
        root = ctk.CTk()
    except Exception as exc:  # tkinter.TclError
        if "display" not in str(exc).lower():
            raise  # a real Tk problem must fail the test, not hide as a skip
        pytest.skip(f"no display available: {exc}")
    root.withdraw()
    boxes = []
    for kind in ("showerror", "showinfo"):
        monkeypatch.setattr(app_modern.messagebox, kind,
                            lambda title, text, kind=kind, **kw: boxes.append((kind, title, text)))
    window = app_modern.ModernApp(root)
    root.update()
    yield window, boxes
    window.close()


def pump(window, until, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        window.root.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("GUI did not finish in time")


def finished(window):
    return lambda: not window.worker.busy and window.worker.events.empty() \
        and str(window.encode_btn.cget("state")) == "normal"


def shown_image(label):
    """What the inner tk label really shows ('' = nothing)."""
    return str(label._label.cget("image"))


def test_window_builds(gui):
    window, boxes = gui
    assert window.root.title() == "LSB Steganography - Modern"
    assert window.mode() == "image"
    assert all(str(b.cget("state")) == "normal" for b in window.buttons if b is not window.measure_btn)
    assert str(window.measure_btn.cget("state")) == "disabled"  # nothing encoded yet
    assert isinstance(window.dnd, bool)
    assert boxes == []


def test_window_fits_screen_and_content_fits_window(gui):
    """All in physical pixels. Measured bug this guards against: at 125 % the first
    version was 1393x997 px with 964 px of content in a 950 px window, and its
    bottom edge was below the screen."""
    window, boxes = gui
    root = window.root
    root.update()
    scale = ctk.ScalingTracker.get_window_scaling(root)
    w, h, x, y = window.window_box
    left, top, work_w, work_h = app_modern.screen_work_area(root)
    assert root.winfo_reqwidth() <= round(w * scale)
    assert root.winfo_reqheight() <= round(h * scale)
    assert x >= left and y >= top
    assert x + round(w * scale) + 18 <= left + work_w  # 18 x 47 = border and title bar
    assert y + round(h * scale) + 47 <= top + work_h


def test_validation_error_shows_box_and_keeps_buttons_enabled(gui):
    window, boxes = gui
    window.start_encode()
    assert boxes == [("showerror", "Check your input", "Please choose a cover file first.")]
    assert str(window.encode_btn.cget("state")) == "normal"


def test_image_flow_capacity_bar_encode_decode_difference_measure(gui, tmp_path):
    window, boxes = gui
    cover = tmp_path / "cover photo é.png"
    Image.fromarray(np.random.default_rng(1).integers(0, 256, (60, 80, 3), dtype=np.uint8)).save(cover)
    window.select_cover(str(cover))
    pump(window, finished(window))
    capacity = (60 * 80 * 3 - 104) // 8
    assert window.capacity == capacity

    message = "Meet at 7 pm\nनमस्ते 😀"
    window.message_box.insert("1.0", message)
    window.on_message_change()
    size = len(message.encode("utf-8"))
    assert window.capacity_bar.get() == pytest.approx(size / capacity)
    assert window.capacity_bar.cget("progress_color") == app_modern.BAR_OK

    window.start_encode()
    assert str(window.encode_btn.cget("state")) == "disabled"  # busy
    pump(window, finished(window))
    assert boxes[-1][:2] == ("showinfo", "Done")
    assert str(window.measure_btn.cget("state")) == "normal"
    assert shown_image(window.preview_labels["Stego"]) != ""

    window.diff_switch.select()
    window.on_diff_toggle()
    pump(window, finished(window))
    assert window._images["Stego"].cget("size") == (80, 60)  # the 1:1 crop, not the preview
    window.diff_switch.deselect()
    window.on_diff_toggle()
    assert window._images["Stego"].cget("size") == window._stego_preview.size

    window.start_measure()
    pump(window, finished(window))
    text = window.metrics_box.get("1.0", "end-1c")
    assert "PSNR (R, G, B values only)" in text and "not a general rule" in text
    assert window.tabs.get() == "Results / About"

    window.start_decode()
    pump(window, finished(window))
    assert window.result_text == message
    assert window.result_box.get("1.0", "end-1c") == message


def test_over_capacity_turns_bar_red(gui, tmp_path):
    window, boxes = gui
    cover = tmp_path / "tiny.png"
    Image.fromarray(np.zeros((10, 10, 3), np.uint8)).save(cover)  # capacity (300-104)//8 = 24
    window.select_cover(str(cover))
    pump(window, finished(window))
    window.message_box.insert("1.0", "x" * 25)
    window.on_message_change()
    assert window.capacity_bar.get() == 1.0
    assert window.capacity_bar.cget("progress_color") == app_modern.BAR_OVER
    assert "TOO LONG by 1 bytes" in window.size_label.cget("text")
    window.start_encode()
    pump(window, finished(window))
    assert boxes[-1][:2] == ("showerror", "Message too long")


def test_mode_change_really_clears_previews(gui, tmp_path):
    window, boxes = gui
    cover = tmp_path / "c.png"
    Image.fromarray(np.zeros((20, 20, 3), np.uint8)).save(cover)
    window.select_cover(str(cover))
    pump(window, finished(window))
    assert shown_image(window.preview_labels["Cover"]) != ""
    window.mode_button.set("Video")
    window.on_mode_change()
    assert shown_image(window.preview_labels["Cover"]) == ""  # CTk ignores image=None
    assert window.cover.get() == "" and window.capacity is None


def test_engine_error_is_friendly_and_buttons_come_back(gui, tmp_path):
    window, boxes = gui
    clean = tmp_path / "clean.png"
    Image.fromarray(np.zeros((40, 40, 3), np.uint8)).save(clean)
    window.stego.set(str(clean))
    window.start_decode()
    pump(window, finished(window))
    assert boxes[-1][:2] == ("showerror", "No hidden message")
    assert str(window.decode_btn.cget("state")) == "normal"


def test_drop_of_two_files_is_refused(gui):
    window, boxes = gui

    class Event:
        data = "{C:/a b.png} C:/c.png"
        action = "copy"

    window.on_drop("cover", Event())
    assert boxes[-1] == ("showerror", "Check your input", "Please drop exactly one file.")


def test_huge_single_line_message_does_not_freeze(gui, tmp_path):
    window, boxes = gui
    txt = tmp_path / "huge.txt"
    txt.write_text("x" * 1_000_000, encoding="utf-8")
    start = time.perf_counter()
    window.load_message_file(str(txt))
    window.root.update()
    assert time.perf_counter() - start < 5
    assert window.message() == "x" * 1_000_000
    start = time.perf_counter()
    window.set_result("y" * 1_000_000)
    window.root.update()
    assert time.perf_counter() - start < 5
    assert window.result_text == "y" * 1_000_000
    assert boxes[-1][:2] == ("showinfo", "Long message")
