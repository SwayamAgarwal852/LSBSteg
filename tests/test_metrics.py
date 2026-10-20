"""Tests for metrics.py (SP6).

Hand arithmetic used below (log10(255^2) = log10(65025) = 4.813080):
    PSNR = 10 * (4.813080 - log10(MSE))
    MSE = 1      -> 48.1308 dB
    MSE = 0.5    -> 48.1308 + 10*log10(2)   = 48.1308 + 3.0103  = 51.1411 dB
    MSE = 0.01   -> 48.1308 + 10*log10(100) = 48.1308 + 20      = 68.1308 dB
    MSE = 0.375  -> 48.1308 + 10*log10(8/3) = 48.1308 + 4.2597  = 52.3905 dB
"""

import math
import shutil
import subprocess

import numpy as np
import pytest

from bitutils import embed_bits
from encoder import encode_video
from metrics import (
    Timer,
    capacity_bytes,
    exact_match,
    format_psnr,
    mse,
    percent_used,
    psnr,
    summarize_frame_mses,
    video_frame_mses,
)


# ---------------------------------------------------------------- MSE / PSNR by hand

def test_one_changed_byte_among_100():
    # 99 bytes equal, one differs by 1: MSE = 1^2 / 100 = 0.01
    cover = np.full(100, 128, dtype=np.uint8)
    stego = cover.copy()
    stego[42] = 129
    assert mse(cover, stego) == pytest.approx(0.01)
    # PSNR = 10*log10(65025 / 0.01) = 10*log10(6,502,500) = 68.1308 dB
    assert psnr(mse(cover, stego)) == pytest.approx(68.1308, abs=1e-4)


def test_every_byte_differs_by_one():
    cover = np.arange(256, dtype=np.uint8)
    stego = cover ^ 1  # flip every LSB -> every byte changes by exactly 1
    assert mse(cover, stego) == 1.0
    assert psnr(1.0) == pytest.approx(48.1308, abs=1e-4)


def test_no_uint8_overflow():
    # In uint8, 0 - 255 wraps to 1 (MSE would wrongly be 0.25).
    cover = np.array([0, 10, 10, 10], dtype=np.uint8)
    stego = np.array([255, 10, 10, 10], dtype=np.uint8)
    assert mse(cover, stego) == 65025 / 4  # = 16256.25
    # PSNR = 10*log10(65025 / (65025/4)) = 10*log10(4) = 6.0206 dB
    assert psnr(mse(cover, stego)) == pytest.approx(6.0206, abs=1e-4)


def test_identical_gives_infinite_psnr():
    a = np.random.default_rng(0).integers(0, 256, 1000, dtype=np.uint8)
    assert mse(a, a.copy()) == 0.0
    assert psnr(0.0) == math.inf
    assert format_psnr(psnr(0.0)) == "identical (inf dB)"
    assert format_psnr(51.14109) == "51.14 dB"


def test_shape_mismatch_rejected():
    with pytest.raises(ValueError):
        mse(np.zeros(4, np.uint8), np.zeros(5, np.uint8))


def test_random_lsb_changes_give_about_51_db():
    """Sanity check: setting every LSB to a random bit changes about half of
    the bytes by 1, so E[diff^2] = 0.5 * 1 = 0.5 and PSNR ~ 51.14 dB."""
    rng = np.random.default_rng(2026)
    cover = rng.integers(0, 256, 10_000_000, dtype=np.uint8)
    bits = rng.integers(0, 2, cover.size, dtype=np.uint8)
    stego = embed_bits(cover, bits)
    measured_mse = mse(cover, stego)
    measured_psnr = psnr(measured_mse)
    print(f"\n10,000,000 random bytes, every LSB set to a random bit: "
          f"MSE = {measured_mse:.6f}, PSNR = {measured_psnr:.4f} dB "
          f"(theory: 0.5 and 51.1411 dB)")
    # Std. error of the mean of 1e7 coin flips = 0.5/sqrt(1e7) = 0.00016
    assert measured_mse == pytest.approx(0.5, abs=0.001)
    assert measured_psnr == pytest.approx(51.1411, abs=0.01)


# ---------------------------------------------------------------- capacity / match / timer

def test_capacity_and_percent_used():
    assert capacity_bytes(100 * 100 * 3) == 3737
    assert percent_used(3737, 3737) == 100.0
    assert percent_used(1, 4) == 25.0


def test_exact_match():
    assert exact_match("नमस्ते", "नमस्ते")
    assert not exact_match("hello", "hellO")


def test_timer_measures_elapsed_time():
    with Timer() as t:
        sum(range(100_000))
    assert 0 < t.seconds < 5


# ---------------------------------------------------------------- video summary

def test_video_summary_by_hand():
    # Frame MSEs 1.0, 0.5, 0, 0  (two frames changed, two untouched)
    s = summarize_frame_mses([1.0, 0.5, 0.0, 0.0], payload_frames=2)
    assert s["frames_total"] == 4 and s["frames_modified"] == 2
    # (a) mean of 48.1308 and 51.1411 = 49.6360 dB
    assert s["mean_psnr_modified"] == pytest.approx(49.6360, abs=1e-4)
    # (b) pooled MSE = (1 + 0.5 + 0 + 0) / 4 = 0.375 -> 52.3905 dB
    assert s["pooled_psnr"] == pytest.approx(52.3905, abs=1e-4)


def test_video_summary_payload_frame_with_zero_mse():
    # Frame 2 carried payload bits but they all matched the old LSBs (MSE 0):
    # it is NOT counted as modified and does not make the mean infinite.
    s = summarize_frame_mses([1.0, 0.0, 0.0], payload_frames=2)
    assert s["frames_with_payload"] == 2 and s["frames_modified"] == 1
    assert s["mean_psnr_modified"] == pytest.approx(48.1308, abs=1e-4)
    assert s["pooled_psnr"] == pytest.approx(48.1308 + 10 * math.log10(3), abs=1e-4)


def test_video_summary_nothing_changed():
    s = summarize_frame_mses([0.0, 0.0])
    assert s["frames_modified"] == 0
    assert s["mean_psnr_modified"] == math.inf and s["pooled_psnr"] == math.inf


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_video_frame_mses_on_real_clip(tmp_path):
    cover = tmp_path / "cover.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=160x120:rate=25:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cover)], check=True)
    message = "x" * 10_000  # (13 + 10000) * 8 = 80,104 bits; a frame holds 57,600 -> 2 frames
    stego = encode_video(cover, message, tmp_path / "stego.mkv")
    mses = video_frame_mses(cover, stego)
    assert len(mses) == 25
    assert all(m > 0 for m in mses[:2]) and all(m == 0 for m in mses[2:])
    # Frame 2 holds only 80,104 - 57,600 = 22,504 bits, so it changes less.
    assert mses[1] < mses[0]
    s = summarize_frame_mses(mses, payload_frames=2)
    assert s["frames_modified"] == 2
    assert s["pooled_psnr"] > s["mean_psnr_modified"]
