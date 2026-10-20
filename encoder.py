"""Hide a text message in an image (video support is added in SP5)."""

from pathlib import Path

from header import embed_message, max_payload_bytes
from image_utils import carrier_bytes, load_image, save_png, with_carrier_bytes


def image_capacity_bytes(cover_path) -> int:
    """Maximum message size (UTF-8 bytes) this cover image can hold."""
    return max_payload_bytes(carrier_bytes(load_image(cover_path)).size)


def encode_image(cover_path, message: str, output_path) -> Path:
    """Hide `message` in `cover_path` and save the result as a PNG.

    Steps: load + normalise the image -> take the R,G,B (or grey) bytes ->
    write header + message into their LSBs -> put them back -> save PNG.
    The cover file on disk is only read, never changed.
    """
    pixels = load_image(cover_path)
    stego_flat = embed_message(carrier_bytes(pixels), message)
    return save_png(with_carrier_bytes(pixels, stego_flat), output_path)
