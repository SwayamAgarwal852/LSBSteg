"""Recover a text message hidden by encoder.py, from an image or a video."""

import numpy as np

from bitutils import bits_to_bytes, bytes_to_text
from errors import CorruptedDataError, NoHiddenMessageError
from header import HEADER_BITS, check_payload, extract_message, parse_header
from image_utils import carrier_bytes, load_image
from video_utils import FrameReader, probe_video


# ---------------------------------------------------------------- image

def decode_image(stego_path) -> str:
    """Return the hidden message, or raise a clear StegoError.

    The image is loaded exactly like the encoder does, so its own mode
    tells us which channels carry the bits (L/LA: grey, RGB/RGBA: R,G,B).
    """
    return extract_message(carrier_bytes(load_image(stego_path)))


# ---------------------------------------------------------------- video

class _LsbStream:
    """Hands out LSBs from consecutive frames, reading frames only when needed."""

    def __init__(self, frames):
        self._frames = iter(frames)
        self._left = np.empty(0, dtype=np.uint8)  # bits read but not used yet

    def read(self, n: int) -> np.ndarray:
        chunks, have = [self._left], self._left.size
        while have < n:
            frame = next(self._frames, None)
            if frame is None:
                raise CorruptedDataError("Video ended before the hidden message was complete.")
            bits = frame.reshape(-1) & 1  # the LSB of every R, G, B byte
            chunks.append(bits)
            have += bits.size
        bits = np.concatenate(chunks)
        self._left = bits[n:]
        return bits[:n]


def decode_video(stego_path) -> str:
    """Return the message hidden in a video, or raise a clear StegoError.

    Reads the 104 header bits first and validates them; then reads only
    as many frames as the payload needs and stops ffmpeg early.
    """
    info = probe_video(stego_path)
    if info.usable_bytes < HEADER_BITS:
        raise NoHiddenMessageError("Video is too small to contain a hidden message.")

    with FrameReader(stego_path, info) as reader:  # leaving the block stops ffmpeg
        stream = _LsbStream(reader)
        length, crc = parse_header(bits_to_bytes(stream.read(HEADER_BITS)), info.usable_bytes)
        payload = bits_to_bytes(stream.read(length * 8))
    check_payload(payload, length, crc)
    return bytes_to_text(payload)
