"""Recover a text message hidden by encoder.py (video support is added in SP5)."""

from header import extract_message
from image_utils import carrier_bytes, load_image


def decode_image(stego_path) -> str:
    """Return the hidden message, or raise a clear StegoError.

    The image is loaded exactly like the encoder does, so its own mode
    tells us which channels carry the bits (L/LA: grey, RGB/RGBA: R,G,B).
    """
    return extract_message(carrier_bytes(load_image(stego_path)))
