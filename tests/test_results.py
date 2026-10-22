"""Tests for results.py on small SYNTHETIC covers (SP6)."""

import csv
import math
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

import results


def test_make_message_is_exact_size_ascii():
    msg = results.make_message(1000)
    assert len(msg) == len(msg.encode("utf-8")) == 1000
    assert all(32 <= ord(ch) < 127 for ch in msg)


def test_payload_size():
    assert results.payload_size(3737, 100) == 3737
    assert results.payload_size(3737, 10) == 373
    assert results.payload_size(3737, 0.001) == 1  # never an empty message


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_run_writes_csv_and_figures(tmp_path):
    rng = np.random.default_rng(0)
    grad = np.linspace(0, 255, 96)[None, :, None] * np.ones((64, 1, 3))
    image = tmp_path / "synthetic_gradient.png"
    Image.fromarray(np.clip(grad + rng.integers(-10, 11, grad.shape), 0, 255).astype(np.uint8)).save(image)
    grey = tmp_path / "synthetic_grey.png"
    Image.fromarray(rng.integers(0, 256, (40, 50), dtype=np.uint8)).save(grey)
    video = tmp_path / "synthetic_testsrc.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=size=96x64:rate=25:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)

    out = tmp_path / "out"
    csv_path = results.run([image, grey], [video], "synthetic", out, [10, 100])

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 6  # 3 covers x 2 sizes
    assert list(rows[0]) == results.CSV_COLUMNS
    sizes = {p.name: p.stat().st_size for p in (image, grey, video)}
    for row in rows:
        assert row["label"] == "synthetic"
        assert row["exact_match"] == "True"
        assert 40 < float(row["psnr_db"]) < math.inf
        # PSNR column agrees with the MSE column: 10*log10(255^2 / MSE)
        assert float(row["psnr_db"]) == pytest.approx(10 * math.log10(65025 / float(row["mse"])))
        assert int(row["payload_bytes"]) <= int(row["capacity_bytes"])
        assert float(row["encode_s"]) > 0 and float(row["decode_s"]) > 0
        assert int(row["cover_file_bytes"]) == sizes[row["cover"]]
        assert int(row["stego_file_bytes"]) > 0
    full = [r for r in rows if r["percent_used"] == "100.0"]
    assert len(full) == 3
    video_full = next(r for r in full if r["kind"] == "video")
    assert int(video_full["frames_modified"]) == 25 == int(video_full["frames_total"])
    assert float(video_full["pooled_psnr_db"]) == pytest.approx(float(video_full["psnr_db"]))
    assert next(r for r in rows if r["cover"] == "synthetic_grey.png")["mode"] == "L"

    figures = sorted(p.name for p in out.glob("*.png"))
    assert len(figures) == 9  # 3 figures per cover
    assert all(name.startswith("synthetic_") for name in figures)
    assert all((out / name).stat().st_size > 5000 for name in figures)
