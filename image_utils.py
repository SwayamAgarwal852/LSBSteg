"""Image loading and channel handling shared by encoder.py and decoder.py.

Every image is turned into one of four 8-bit modes before we touch it:
    RGB / RGBA -> hide bits in R, G, B (alpha is never changed)
    L   / LA   -> hide bits in the grey channel (alpha is never changed)
Encoder and decoder use the SAME loading code, so they always agree on
which bytes carry the message (PLAN.md A3-A6, D5).
"""

from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from errors import UnsupportedFormatError

SUPPORTED_FORMATS = {"PNG", "JPEG", "BMP"}  # D5: covers we accept
WORKING_MODES = {"RGB", "RGBA", "L", "LA"}  # modes we embed into directly
HIGH_BIT_DEPTH_MODES = {"I;16", "I;16B", "I;16L", "I", "F"}  # >8 bits per sample

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- 16-bit detection

def png_bit_depth(path: Path) -> int | None:
    """Return the bit depth stored in a PNG's IHDR chunk (None if not a PNG).

    We read the file header ourselves because Pillow silently turns 16-bit
    RGB / RGBA PNGs into 8-bit 'RGB' / 'RGBA' images (verified with Pillow
    13.0.0), so checking img.mode alone would NOT catch them.
    PNG layout: 8-byte signature, 4-byte length, b"IHDR", width(4),
    height(4), then 1 byte bit depth at offset 24.
    """
    with open(path, "rb") as f:
        start = f.read(26)
    if len(start) < 26 or start[:8] != PNG_SIGNATURE or start[12:16] != b"IHDR":
        return None
    return start[24]


# ---------------------------------------------------------------- loading

def load_image(path) -> np.ndarray:
    """Open an image and return it as a uint8 array in a working mode.

    Shape is (H, W) for L, or (H, W, C) for LA / RGB / RGBA.
    Raises UnsupportedFormatError for anything we cannot embed into safely.
    """
    path = Path(path)
    # Check bit depth on the raw file BEFORE Pillow converts it to 8-bit.
    depth = png_bit_depth(path)
    if depth is not None and depth > 8:
        raise UnsupportedFormatError(
            f"{depth}-bit PNGs are not supported. Please use an 8-bit image."
        )

    try:
        with Image.open(path) as img:
            if img.format not in SUPPORTED_FORMATS:
                raise UnsupportedFormatError(
                    f"{img.format} files are not supported. Use PNG, JPEG or BMP."
                )
            img = _to_working_mode(img)
            # np.array (not asarray) makes our own writable copy of the pixels,
            # read fully before the file is closed.
            return np.array(img)
    except UnidentifiedImageError as exc:
        raise UnsupportedFormatError(f"'{path.name}' is not a readable image.") from exc


def _to_working_mode(img: Image.Image) -> Image.Image:
    """Convert any Pillow mode into RGB, RGBA, L or LA."""
    if img.mode in HIGH_BIT_DEPTH_MODES:
        # Backup for the IHDR check (e.g. a 16-bit image in another format).
        raise UnsupportedFormatError(f"High bit-depth images ({img.mode}) are not supported.")
    if img.mode in WORKING_MODES:
        return img
    if img.mode in ("P", "PA"):
        # Changing the LSB of a palette INDEX can pick a totally different
        # colour, so palette images become true-colour first (A5).
        has_alpha = img.mode == "PA" or "transparency" in img.info
        return img.convert("RGBA" if has_alpha else "RGB")
    # 1-bit, CMYK, YCbCr, ...: plain RGB is the simplest safe choice.
    return img.convert("RGB")


# ---------------------------------------------------------------- channels

def carrier_bytes(pixels: np.ndarray) -> np.ndarray:
    """Return the bytes that carry the message as a flat 1-D array.

    Order: row by row, pixel by pixel, then R, G, B inside a pixel (A3).
    Alpha (if any) is left out, so transparency is never changed.
    """
    if pixels.ndim == 2:  # L
        return pixels.reshape(-1)
    if pixels.shape[2] == 2:  # LA -> grey channel only
        return pixels[..., 0].reshape(-1)
    return pixels[..., :3].reshape(-1)  # RGB / RGBA -> R, G, B only


def with_carrier_bytes(pixels: np.ndarray, flat: np.ndarray) -> np.ndarray:
    """Inverse of carrier_bytes: put `flat` back into a copy of `pixels`."""
    out = pixels.copy()
    if out.ndim == 2:
        out[:] = flat.reshape(out.shape)
    elif out.shape[2] == 2:
        out[..., 0] = flat.reshape(out.shape[:2])
    else:
        out[..., :3] = flat.reshape(out.shape[0], out.shape[1], 3)
    return out


def save_png(pixels: np.ndarray, path) -> Path:
    """Save as PNG (lossless, so every LSB survives). Mode follows the shape."""
    path = Path(path)
    if path.suffix.lower() != ".png":
        # Saving as JPEG would destroy the hidden bits, so insist on .png.
        raise UnsupportedFormatError("Output file must end in .png (lossless).")
    Image.fromarray(pixels).save(path, format="PNG")
    return path
