"""Tests for gui_logic.py: everything the GUI does that needs no window (SP7)."""

import shutil
import subprocess
import time

import numpy as np
import pytest
from PIL import Image

import gui_logic as logic
from errors import (
    CapacityError,
    CorruptedDataError,
    EmptyMessageError,
    FFmpegError,
    FFmpegNotFoundError,
    NoHiddenMessageError,
    UnsupportedFormatError,
)
from gui_logic import IMAGE, VIDEO, InputError

HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "cover.png"
    Image.fromarray(np.random.default_rng(0).integers(0, 256, (60, 80, 3), dtype=np.uint8)).save(path)
    return path


@pytest.fixture
def clip(tmp_path):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=25:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


# ---------------------------------------------------------------- validation

def test_no_cover(tmp_path):
    with pytest.raises(InputError, match="choose a cover"):
        logic.validate_encode(IMAGE, "", "hi", str(tmp_path / "o.png"))


def test_cover_does_not_exist(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        logic.validate_encode(IMAGE, str(tmp_path / "missing.png"), "hi", str(tmp_path / "o.png"))


def test_mode_and_file_type_must_agree(png, clip):
    with pytest.raises(InputError, match="Video mode"):
        logic.validate_cover(IMAGE, str(clip))
    with pytest.raises(InputError, match="Image mode"):
        logic.validate_cover(VIDEO, str(png))


def test_empty_message(png):
    with pytest.raises(InputError, match="empty"):
        logic.validate_encode(IMAGE, str(png), "", str(png.with_name("o.png")))


def test_whitespace_message_is_allowed(png):
    logic.validate_encode(IMAGE, str(png), " ", str(png.with_name("o.png")))


def test_no_output(png):
    with pytest.raises(InputError, match="where to save"):
        logic.validate_encode(IMAGE, str(png), "hi", "")


@pytest.mark.parametrize("mode, cover_fixture, bad_output, expected",
                         [(IMAGE, "png", "o.jpg", r"\.png"), (VIDEO, "clip", "o.mp4", r"\.mkv")])
def test_wrong_output_extension(request, mode, cover_fixture, bad_output, expected):
    cover = request.getfixturevalue(cover_fixture)
    with pytest.raises(InputError, match=expected):
        logic.validate_encode(mode, str(cover), "hi", str(cover.with_name(bad_output)))


def test_output_equal_to_cover(png):
    with pytest.raises(InputError, match="different from the cover"):
        logic.validate_encode(IMAGE, str(png), "hi", str(png))


def test_output_folder_missing(png):
    with pytest.raises(InputError, match="does not exist"):
        logic.validate_encode(IMAGE, str(png), "hi", str(png.parent / "nope" / "o.png"))


def test_valid_encode_and_decode_input(png):
    cover, output = logic.validate_encode(IMAGE, str(png), "hi", str(png.with_name("o.PNG")))
    assert cover == png and output.name == "o.PNG"
    assert logic.validate_decode(IMAGE, str(png)) == png
    with pytest.raises(InputError, match="file to decode"):
        logic.validate_decode(IMAGE, "")


def test_default_output_path():
    assert logic.default_output_path(IMAGE, r"C:\a b\photo.jpg").endswith("photo_stego.png")
    assert logic.default_output_path(VIDEO, r"C:\a b\clip.mp4").endswith("clip_stego.mkv")


# ---------------------------------------------------------------- texts

def test_capacity_text():
    text = logic.capacity_text(3737)
    assert "3,737 bytes" in text and "2-4 bytes each" in text


def test_format_seconds():
    assert logic.format_seconds(0.0042) == "4 ms"
    assert logic.format_seconds(0.85) == "850 ms"
    assert logic.format_seconds(2.314) == "2.31 s"


def test_message_size_text_counts_utf8_bytes():
    assert "2 characters = 6 bytes" in logic.message_size_text("नम", 100)
    assert "TOO LONG by 2 bytes" in logic.message_size_text("x" * 12, 10)
    assert "capacity" not in logic.message_size_text("hi", None)


def test_image_notes(png, tmp_path):
    assert len(logic.image_notes(png)) == 1 and "JPEG" in logic.image_notes(png)[0]
    jpg = tmp_path / "c.jpg"
    Image.open(png).save(jpg)
    assert any("cover is a JPEG" in n for n in logic.image_notes(jpg))
    pal = tmp_path / "p.png"
    Image.open(png).convert("P").save(pal)
    assert any("Palette" in n for n in logic.image_notes(pal))


@pytest.mark.parametrize("w, h, frames, rate, warned", [
    (640, 480, 250, "25/1", False),        # exactly 10 s, exactly 640x480: no warning
    (640, 480, 251, "25/1", True),         # 10.04 s
    (1280, 720, 25, "25/1", True),         # more pixels than 640x480
    (320, 240, 299, "30000/1001", False),  # 299 * 1001 / 30000 = 9.977 s
    (320, 240, 300, "30000/1001", True),   # 300 * 1001 / 30000 = 10.01 s
    (160, 120, 10, "0/0", False),          # unknown rate must not crash
])
def test_video_notes(w, h, frames, rate, warned):
    notes = logic.video_notes(w, h, frames, rate)
    assert any(n.startswith("Large video") for n in notes) == warned
    assert any("MP4" in n and "social media" in n and "messaging" in n for n in notes)


# ---------------------------------------------------------------- friendly messages

@pytest.mark.parametrize("exc, title", [
    (InputError("x"), "Check your input"),
    (CapacityError("x"), "Message too long"),
    (NoHiddenMessageError("x"), "No hidden message"),
    (CorruptedDataError("x"), "Data corrupted"),
    (UnsupportedFormatError("x"), "Unsupported file"),
    (FFmpegNotFoundError("x"), "FFmpeg missing"),
    (FFmpegError("x"), "Video processing failed"),
    (EmptyMessageError("x"), "Nothing to hide"),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), "Not UTF-8 text"),
    (PermissionError(13, "denied", "C:/x.png"), "Permission denied"),
    (FileNotFoundError(2, "missing", "C:/x.png"), "File not found"),
])
def test_friendly_titles(exc, title):
    assert logic.friendly_message(exc)[0] == title


def test_unexpected_error_is_one_line():
    title, text = logic.friendly_message(ValueError("first line\nsecond line\nTraceback..."))
    assert title == "Unexpected error"
    assert text == "Unexpected error: ValueError: first line"


def test_ffmpeg_error_shows_first_line_only():
    _, text = logic.friendly_message(FFmpegError("ffmpeg stopped\n[long log]\nmore"))
    assert text == "ffmpeg stopped"


# ---------------------------------------------------------------- long text

def test_display_text_exact_when_safe():
    text = "line\n" * 100_000  # 500,000 characters but short lines
    assert logic.display_text(text) == (text, None)
    assert logic.display_text("😀 नमस्ते") == ("😀 नमस्ते", None)


def test_display_text_previews_very_long_line():
    text = "x" * 1_000_000
    shown, note = logic.display_text(text)
    assert shown == text[:5000] and "Copy result" in note


def test_read_text_file(tmp_path):
    f = tmp_path / "m.txt"
    f.write_bytes("\ufeffनमस्ते 😀\r\nline 2".encode("utf-8"))  # Notepad-style BOM + CRLF
    assert logic.read_text_file(f) == "नमस्ते 😀\nline 2"
    bad = tmp_path / "bad.txt"
    bad.write_bytes("café".encode("cp1252"))
    with pytest.raises(UnicodeDecodeError):
        logic.read_text_file(bad)


# ---------------------------------------------------------------- worker

def wait_for_events(worker, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        events = worker.poll()
        if events:
            return events
        time.sleep(0.01)
    raise AssertionError("worker produced no event")


def test_worker_success_and_error_go_through_queue(capsys):
    worker = logic.Worker()
    worker.start("job", lambda a, b: a + b, 2, 3)
    assert wait_for_events(worker) == [("ok", "job", 5)]
    worker.start("job", lambda: 1 / 0)
    [(status, job, exc)] = wait_for_events(worker)
    assert status == "error" and isinstance(exc, ZeroDivisionError)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""  # nothing printed to the console


def test_worker_runs_one_job_at_a_time():
    worker = logic.Worker()
    worker.start("slow", time.sleep, 0.5)
    assert worker.busy
    with pytest.raises(InputError, match="wait"):
        worker.start("other", print)
    wait_for_events(worker)
    assert not worker.busy


# ---------------------------------------------------------------- jobs

def test_image_jobs_round_trip(png, tmp_path):
    report = logic.analyse_cover(IMAGE, png)
    assert report.capacity == (60 * 80 * 3 - 104) // 8
    assert report.preview.size[0] <= 320 and report.preview.size[1] <= 240
    message = "नमस्ते 😀 secret"
    enc = logic.run_encode(IMAGE, png, message, tmp_path / "out.png")
    assert enc.output.exists() and enc.seconds > 0
    dec = logic.run_decode(IMAGE, enc.output)
    assert dec.text == message


def test_video_jobs_round_trip(clip, tmp_path):
    report = logic.analyse_cover(VIDEO, clip)
    assert report.capacity == (25 * 160 * 120 * 3 - 104) // 8
    assert report.preview.size == (160, 120)
    enc = logic.run_encode(VIDEO, clip, "video secret", tmp_path / "out.mkv")
    assert logic.run_decode(VIDEO, enc.output).text == "video secret"
