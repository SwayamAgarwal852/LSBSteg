"""Negative demonstrations (SP8): what normal file handling does to a hidden message.

Outcomes measured in the SP8 exploration run (2026-10-22, Pillow 13.0.0, FFmpeg 9.0.2):
a lossy copy (JPEG, resize, H.264 in YUV) keeps only about 50-70% of the embedded bits,
i.e. close to random. Whether the 104 header bits happen to survive is luck and depends
on the content (one flat grey 99% resize kept all of them). So these tests do not
assert WHICH error appears: they assert that the decoder reports an error and never
returns text. A false "success" would need the 32-bit magic and the CRC32 to match by
chance. Pixel-exact operations (cropping away rows/columns that hold no message bits,
lossless RGB H.264) keep the message; those outcomes follow from the row-major layout
and are fully deterministic.
"""

import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from decoder import decode_image, decode_video
from encoder import encode_image, encode_video
from errors import CorruptedDataError, NoHiddenMessageError

LOST = (NoHiddenMessageError, CorruptedDataError)
W, H = 320, 240
SHORT = "Meet at the library at 7 pm. नमस्ते 😀"  # 52 bytes: lies inside the first row
LONG = "x" * 3000  # (13 + 3000) * 8 = 24,104 bits = rows 0-25 of a 320-wide RGB image


@pytest.fixture
def stego_png(tmp_path):
    def make(message):
        cover = tmp_path / "cover.png"
        Image.fromarray(np.random.default_rng(1).integers(0, 256, (H, W, 3), dtype=np.uint8)).save(cover)
        out = encode_image(cover, message, tmp_path / "stego.png")
        assert decode_image(out) == message  # control: the untouched stego file works
        with Image.open(out) as img:  # copy into memory: Windows cannot replace an open file
            return img.copy()
    return make


# ---------------------------------------------------------------- lossy image operations

@pytest.mark.parametrize("save_kwargs", [{"quality": 95}, {"quality": 100, "subsampling": 0}],
                         ids=["q95", "q100_444"])
def test_resaving_as_jpeg_destroys_message(stego_png, tmp_path, save_kwargs):
    jpg = tmp_path / "resaved.jpg"
    stego_png(SHORT).save(jpg, **save_kwargs)
    with pytest.raises(LOST):
        decode_image(jpg)


def test_resizing_destroys_message(stego_png, tmp_path):
    out = tmp_path / "resized.png"
    stego_png(SHORT).resize((int(W * 0.99), int(H * 0.99)), Image.BICUBIC).save(out)
    with pytest.raises(LOST):
        decode_image(out)


@pytest.mark.parametrize("box", [(1, 0, W, H), (0, 1, W, H)], ids=["left_1px", "top_1px"])
def test_cropping_left_or_top_shifts_every_bit(stego_png, tmp_path, box):
    out = tmp_path / "cropped.png"
    stego_png(SHORT).crop(box).save(out)
    with pytest.raises(LOST):
        decode_image(out)


# ---------------------------------------------------------------- crops that only remove unused pixels

def test_cropping_right_edge_depends_on_message_length(stego_png, tmp_path):
    out = tmp_path / "cropped.png"
    stego_png(SHORT).crop((0, 0, W - 1, H)).save(out)  # message ends before the last column
    assert decode_image(out) == SHORT
    stego_png(LONG).crop((0, 0, W - 1, H)).save(out)  # row 2 onwards now starts 1 pixel early
    with pytest.raises(CorruptedDataError):
        decode_image(out)


def test_cropping_bottom_keeps_message_until_it_cuts_into_it(stego_png, tmp_path):
    out = tmp_path / "cropped.png"
    img = stego_png(LONG)
    img.crop((0, 0, W, 26)).save(out)  # exactly the 26 rows that hold the message
    assert decode_image(out) == LONG
    img.crop((0, 0, W, 25)).save(out)
    with pytest.raises(CorruptedDataError, match="Header claims 3000 bytes"):
        decode_image(out)


# ---------------------------------------------------------------- video re-encoding

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
VIDEO_MESSAGE = "Video secret नमस्ते 😀 " * 20


@pytest.fixture(scope="module")
def stego_mkv(tmp_path_factory):
    d = tmp_path_factory.mktemp("negative_video")
    cover = d / "cover.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cover)], check=True)
    out = encode_video(cover, VIDEO_MESSAGE, d / "stego.mkv")
    assert decode_video(out) == VIDEO_MESSAGE
    return out


def reencode(stego, out, *options):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(stego), *options, str(out)], check=True)
    return out


@needs_ffmpeg
@pytest.mark.parametrize("options", [
    ["-c:v", "libx264", "-c:a", "copy"],  # ffmpeg defaults (picks yuv444p for this RGB input)
    ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy"],  # what phones/sites produce
    ["-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv444p", "-c:a", "copy"],  # "lossless" YUV
], ids=["default", "yuv420p", "crf0_yuv444p"])
def test_h264_reencoding_destroys_message(stego_mkv, tmp_path, options):
    out = reencode(stego_mkv, tmp_path / "reencoded.mp4", *options)
    with pytest.raises(LOST):
        decode_video(out)


@needs_ffmpeg
def test_lossless_rgb_h264_keeps_message(stego_mkv, tmp_path):
    """Not every MP4 kills the message: only lossy or RGB->YUV conversion does."""
    encoders = subprocess.run([FFMPEG, "-v", "error", "-encoders"], capture_output=True, text=True).stdout
    if "libx264rgb" not in encoders:
        pytest.skip("this ffmpeg build has no libx264rgb")
    out = reencode(stego_mkv, tmp_path / "lossless_rgb.mp4", "-c:v", "libx264rgb", "-crf", "0", "-c:a", "copy")
    assert decode_video(out) == VIDEO_MESSAGE
