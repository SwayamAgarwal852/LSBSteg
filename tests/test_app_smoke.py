"""Smoke tests for app.py: build the real Tk window, drive it from code, destroy it.

Message boxes are replaced by recorders so nothing blocks. This proves the
wiring (validation -> worker thread -> queue -> widgets); it is NOT a
replacement for clicking through GUI_CHECKLIST.md by hand.
"""

import time
import tkinter as tk

import numpy as np
import pytest
from PIL import Image

import app


@pytest.fixture
def gui(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        if "display" not in str(exc).lower():
            raise  # a real Tk problem must fail the test, not hide as a skip
        pytest.skip(f"no display available: {exc}")
    root.withdraw()  # do not flash a window during tests
    boxes = []
    for kind in ("showerror", "showinfo"):
        monkeypatch.setattr(app.messagebox, kind,
                            lambda title, text, kind=kind, **kw: boxes.append((kind, title, text)))
    window = app.StegoApp(root)
    root.update()
    yield window, boxes
    window.close()


def pump(window, until, timeout=60):
    """Run the Tk event loop until `until()` is true (the worker finished)."""
    end = time.time() + timeout
    while time.time() < end:
        window.root.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("GUI did not finish in time")


def finished(window):
    return lambda: not window.worker.busy and window.worker.events.empty() \
        and str(window.encode_btn["state"]) == "normal"


def test_window_builds_and_closes(gui):
    window, boxes = gui
    assert window.root.title() == "LSB Steganography - Image and Video"
    assert window.mode.get() == "image"
    assert all(str(b["state"]) == "normal" for b in window.buttons)
    assert boxes == []


def test_validation_error_shows_box_and_keeps_buttons_enabled(gui):
    window, boxes = gui
    window.start_encode()  # nothing chosen
    assert boxes == [("showerror", "Check your input", "Please choose a cover file first.")]
    assert all(str(b["state"]) == "normal" for b in window.buttons)


def test_image_encode_decode_through_the_gui(gui, tmp_path):
    window, boxes = gui
    cover = tmp_path / "cover photo é.png"
    Image.fromarray(np.random.default_rng(1).integers(0, 256, (60, 80, 3), dtype=np.uint8)).save(cover)
    window.select_cover(str(cover))
    pump(window, finished(window))
    assert window.capacity == (60 * 80 * 3 - 104) // 8
    assert "2-4 bytes each" in window.capacity_label.get()

    message = "Meet at 7 pm\nनमस्ते 😀\ttab"
    window.message_box.insert("1.0", message)
    window.start_encode()
    assert all(str(b["state"]) == "disabled" for b in window.buttons)  # busy
    pump(window, finished(window))
    assert boxes[-1][:2] == ("showinfo", "Done")
    assert window.stego.get().endswith("cover photo é_stego.png")

    window.start_decode()
    pump(window, finished(window))
    assert window.result_text == message
    assert window.result_box.get("1.0", "end-1c") == message  # exact text in the box
    assert "_photos" in vars(window) and set(window._photos) == {"Cover", "Stego"}


def test_engine_error_is_friendly_and_buttons_come_back(gui, tmp_path):
    window, boxes = gui
    clean = tmp_path / "clean.png"
    Image.fromarray(np.zeros((40, 40, 3), np.uint8)).save(clean)
    window.stego.set(str(clean))
    window.start_decode()
    pump(window, finished(window))
    assert boxes[-1][:2] == ("showerror", "No hidden message")
    assert all(str(b["state"]) == "normal" for b in window.buttons)


def test_unexpected_error_in_callback_is_one_line(gui):
    window, boxes = gui
    window.root.report_callback_exception(KeyError, KeyError("boom"), None)
    assert boxes[-1] == ("showerror", "Unexpected error", "Unexpected error: KeyError: 'boom'")


def test_huge_single_line_message_does_not_freeze(gui, tmp_path):
    window, boxes = gui
    txt = tmp_path / "huge.txt"
    txt.write_text("x" * 1_000_000, encoding="utf-8")
    start = time.perf_counter()
    window.load_message_file(str(txt))
    window.root.update()
    assert time.perf_counter() - start < 5
    assert window.message() == "x" * 1_000_000  # full text kept for encoding
    start = time.perf_counter()
    window.set_result("y" * 1_000_000)
    window.root.update()
    assert time.perf_counter() - start < 5
    assert window.result_text == "y" * 1_000_000
    assert boxes[-1][:2] == ("showinfo", "Long message")
