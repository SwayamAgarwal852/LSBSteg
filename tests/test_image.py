"""Tests for the image pipeline: encoder.encode_image / decoder.decode_image (SP4)."""

import hashlib
import struct
import time
import zlib

import numpy as np
import pytest
from PIL import Image

from decoder import decode_image
from encoder import encode_image, image_capacity_bytes
from errors import CapacityError, NoHiddenMessageError, UnsupportedFormatError
from image_utils import png_bit_depth

MESSAGE = "Meet at 7 pm. नमस्ते 😀"


# ---------------------------------------------------------------- helpers

def make_pixels(h, w, channels, seed=0):
    """Gradient plus noise: looks like a real picture, and is reproducible."""
    rng = np.random.default_rng(seed)
    grad = np.linspace(0, 255, w, dtype=np.float64)[None, :] * np.ones((h, 1))
    noise = rng.integers(-20, 21, (h, w))
    base = np.clip(grad + noise, 0, 255).astype(np.uint8)
    if channels == 1:
        return base
    return np.stack([np.roll(base, 7 * c, axis=1) for c in range(channels)], axis=2)


def save(pixels, path, **kwargs):
    Image.fromarray(pixels).save(path, **kwargs)
    return path


def load(path):
    with Image.open(path) as img:
        return img.mode, np.array(img)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_png16(path, samples, colour_type):
    """Write a real 16-bit PNG by hand (Pillow cannot write 16-bit RGB).

    colour_type: 0 = grey, 2 = RGB, 4 = grey+alpha, 6 = RGBA.
    """
    h, w = samples.shape[:2]
    rows = samples.astype(">u2").reshape(h, -1).tobytes()
    stride = len(rows) // h
    raw = b"".join(b"\x00" + rows[i * stride:(i + 1) * stride] for i in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr = struct.pack(">IIBBBBB", w, h, 16, colour_type, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


# ---------------------------------------------------------------- modes

def test_rgb_round_trip(tmp_path):
    cover = save(make_pixels(60, 80, 3), tmp_path / "cover.png")
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")
    assert load(out)[0] == "RGB"
    assert decode_image(out) == MESSAGE


def test_grayscale_stays_grayscale(tmp_path):
    cover = save(make_pixels(60, 80, 1), tmp_path / "grey.png")
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")
    assert load(out)[0] == "L"
    assert decode_image(out) == MESSAGE
    assert image_capacity_bytes(cover) == (60 * 80 - 104) // 8  # 1 bit per pixel


def test_rgba_alpha_byte_identical(tmp_path):
    pixels = make_pixels(60, 80, 4)
    pixels[..., 3] = np.random.default_rng(9).integers(0, 256, (60, 80))  # varied alpha
    cover = save(pixels, tmp_path / "rgba.png")
    out = encode_image(cover, "x" * 500, tmp_path / "stego.png")
    mode, stego = load(out)
    assert mode == "RGBA"
    assert np.array_equal(stego[..., 3], pixels[..., 3])
    assert decode_image(out) == "x" * 500


def test_la_alpha_byte_identical(tmp_path):
    pixels = make_pixels(60, 80, 2)
    cover = save(pixels, tmp_path / "la.png")
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")
    mode, stego = load(out)
    assert mode == "LA"
    assert np.array_equal(stego[..., 1], pixels[..., 1])
    assert decode_image(out) == MESSAGE


def test_palette_converted_to_rgb(tmp_path):
    cover = tmp_path / "palette.png"
    Image.fromarray(make_pixels(60, 80, 3)).convert("P", palette=Image.Palette.ADAPTIVE).save(cover)
    assert load(cover)[0] == "P"
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")
    assert load(out)[0] == "RGB"
    assert decode_image(out) == MESSAGE


def test_palette_with_transparency_becomes_rgba(tmp_path):
    cover = tmp_path / "palette_t.png"
    img = Image.fromarray(make_pixels(60, 80, 3)).convert("P", palette=Image.Palette.ADAPTIVE)
    img.save(cover, transparency=0)
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")
    assert load(out)[0] == "RGBA"
    assert decode_image(out) == MESSAGE


def test_jpeg_cover(tmp_path):
    cover = save(make_pixels(60, 80, 3), tmp_path / "photo.jpg", quality=90)
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")
    with Image.open(out) as img:
        assert img.format == "PNG" and img.mode == "RGB"
    assert decode_image(out) == MESSAGE


@pytest.mark.parametrize("mode", ["1", "CMYK"])
def test_other_modes_converted_to_rgb(tmp_path, mode):
    ext = "jpg" if mode == "CMYK" else "png"
    cover = tmp_path / f"cover.{ext}"
    Image.fromarray(make_pixels(60, 80, 3)).convert(mode).save(cover)
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")
    assert load(out)[0] == "RGB"
    assert decode_image(out) == MESSAGE


def test_bmp_cover(tmp_path):
    cover = save(make_pixels(60, 80, 3), tmp_path / "cover.bmp")
    assert decode_image(encode_image(cover, MESSAGE, tmp_path / "stego.png")) == MESSAGE


# ---------------------------------------------------------------- saved to disk and reloaded

def test_stego_saved_reloaded_and_decoded(tmp_path):
    pixels = make_pixels(60, 80, 3)
    cover = save(pixels, tmp_path / "cover.png")
    cover_hash = sha256(cover)
    out = encode_image(cover, MESSAGE, tmp_path / "stego.png")

    assert out.exists() and out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(out) as img:  # fresh read from disk
        assert img.format == "PNG" and img.size == (80, 60)
        stego = np.array(img)
    diff = np.abs(stego.astype(np.int16) - pixels.astype(np.int16))
    assert diff.max() == 1  # something changed, but never by more than 1
    assert sha256(cover) == cover_hash  # cover file untouched
    assert decode_image(out) == MESSAGE


# ---------------------------------------------------------------- capacity

def test_one_byte_message(tmp_path):
    cover = save(make_pixels(20, 20, 3), tmp_path / "cover.png")
    assert decode_image(encode_image(cover, "A", tmp_path / "s.png")) == "A"


def test_exactly_at_capacity(tmp_path):
    cover = save(make_pixels(20, 20, 3), tmp_path / "cover.png")
    limit = image_capacity_bytes(cover)
    assert limit == (20 * 20 * 3 - 104) // 8 == 137
    out = encode_image(cover, "z" * limit, tmp_path / "s.png")
    assert decode_image(out) == "z" * limit


def test_one_byte_over_capacity(tmp_path):
    cover = save(make_pixels(20, 20, 3), tmp_path / "cover.png")
    out = tmp_path / "s.png"
    with pytest.raises(CapacityError, match=r"138 bytes.*at most 137 bytes"):
        encode_image(cover, "z" * 138, out)
    assert not out.exists()  # nothing written on failure


def test_capacity_counts_utf8_bytes_not_characters(tmp_path):
    cover = save(make_pixels(20, 20, 3), tmp_path / "cover.png")
    # 46 Hindi letters x 3 bytes = 138 bytes > 137, although only 46 characters
    with pytest.raises(CapacityError):
        encode_image(cover, "न" * 46, tmp_path / "s.png")


def test_1x1_image(tmp_path):
    cover = save(make_pixels(1, 1, 3), tmp_path / "tiny.png")
    with pytest.raises(CapacityError, match="at most 0 bytes"):
        encode_image(cover, "A", tmp_path / "s.png")
    with pytest.raises(NoHiddenMessageError):
        decode_image(cover)


def test_large_4000x3000_image(tmp_path):
    cover = save(make_pixels(3000, 4000, 3), tmp_path / "big.png")
    message = "large image test " * 60_000  # 1,020,000 bytes
    t0 = time.perf_counter()
    out = encode_image(cover, message, tmp_path / "big_stego.png")
    t1 = time.perf_counter()
    assert decode_image(out) == message
    t2 = time.perf_counter()
    print(f"\n4000x3000 RGB, {len(message):,} byte message: "
          f"encode {t1 - t0:.2f} s, decode {t2 - t1:.2f} s (dev laptop, incl. PNG I/O)")


# ---------------------------------------------------------------- 16-bit PNGs

def test_pillow_hides_16bit_rgb(tmp_path):
    """Documents WHY we read IHDR: Pillow reports 16-bit RGB as 8-bit 'RGB'."""
    path = write_png16(tmp_path / "rgb16.png", np.full((8, 8, 3), 40000), colour_type=2)
    assert load(path)[0] == "RGB"
    assert png_bit_depth(path) == 16


@pytest.mark.parametrize("colour_type, channels", [(0, 1), (2, 3), (4, 2), (6, 4)],
                         ids=["grey16", "rgb16", "grey_alpha16", "rgba16"])
def test_16bit_png_rejected(tmp_path, colour_type, channels):
    shape = (8, 8) if channels == 1 else (8, 8, channels)
    path = write_png16(tmp_path / "deep.png", np.full(shape, 40000), colour_type)
    with pytest.raises(UnsupportedFormatError, match="16-bit"):
        encode_image(path, "A", tmp_path / "s.png")
    with pytest.raises(UnsupportedFormatError, match="16-bit"):
        decode_image(path)


def test_16bit_grey_written_by_pillow_rejected(tmp_path):
    path = save(np.full((8, 8), 40000, dtype=np.uint16), tmp_path / "i16.png")
    with pytest.raises(UnsupportedFormatError):
        encode_image(path, "A", tmp_path / "s.png")


def test_8bit_png_depth_is_8(tmp_path):
    assert png_bit_depth(save(make_pixels(4, 4, 3), tmp_path / "a.png")) == 8


# ---------------------------------------------------------------- paths and bad input

def test_path_with_spaces_and_non_ascii(tmp_path):
    folder = tmp_path / "my folder नमस्ते é"
    folder.mkdir()
    cover = save(make_pixels(40, 40, 3), folder / "cover image 😀 ü.png")
    out = encode_image(cover, MESSAGE, folder / "stego file ñ.png")
    assert decode_image(out) == MESSAGE


def test_clean_image_has_no_hidden_message(tmp_path):
    cover = save(make_pixels(60, 80, 3), tmp_path / "clean.png")
    with pytest.raises(NoHiddenMessageError, match="No hidden message"):
        decode_image(cover)


def test_output_must_be_png(tmp_path):
    cover = save(make_pixels(20, 20, 3), tmp_path / "cover.png")
    with pytest.raises(UnsupportedFormatError, match=r"\.png"):
        encode_image(cover, "A", tmp_path / "stego.jpg")


def test_unsupported_cover_format(tmp_path):
    cover = save(make_pixels(20, 20, 3), tmp_path / "cover.gif")
    with pytest.raises(UnsupportedFormatError, match="GIF"):
        encode_image(cover, "A", tmp_path / "s.png")


def test_not_an_image(tmp_path):
    fake = tmp_path / "notes.png"
    fake.write_text("hello, I am not an image")
    with pytest.raises(UnsupportedFormatError, match="not a readable image"):
        decode_image(fake)
