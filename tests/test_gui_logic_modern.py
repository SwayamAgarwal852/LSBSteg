"""Tests for the gui_logic.py helpers used by the modern window (app_modern.py)."""

import math
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

import gui_logic as logic
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


# ---------------------------------------------------------------- capacity bar

def test_capacity_usage_counts_utf8_bytes():
    u = logic.capacity_usage("नम", 12)  # 2 Hindi letters = 6 bytes
    assert (u.size, u.fraction, u.over) == (6, 0.5, False)


def test_capacity_usage_exactly_full_is_not_over():
    u = logic.capacity_usage("x" * 10, 10)
    assert (u.fraction, u.over) == (1.0, False)


def test_capacity_usage_over_is_flagged_and_bar_clamped():
    u = logic.capacity_usage("x" * 11, 10)
    assert (u.size, u.fraction, u.over) == (11, 1.0, True)


def test_capacity_usage_without_cover():
    assert logic.capacity_usage("hi", None) is None
    assert logic.capacity_usage("hi", 0) is None


# ---------------------------------------------------------------- window size

@pytest.mark.parametrize("work, scale", [
    ((0, 0, 1920, 1032), 1.25),  # this laptop: 1920x1080, taskbar 48 px at the bottom
    ((0, 0, 1920, 1040), 1.0), ((0, 0, 1366, 728), 1.0), ((0, 0, 1366, 728), 1.25),
    ((0, 0, 1280, 680), 1.5), ((0, 0, 3840, 2100), 2.0), ((60, 0, 1860, 1080), 1.25),  # taskbar left
])
def test_fit_window_always_fits_the_work_area(work, scale):
    left, top, work_w, work_h = work
    w, h, x, y = logic.fit_window(*work, scale)
    frame_w, frame_h = 18, 47  # border and title bar measured at 125 %
    assert x >= left and y >= top
    assert x + round(w * scale) + frame_w <= left + work_w
    assert y + round(h * scale) + frame_h <= top + work_h
    assert (w, h) <= (1040, 700)


def test_fit_window_keeps_wanted_size_when_it_fits():
    assert logic.fit_window(0, 0, 1920, 1032, 1.25)[:2] == (1040, 700)
    assert logic.fit_window(0, 0, 1366, 728, 1.0)[:2] == (1040, 668)  # 728 - 60 frame


# ---------------------------------------------------------------- drag and drop

def test_dropped_file_single_path_with_spaces():
    assert logic.dropped_file(("C:/my files/cover é.png",)) == "C:/my files/cover é.png"


@pytest.mark.parametrize("paths", [(), ("a.png", "b.png"), ("",)])
def test_dropped_file_needs_exactly_one(paths):
    with pytest.raises(InputError, match="exactly one file"):
        logic.dropped_file(paths)


# ---------------------------------------------------------------- difference view

def test_difference_crop_marks_exactly_the_changed_values(png, tmp_path):
    out = logic.run_encode(IMAGE, png, "hello difference", tmp_path / "s.png").output
    crop = logic.difference_crop(IMAGE, png, out)
    cover, stego = np.array(Image.open(png)), np.array(Image.open(out))
    assert crop.size == (80, 60)  # smaller than DIFF_CROP: whole image, still 1:1
    expected = (cover != stego).astype(np.uint8) * 255
    assert np.array_equal(np.array(crop), expected)
    assert set(np.unique(np.array(crop))) <= {0, 255} and np.array(crop).any()


def test_difference_crop_is_top_left_and_never_resampled(tmp_path):
    cover = tmp_path / "big.png"
    Image.fromarray(np.random.default_rng(1).integers(0, 256, (600, 800, 3), dtype=np.uint8)).save(cover)
    out = logic.run_encode(IMAGE, cover, "x" * 5000, tmp_path / "s.png").output
    crop = np.array(logic.difference_crop(IMAGE, cover, out))
    assert crop.shape == (240, 320, 3)
    full = (np.array(Image.open(cover)) != np.array(Image.open(out))).astype(np.uint8) * 255
    assert np.array_equal(crop, full[:240, :320])


def test_difference_crop_ignores_alpha(tmp_path):
    px = np.random.default_rng(2).integers(0, 256, (40, 50, 4), dtype=np.uint8)
    cover = tmp_path / "rgba.png"
    Image.fromarray(px).save(cover)
    out = logic.run_encode(IMAGE, cover, "alpha stays", tmp_path / "s.png").output
    assert np.array(logic.difference_crop(IMAGE, cover, out)).shape == (40, 50, 3)


def test_difference_crop_rejects_different_sizes(png, tmp_path):
    other = tmp_path / "other.png"
    Image.fromarray(np.zeros((10, 10, 3), np.uint8)).save(other)
    with pytest.raises(InputError, match="different sizes"):
        logic.difference_crop(IMAGE, png, other)


def test_difference_crop_video_first_frame(clip, tmp_path):
    out = logic.run_encode(VIDEO, clip, "video diff", tmp_path / "s.mkv").output
    crop = np.array(logic.difference_crop(VIDEO, clip, out))
    assert crop.shape == (120, 160, 3) and crop.any()


# ---------------------------------------------------------------- quality panel

def test_measure_quality_image_matches_metrics_by_hand(png, tmp_path):
    message = "quality check"
    out = logic.run_encode(IMAGE, png, message, tmp_path / "s.png").output
    r = logic.measure_quality(IMAGE, png, out, len(message), 1000, 0.25)
    c = np.array(Image.open(png)).astype(np.float64)
    s = np.array(Image.open(out)).astype(np.float64)
    by_hand = np.mean((c - s) ** 2)
    assert r.mse == pytest.approx(by_hand)
    assert r.psnr == pytest.approx(10 * math.log10(255 ** 2 / by_hand))


def test_quality_lines_image_labels(png, tmp_path):
    out = logic.run_encode(IMAGE, png, "hi", tmp_path / "s.png").output
    lines = logic.quality_lines(logic.measure_quality(IMAGE, png, out, 2, 1787, 0.0042))
    text = "\n".join(lines)
    assert "not a general rule" in lines[0]
    assert "MSE (R, G, B values only; alpha not included)" in text
    assert "PSNR (R, G, B values only)" in text
    assert "Encode time: 4 ms" in text
    assert "Capacity used: 0.11% (2 of 1,787 message bytes" in text
    assert "PSNR is very high" in text  # tiny message note


def test_quality_lines_no_tiny_note_for_large_payload():
    r = logic.QualityReport(IMAGE, 0.5, 51.14, 1000, 1000, 1.5)
    assert not any("very high" in line for line in logic.quality_lines(r))


def test_quality_lines_video_names_pooled_and_mean():
    r = logic.QualityReport(VIDEO, 0.375, 52.39, 500, 1000, 2.0, frames_total=4,
                            frames_modified=2, mean_psnr_modified=49.64)
    text = "\n".join(logic.quality_lines(r))
    assert "MSE pooled over all 4 frames: 0.375000" in text
    assert "PSNR pooled over all 4 frames: 52.39 dB" in text
    assert "PSNR mean over the 2 modified frames only: 49.64 dB" in text


def test_quality_lines_video_nothing_changed():
    r = logic.QualityReport(VIDEO, 0.0, math.inf, 1, 1000, 1.0, frames_total=3)
    text = "\n".join(logic.quality_lines(r))
    assert "identical (inf dB)" in text and "No frame was changed" in text


def test_measure_quality_video(clip, tmp_path):
    out = logic.run_encode(VIDEO, clip, "v" * 10_000, tmp_path / "s.mkv").output
    r = logic.measure_quality(VIDEO, clip, out, 10_000, logic.video_capacity_bytes(clip), 1.0)
    # (13 + 10,000) * 8 = 80,104 bits; one 160x120 frame holds 57,600 -> 2 frames change
    assert (r.frames_total, r.frames_modified) == (25, 2)
    assert r.mean_psnr_modified < r.psnr  # pooled also counts the 23 unchanged frames
