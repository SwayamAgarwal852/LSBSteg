"""Everything the GUI needs that does NOT touch widgets, so it can be tested
without opening a window: validation, friendly error messages, capacity and
warning texts, previews, the three background jobs and the worker thread.

app.py only builds widgets and calls into this module.
"""

import io
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image

from decoder import decode_image, decode_video
from encoder import encode_image, encode_video, image_capacity_bytes, video_capacity_bytes
from errors import (
    CapacityError,
    CorruptedDataError,
    EmptyMessageError,
    FFmpegError,
    FFmpegNotFoundError,
    NoHiddenMessageError,
    UnsupportedFormatError,
)
from image_utils import carrier_bytes, load_image
from metrics import format_psnr, mse, percent_used, psnr, summarize_frame_mses, video_frame_mses
from video_utils import FrameReader, find_tool, probe_video

IMAGE, VIDEO = "image", "video"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}
OUTPUT_EXTENSION = {IMAGE: ".png", VIDEO: ".mkv"}
PREVIEW_SIZE = (320, 240)
# Tk's Text widget freezes on very long single lines (measured: 1,000,000
# characters on one line did not finish within 60 s), so longer lines are
# only previewed; Copy/Save always use the full text.
MAX_DISPLAY_LINE = 20_000
PREVIEW_CHARS = 5_000
LONG_VIDEO_SECONDS = 10  # A10
LARGE_VIDEO_PIXELS = 640 * 480  # A10


class InputError(Exception):
    """The user's input is incomplete or inconsistent (checked before any work)."""


# ---------------------------------------------------------------- validation

def validate_cover(mode: str, cover: str) -> Path:
    if not cover:
        raise InputError("Please choose a cover file first.")
    path = Path(cover)
    if not path.is_file():
        raise InputError(f"The file '{path.name}' does not exist.")
    is_image = path.suffix.lower() in IMAGE_EXTENSIONS
    if mode == IMAGE and not is_image:
        raise InputError("Image mode accepts PNG, JPEG or BMP files. "
                         "For a video, switch to Video mode.")
    if mode == VIDEO and is_image:
        raise InputError("This looks like an image. Switch to Image mode.")
    return path


def validate_encode(mode: str, cover: str, message: str, output: str) -> tuple[Path, Path]:
    """Check everything before encoding; return (cover_path, output_path)."""
    cover_path = validate_cover(mode, cover)
    if message == "":
        raise InputError("The message is empty - there is nothing to hide.")
    if not output:
        raise InputError("Please choose where to save the output file.")
    output_path = Path(output)
    expected = OUTPUT_EXTENSION[mode]
    if output_path.suffix.lower() != expected:
        raise InputError(f"The output file must end in {expected} "
                         f"({'lossless PNG' if mode == IMAGE else 'lossless FFV1 MKV'}).")
    if output_path.resolve() == cover_path.resolve():
        raise InputError("The output file must be different from the cover file.")
    if not output_path.parent.is_dir():
        raise InputError(f"The folder '{output_path.parent}' does not exist.")
    return cover_path, output_path


def validate_decode(mode: str, stego: str) -> Path:
    if not stego:
        raise InputError("Please choose the file to decode first.")
    return validate_cover(mode, stego)


def default_output_path(mode: str, cover: str) -> str:
    """Suggest '<cover name>_stego.png/.mkv' next to the cover."""
    path = Path(cover)
    return str(path.with_name(path.stem + "_stego" + OUTPUT_EXTENSION[mode]))


# ---------------------------------------------------------------- texts

def capacity_text(capacity: int) -> str:
    return (f"Capacity: up to {capacity:,} bytes "
            f"({capacity:,} English characters; non-English characters use 2-4 bytes each)")


def format_seconds(seconds: float) -> str:
    """'850 ms' below one second, '2.31 s' above (so fast jobs never show '0.00 s')."""
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.2f} s"


def message_size_text(message: str, capacity: int | None) -> str:
    size = len(message.encode("utf-8"))
    text = f"Message: {len(message):,} characters = {size:,} bytes (UTF-8)"
    if capacity:
        text += f", {100 * size / capacity:.1f}% of capacity"
        if size > capacity:
            text += f" - TOO LONG by {size - capacity:,} bytes"
    return text


def image_notes(path: Path) -> list[str]:
    notes = ["Output is a PNG file. Do not re-save, edit or convert it to JPEG: "
             "that destroys the hidden message."]
    with Image.open(path) as img:
        fmt, mode = img.format, img.mode
    if fmt == "JPEG":
        notes.append("The cover is a JPEG: it is only read; the result is saved as PNG.")
    if mode in ("P", "PA"):
        notes.append("Palette image: it will be converted to true colour (RGB/RGBA) first.")
    return notes


def video_notes(width: int, height: int, frame_count: int, frame_rate: str) -> list[str]:
    notes = []
    rate = 0 if frame_rate.endswith("/0") else Fraction(frame_rate)  # ffprobe "0/0" = unknown
    seconds = frame_count / rate if rate else 0
    if seconds > LONG_VIDEO_SECONDS or width * height > LARGE_VIDEO_PIXELS:
        notes.append(f"Large video ({width}x{height}, {float(seconds):.1f} s): encoding may be "
                     "slow. Short clips of up to 10 s at 640x480 are recommended.")
    notes.append("The output MKV (lossless) is much larger than the input. Converting it to "
                 "MP4, uploading it to social media or sending it through messaging apps "
                 "re-compresses it and destroys the hidden message.")
    return notes


def friendly_message(exc: BaseException) -> tuple[str, str]:
    """(title, text) for a message box. Never shows a traceback."""
    first_line = (str(exc).strip().splitlines() or [""])[0]
    if isinstance(exc, InputError):
        return "Check your input", str(exc)
    if isinstance(exc, CapacityError):
        return "Message too long", f"{exc}\n\nShorten the message or use a larger cover."
    if isinstance(exc, NoHiddenMessageError):
        return "No hidden message", ("No hidden message was found in this file. It was not "
                                     "made by this tool, or the wrong mode is selected.")
    if isinstance(exc, CorruptedDataError):
        return "Data corrupted", (f"{exc}\n\nThe file was probably edited, re-saved or "
                                  "re-compressed after the message was hidden.")
    if isinstance(exc, UnsupportedFormatError):
        return "Unsupported file", str(exc)
    if isinstance(exc, FFmpegNotFoundError):
        return "FFmpeg missing", str(exc)
    if isinstance(exc, FFmpegError):
        return "Video processing failed", first_line
    if isinstance(exc, EmptyMessageError):
        return "Nothing to hide", str(exc)
    if isinstance(exc, UnicodeDecodeError):
        return "Not UTF-8 text", "The text file is not UTF-8. Save it as UTF-8 and try again."
    if isinstance(exc, PermissionError):
        return "Permission denied", f"Cannot read or write the file:\n{exc.filename or first_line}"
    if isinstance(exc, FileNotFoundError):
        return "File not found", f"The file was not found:\n{exc.filename or first_line}"
    return "Unexpected error", f"Unexpected error: {type(exc).__name__}: {first_line}"


# ---------------------------------------------------------------- long text

def is_safe_to_display(text: str) -> bool:
    """True if no line is long enough to freeze the Tk Text widget."""
    return max((len(line) for line in text.split("\n")), default=0) <= MAX_DISPLAY_LINE


def display_text(text: str) -> tuple[str, str | None]:
    """(text for the widget, note or None). Exact text whenever it is safe."""
    if is_safe_to_display(text):
        return text, None
    note = (f"This message is {len(text):,} characters long with very long lines, which "
            f"would freeze the window. Showing only the first {PREVIEW_CHARS:,} characters. "
            "Use 'Copy result' or 'Save result...' to get the full, exact text.")
    return text[:PREVIEW_CHARS], note


def read_text_file(path) -> str:
    """Read a UTF-8 .txt file (a UTF-8 BOM from Notepad is removed)."""
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


# ---------------------------------------------------------------- previews

def preview_image(mode: str, path: Path) -> Image.Image:
    """Small RGB(A) picture for the preview panel (first frame for video)."""
    if mode == IMAGE:
        with Image.open(path) as img:
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    else:
        cmd = [find_tool("ffmpeg"), "-v", "error", "-noautorotate", "-i", str(path),
               "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"]
        data = subprocess.run(cmd, capture_output=True, check=True).stdout
        img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail(PREVIEW_SIZE)
    return img


# ---------------------------------------------------------------- jobs (run in the worker)

@dataclass
class CoverReport:
    capacity: int
    notes: list[str] = field(default_factory=list)
    preview: Image.Image | None = None


@dataclass
class EncodeReport:
    output: Path
    seconds: float
    preview: Image.Image | None = None


@dataclass
class DecodeReport:
    text: str
    seconds: float
    preview: Image.Image | None = None


def analyse_cover(mode: str, path: Path) -> CoverReport:
    if mode == IMAGE:
        return CoverReport(image_capacity_bytes(path), image_notes(path), preview_image(mode, path))
    info = probe_video(path)
    return CoverReport(video_capacity_bytes(path),
                       video_notes(info.width, info.height, info.frame_count, info.frame_rate),
                       preview_image(mode, path))


def run_encode(mode: str, cover: Path, message: str, output: Path) -> EncodeReport:
    start = time.perf_counter()
    if mode == IMAGE:
        encode_image(cover, message, output)
    else:
        encode_video(cover, message, output)
    return EncodeReport(output, time.perf_counter() - start, preview_image(mode, output))


def run_decode(mode: str, path: Path) -> DecodeReport:
    start = time.perf_counter()
    text = decode_image(path) if mode == IMAGE else decode_video(path)
    return DecodeReport(text, time.perf_counter() - start, preview_image(mode, path))


# ---------------------------------------------------------------- worker thread

class Worker:
    """Runs one job at a time in a background thread.

    The thread NEVER touches widgets: it only puts ("ok", job, result) or
    ("error", job, exception) into a queue. The main thread reads the queue
    with poll() (called from root.after) and updates the widgets itself,
    because Tkinter is not thread-safe.
    """

    def __init__(self):
        self.events = queue.Queue()
        self._thread = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, job: str, func, *args) -> None:
        if self.busy:
            raise InputError("Please wait until the current task has finished.")
        self._thread = threading.Thread(target=self._run, args=(job, func, args), daemon=True)
        self._thread.start()

    def _run(self, job, func, args):
        try:
            self.events.put(("ok", job, func(*args)))
        except Exception as exc:  # every error goes to the main thread, none is printed
            self.events.put(("error", job, exc))

    def poll(self) -> list[tuple]:
        """All finished events so far (non-blocking; main thread only)."""
        found = []
        while True:
            try:
                found.append(self.events.get_nowait())
            except queue.Empty:
                return found


# ---------------------------------------------------------------- modern window helpers
# Used by app_modern.py (the classic app.py does not need them).

DIFF_CROP = (320, 240)  # (width, height) of the 1:1 difference view
TINY_PAYLOAD_PERCENT = 1.0  # below this, warn that PSNR is very high


@dataclass
class CapacityUsage:
    size: int  # message size in UTF-8 bytes
    fraction: float  # for the bar: size / capacity, at most 1.0
    over: bool  # True if the message does not fit


def capacity_usage(message: str, capacity: int | None) -> CapacityUsage | None:
    """Values for the live capacity bar; None until a cover was analysed."""
    if not capacity:
        return None
    size = len(message.encode("utf-8"))
    return CapacityUsage(size, min(size / capacity, 1.0), size > capacity)


def dropped_file(paths) -> str:
    """The single path from a drag-and-drop event (already split into a list)."""
    paths = [p for p in paths if p]
    if len(paths) != 1:
        raise InputError("Please drop exactly one file.")
    return paths[0]


def _first_frame_pixels(mode: str, path: Path) -> np.ndarray:
    """Pixels exactly as the encoder sees them (image, or first video frame)."""
    if mode == IMAGE:
        return load_image(path)
    with FrameReader(path, probe_video(path)) as reader:
        return next(iter(reader)).copy()


def _carrier_part(pixels: np.ndarray) -> np.ndarray:
    """Only the channels that carry bits: grey for L/LA, R,G,B otherwise."""
    if pixels.ndim == 2:
        return pixels
    return pixels[..., 0] if pixels.shape[2] == 2 else pixels[..., :3]


def difference_crop(mode: str, cover: Path, stego: Path, size=DIFF_CROP) -> Image.Image:
    """|cover - stego| x 255 for the top-left corner, at 1:1 (no resampling).

    The message is written from the top-left pixel on, so this is where the
    changes are. A shrunken whole image would average the 0/1 pattern into
    grey (seen in Phase 4), which is why we crop instead of scaling.
    """
    c = _carrier_part(_first_frame_pixels(mode, cover))
    s = _carrier_part(_first_frame_pixels(mode, stego))
    if c.shape != s.shape:
        raise InputError("The cover and the stego file have different sizes.")
    w, h = size
    diff = (c[:h, :w] != s[:h, :w]).astype(np.uint8) * 255
    return Image.fromarray(diff)


@dataclass
class QualityReport:
    mode: str
    mse: float  # image: over R,G,B (or grey); video: pooled over all frames
    psnr: float
    payload_bytes: int
    capacity: int
    encode_seconds: float
    frames_total: int = 0  # video only
    frames_modified: int = 0
    mean_psnr_modified: float = 0.0


def measure_quality(mode: str, cover: Path, stego: Path, payload_bytes: int,
                    capacity: int, encode_seconds: float) -> QualityReport:
    """MSE/PSNR between cover and stego with metrics.py (runs in the worker)."""
    if mode == IMAGE:
        m = mse(carrier_bytes(load_image(cover)), carrier_bytes(load_image(stego)))
        return QualityReport(mode, m, psnr(m), payload_bytes, capacity, encode_seconds)
    frame_mses = video_frame_mses(cover, stego)
    summary = summarize_frame_mses(frame_mses)
    pooled = sum(frame_mses) / len(frame_mses)
    return QualityReport(mode, pooled, summary["pooled_psnr"], payload_bytes, capacity,
                         encode_seconds, summary["frames_total"], summary["frames_modified"],
                         summary["mean_psnr_modified"])


def quality_lines(r: QualityReport) -> list[str]:
    """Labelled text for the metrics panel."""
    used = percent_used(r.payload_bytes, r.capacity)
    lines = ["Measured for this cover and this message only (not a general rule)."]
    if r.mode == IMAGE:
        lines += [f"MSE (R, G, B values only; alpha not included): {r.mse:.6f}",
                  f"PSNR (R, G, B values only): {format_psnr(r.psnr)}"]
    else:
        lines += [f"MSE pooled over all {r.frames_total:,} frames: {r.mse:.6f}",
                  f"PSNR pooled over all {r.frames_total:,} frames: {format_psnr(r.psnr)}"]
        if r.frames_modified:
            lines.append(f"PSNR mean over the {r.frames_modified:,} modified frames only: "
                         f"{format_psnr(r.mean_psnr_modified)}")
        else:
            lines.append("No frame was changed (every hidden bit already matched).")
    lines += [f"Encode time: {format_seconds(r.encode_seconds)}",
              f"Capacity used: {used:.2f}% ({r.payload_bytes:,} of {r.capacity:,} message bytes; "
              "the 13-byte header is not counted)"]
    if used < TINY_PAYLOAD_PERCENT:
        lines.append(f"Note: the message uses less than {TINY_PAYLOAD_PERCENT:g}% of the capacity, "
                     "so very few values changed and the PSNR is very high.")
    return lines
