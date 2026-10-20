"""Run real encode/decode experiments and save metrics.csv plus figures.

Usage (every run must be labelled, so test output is never mistaken for
real results):

    python results.py --label real --image photo.jpg --video clip.mp4
    python results.py --label synthetic --image gradient.png --out results/synthetic

For each cover and each payload size (percent of capacity) it encodes a
random ASCII message, decodes it again, and records MSE, PSNR, timings,
file sizes and whether the message came back exactly. Figures are made for
the largest payload of each cover.
"""

import argparse
import csv
import math
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files only; no window needed
import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)
import numpy as np  # noqa: E402

from decoder import decode_image, decode_video  # noqa: E402
from encoder import encode_image, encode_video  # noqa: E402
from image_utils import carrier_bytes, load_image  # noqa: E402
from metrics import (  # noqa: E402
    Timer,
    capacity_bytes,
    exact_match,
    mse,
    percent_used,
    psnr,
    summarize_frame_mses,
    video_frame_mses,
)
from video_utils import FrameReader, probe_video  # noqa: E402

CSV_COLUMNS = [
    "label", "kind", "cover", "width", "height", "mode", "payload_bytes", "capacity_bytes",
    "percent_used", "mse", "psnr_db", "frames_total", "frames_with_payload",
    "frames_modified", "mean_psnr_modified_db", "pooled_psnr_db", "encode_s", "decode_s",
    "exact_match", "cover_file_bytes", "stego_file_bytes",
]


def make_message(n_bytes: int, seed: int = 0) -> str:
    """Random printable ASCII text of exactly n_bytes (1 byte per character).

    Random text gives random bits, like a real (or compressed) message.
    """
    rng = np.random.default_rng(seed)
    return "".join(map(chr, rng.integers(32, 127, n_bytes)))


def payload_size(capacity: int, percent: float) -> int:
    return max(1, math.floor(capacity * percent / 100))


# ---------------------------------------------------------------- experiments

def image_run(cover: Path, percent: float, label: str, workdir: Path):
    """Encode + decode one image; return (csv row, cover pixels, stego pixels)."""
    cover_px = load_image(cover)
    capacity = capacity_bytes(carrier_bytes(cover_px).size)
    message = make_message(payload_size(capacity, percent))
    stego_path = workdir / f"{cover.stem}_{percent:g}pct.png"

    with Timer() as enc:
        encode_image(cover, message, stego_path)
    with Timer() as dec:
        recovered = decode_image(stego_path)

    stego_px = load_image(stego_path)
    # Compare only the bytes that can carry bits (alpha is never changed).
    m = mse(carrier_bytes(cover_px), carrier_bytes(stego_px))
    row = {
        "label": label, "kind": "image", "cover": cover.name,
        "width": cover_px.shape[1], "height": cover_px.shape[0], "mode": _mode(cover_px),
        "payload_bytes": len(message), "capacity_bytes": capacity,
        "percent_used": round(percent_used(len(message), capacity), 2),
        "mse": m, "psnr_db": psnr(m),
        "encode_s": round(enc.seconds, 4), "decode_s": round(dec.seconds, 4),
        "exact_match": exact_match(message, recovered),
        "cover_file_bytes": cover.stat().st_size, "stego_file_bytes": stego_path.stat().st_size,
    }
    return row, cover_px, stego_px


def video_run(cover: Path, percent: float, label: str, workdir: Path):
    """Encode + decode one video; return (csv row, first cover frame, first stego frame)."""
    info = probe_video(cover)
    capacity = capacity_bytes(info.usable_bytes)
    message = make_message(payload_size(capacity, percent))
    stego_path = workdir / f"{cover.stem}_{percent:g}pct.mkv"

    with Timer() as enc:
        encode_video(cover, message, stego_path)
    with Timer() as dec:
        recovered = decode_video(stego_path)

    frame_mses = video_frame_mses(cover, stego_path)
    payload_bits = (13 + len(message)) * 8
    summary = summarize_frame_mses(frame_mses, -(-payload_bits // info.frame_bytes))
    all_mse = sum(frame_mses) / len(frame_mses)
    row = {
        "label": label, "kind": "video", "cover": cover.name,
        "width": info.width, "height": info.height, "mode": "RGB",
        "payload_bytes": len(message), "capacity_bytes": capacity,
        "percent_used": round(percent_used(len(message), capacity), 2),
        "mse": all_mse, "psnr_db": psnr(all_mse), **summary,
        "mean_psnr_modified_db": summary["mean_psnr_modified"],
        "pooled_psnr_db": summary["pooled_psnr"],
        "encode_s": round(enc.seconds, 4), "decode_s": round(dec.seconds, 4),
        "exact_match": exact_match(message, recovered),
        "cover_file_bytes": cover.stat().st_size, "stego_file_bytes": stego_path.stat().st_size,
    }
    return row, _first_frame(cover), _first_frame(stego_path)


def _first_frame(path: Path) -> np.ndarray:
    with FrameReader(path, probe_video(path)) as reader:
        return next(iter(reader)).copy()


def _mode(pixels: np.ndarray) -> str:
    """Working mode from the array shape (see image_utils.load_image)."""
    if pixels.ndim == 2:
        return "L"
    return {2: "LA", 3: "RGB", 4: "RGBA"}[pixels.shape[2]]


# ---------------------------------------------------------------- figures

def _colour_part(pixels: np.ndarray) -> np.ndarray:
    """Drop alpha for display; return (H, W) grey or (H, W, 3) RGB."""
    if pixels.ndim == 2:
        return pixels
    return pixels[..., 0] if pixels.shape[2] == 2 else pixels[..., :3]


def save_figures(cover_px, stego_px, title: str, prefix: Path) -> list[Path]:
    """Side by side, amplified difference, and histogram overlay."""
    cover, stego = _colour_part(cover_px), _colour_part(stego_px)
    grey = cover.ndim == 2
    paths = []

    # 1. Cover and stego side by side: they should look the same.
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    for ax, img, name in zip(axes, (cover, stego), ("Cover", "Stego")):
        ax.imshow(img, cmap="gray" if grey else None, vmin=0, vmax=255)
        ax.set_title(name)
        ax.axis("off")
    fig.suptitle(title, fontsize=11)
    paths.append(_save(fig, prefix.with_name(prefix.name + "_side_by_side.png")))

    # 2. Difference x 255: a change of 1 becomes 255 (white), no change stays 0 (black).
    diff = np.abs(cover.astype(np.int16) - stego.astype(np.int16))
    amplified = (diff * 255).clip(0, 255).astype(np.uint8)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.imshow(amplified, cmap="gray" if grey else None, vmin=0, vmax=255)
    ax.set_title(f"|cover - stego| x 255  (max diff = {diff.max()}, "
                 f"{100 * (diff > 0).mean():.1f}% of values changed)", fontsize=10)
    ax.axis("off")
    fig.suptitle(title, fontsize=11)
    paths.append(_save(fig, prefix.with_name(prefix.name + "_difference_x255.png")))

    # 3. Histogram overlay per channel: LSB changes barely move the histogram.
    channels = [("Grey", "black", cover, stego)] if grey else [
        (name, colour, cover[..., i], stego[..., i])
        for i, (name, colour) in enumerate((("Red", "red"), ("Green", "green"), ("Blue", "blue")))]
    fig, axes = plt.subplots(1, len(channels), figsize=(5 * len(channels), 3.8), squeeze=False)
    for ax, (name, colour, c, s) in zip(axes[0], channels):
        bins = np.arange(257)
        ax.hist(c.ravel(), bins=bins, histtype="step", color=colour, label="cover")
        ax.hist(s.ravel(), bins=bins, histtype="step", color="black", linestyle="--",
                linewidth=0.8, label="stego")
        ax.set_title(name)
        ax.set_xlabel("pixel value")
        ax.set_xlim(0, 255)
        ax.legend()
    axes[0][0].set_ylabel("count")
    fig.suptitle(title, fontsize=11)
    paths.append(_save(fig, prefix.with_name(prefix.name + "_histogram.png")))
    return paths


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- main

def run(images, videos, label: str, out_dir: Path, percents) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:  # stego files are not kept
        work = Path(tmp)
        for kind, covers, runner in (("image", images, image_run), ("video", videos, video_run)):
            for cover in map(Path, covers):
                for percent in percents:
                    row, cover_px, stego_px = runner(cover, percent, label, work)
                    rows.append(row)
                    print(f"[{label}] {kind} {cover.name} {percent:g}%: "
                          f"PSNR {row['psnr_db']:.2f} dB, exact={row['exact_match']}")
                # Figures for the largest payload of this cover.
                title = f"[{label.upper()}] {cover.name} - {kind}, {percent:g}% of capacity"
                if kind == "video":
                    title += " (first frame)"
                save_figures(cover_px, stego_px, title, out_dir / f"{label}_{kind}_{cover.stem}")

    csv_path = out_dir / "metrics.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True,
                        help="tag written into the CSV, figure titles and file names "
                             "(e.g. 'real' or 'synthetic')")
    parser.add_argument("--image", action="append", default=[], help="cover image (repeatable)")
    parser.add_argument("--video", action="append", default=[], help="cover video (repeatable)")
    parser.add_argument("--out", default="results", help="output folder (default: results)")
    parser.add_argument("--percent", type=float, action="append",
                        help="payload size in %% of capacity (repeatable; default 1, 10, 50, 100)")
    args = parser.parse_args(argv)
    if not args.image and not args.video:
        parser.error("give at least one --image or --video")
    csv_path = run(args.image, args.video, args.label, Path(args.out),
                   args.percent or [1, 10, 50, 100])
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
