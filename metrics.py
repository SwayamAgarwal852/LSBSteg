"""Quality and performance metrics: MSE, PSNR, capacity, timing, exact match.

PSNR (peak signal-to-noise ratio) compares cover and stego:
    MSE  = mean of (cover - stego)^2 over all compared bytes
    PSNR = 10 * log10(255^2 / MSE)  in dB; higher = more similar
MSE = 0 means the two are identical; PSNR is then infinite.
"""

import math
import time

import numpy as np

from header import max_payload_bytes
from video_utils import FrameReader, probe_video

MAX_PIXEL = 255


# ---------------------------------------------------------------- MSE / PSNR

def mse(cover: np.ndarray, stego: np.ndarray) -> float:
    """Mean squared error between two uint8 arrays of the same shape."""
    if cover.shape != stego.shape:
        raise ValueError(f"Shapes differ: {cover.shape} vs {stego.shape}.")
    # Convert BEFORE subtracting: in uint8, 0 - 255 would wrap around to 1.
    diff = cover.astype(np.float64) - stego.astype(np.float64)
    return float(np.mean(diff * diff))


def psnr(mse_value: float) -> float:
    """PSNR in dB from an MSE value; math.inf when MSE is 0 (identical)."""
    if mse_value == 0:
        return math.inf  # no division by zero: identical images
    return 10 * math.log10(MAX_PIXEL ** 2 / mse_value)


def format_psnr(value: float) -> str:
    """Human-readable PSNR, e.g. '51.14 dB' or 'identical (inf dB)'."""
    return "identical (inf dB)" if math.isinf(value) else f"{value:.2f} dB"


# ---------------------------------------------------------------- capacity / match

def capacity_bytes(usable_bytes: int) -> int:
    """Max message bytes for a cover with this many carrier bytes."""
    return max_payload_bytes(usable_bytes)


def percent_used(payload_bytes: int, capacity: int) -> float:
    """How full the cover is, in percent of its message capacity."""
    return 100.0 * payload_bytes / capacity if capacity else math.inf


def exact_match(original: str, recovered: str) -> bool:
    """True only if the recovered message is character-for-character identical."""
    return original == recovered


# ---------------------------------------------------------------- timing

class Timer:
    """Measure wall-clock time of a block with time.perf_counter (A13).

        with Timer() as t:
            work()
        print(t.seconds)
    """

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self._start


# ---------------------------------------------------------------- video

def summarize_frame_mses(frame_mses, payload_frames: int | None = None) -> dict:
    """Turn per-frame MSE values into the two video PSNR figures.

    mean_psnr_modified: average PSNR of frames that actually changed
        (MSE > 0). Unchanged frames are left out, because their PSNR is
        infinite and would make any average infinite.
    pooled_psnr: PSNR of the average MSE over ALL frames (unchanged frames
        count as MSE 0). All frames have the same size, so this equals the
        PSNR of the whole video treated as one big array.
    """
    frame_mses = list(frame_mses)
    changed = [m for m in frame_mses if m > 0]
    mean_modified = (sum(psnr(m) for m in changed) / len(changed)) if changed else math.inf
    pooled = psnr(sum(frame_mses) / len(frame_mses)) if frame_mses else math.inf
    return {
        "frames_total": len(frame_mses),
        "frames_with_payload": payload_frames,
        "frames_modified": len(changed),
        "mean_psnr_modified": mean_modified,
        "pooled_psnr": pooled,
    }


def video_frame_mses(cover_path, stego_path) -> list[float]:
    """Per-frame MSE between the cover's decoded RGB frames and the stego frames."""
    cover_info, stego_info = probe_video(cover_path), probe_video(stego_path)
    if (cover_info.width, cover_info.height) != (stego_info.width, stego_info.height):
        raise ValueError("Cover and stego videos have different frame sizes.")
    if cover_info.frame_count != stego_info.frame_count:
        raise ValueError("Cover and stego videos have a different number of frames.")
    # Stream both videos side by side, one frame pair at a time.
    with FrameReader(cover_path, cover_info) as cover, FrameReader(stego_path, stego_info) as stego:
        return [mse(a, b) for a, b in zip(cover, stego)]
