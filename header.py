"""Message framing: a 13-byte header in front of the payload (PLAN.md section 5).

Layout (big-endian):
    offset 0  4 bytes  magic  b"LSBS"   -> tells "our message" from a clean image
    offset 4  1 byte   version 1        -> lets a future format be recognised
    offset 5  4 bytes  payload length   -> decoder knows exactly how much to read
    offset 9  4 bytes  CRC32 of payload -> detects damaged data
    offset 13 N bytes  payload (UTF-8)

We use a length field instead of an end-of-message delimiter, because a
delimiter could also appear inside the message itself.
"""

import struct
import zlib

import numpy as np

from bitutils import (
    bits_to_bytes,
    bytes_to_bits,
    bytes_to_text,
    embed_bits,
    extract_bits,
    text_to_bytes,
)
from errors import (
    CapacityError,
    CorruptedDataError,
    EmptyMessageError,
    NoHiddenMessageError,
    UnsupportedFormatError,
)

MAGIC = b"LSBS"
VERSION = 1
HEADER_FORMAT = ">4sBII"  # > big-endian, 4s magic, B version, I length, I crc
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 13 bytes
HEADER_BITS = HEADER_SIZE * 8  # 104 bits


# ---------------------------------------------------------------- capacity

def max_payload_bytes(usable_bytes: int) -> int:
    """Largest message (in bytes) that fits in `usable_bytes` cover bytes.

    Each cover byte holds 1 bit; the first 104 bits are the header.
    Example: 100x100 RGB -> 30000 bytes -> (30000 - 104) // 8 = 3737.
    """
    return max(0, (usable_bytes - HEADER_BITS) // 8)


# ---------------------------------------------------------------- build

def build_packet(payload: bytes, usable_bytes: int) -> bytes:
    """Return header + payload, after checking it fits in the cover."""
    if len(payload) == 0:
        raise EmptyMessageError("The message is empty - nothing to hide.")
    limit = max_payload_bytes(usable_bytes)
    if len(payload) > limit:
        # Checked before anything is written, so the cover is never half-modified.
        raise CapacityError(
            f"Message is {len(payload)} bytes but this cover holds at most "
            f"{limit} bytes ({usable_bytes} usable bytes, 13-byte header)."
        )
    header = struct.pack(HEADER_FORMAT, MAGIC, VERSION, len(payload), zlib.crc32(payload))
    return header + payload


# ---------------------------------------------------------------- parse

def parse_header(header: bytes, usable_bytes: int) -> tuple[int, int]:
    """Validate the 13 header bytes and return (payload_length, crc).

    Checks go from "is this ours at all?" to "is it plausible?", and all of
    them happen BEFORE the payload is read, so a clean image is rejected
    after reading only 13 bytes instead of producing garbage text.
    """
    if len(header) < HEADER_SIZE:
        raise NoHiddenMessageError("Data is too short to contain a hidden message.")

    magic, version, length, crc = struct.unpack(HEADER_FORMAT, header[:HEADER_SIZE])

    # 1. Magic: a clean image almost always fails here (1 in 2^32 chance to match).
    if magic != MAGIC:
        raise NoHiddenMessageError("No hidden message found.")
    # 2. Version: our signature, but a format we do not know how to read.
    if version != VERSION:
        raise UnsupportedFormatError(
            f"Message was made by a different version of this tool (version {version})."
        )
    # 3. Length: must be possible for THIS cover, otherwise we would read past
    #    the end or read pixels that were never part of the message.
    limit = max_payload_bytes(usable_bytes)
    if length == 0 or length > limit:
        raise CorruptedDataError(
            f"Header claims {length} bytes, but this cover can hold 1 to {limit} bytes."
        )
    return length, crc


def check_payload(payload: bytes, length: int, crc: int) -> bytes:
    """Make sure the payload is complete and matches the CRC from the header."""
    if len(payload) != length:
        raise CorruptedDataError(
            f"Expected {length} payload bytes but got {len(payload)} (data truncated)."
        )
    # 4. CRC32: catches flipped bits, e.g. after the file was edited or re-compressed.
    if zlib.crc32(payload) != crc:
        raise CorruptedDataError("Data corrupted or not produced by this tool (CRC mismatch).")
    return payload


# ---------------------------------------------------------------- flat-array helpers

def embed_message(flat: np.ndarray, text: str) -> np.ndarray:
    """Hide `text` in the LSBs of a flat uint8 array; returns a new array."""
    packet = build_packet(text_to_bytes(text), flat.size)
    return embed_bits(flat, bytes_to_bits(packet))


def extract_message(flat: np.ndarray) -> str:
    """Recover the text hidden by embed_message, or raise a clear error."""
    if flat.size < HEADER_BITS:
        raise NoHiddenMessageError("Cover is too small to contain a hidden message.")

    # Read ONLY the header first; the payload is read after it is validated.
    header = bits_to_bytes(extract_bits(flat, HEADER_BITS))
    length, crc = parse_header(header, flat.size)

    payload = bits_to_bytes(extract_bits(flat, length * 8, start=HEADER_BITS))
    check_payload(payload, length, crc)
    # 5. UTF-8: bytes_to_text raises CorruptedDataError if not valid text.
    return bytes_to_text(payload)
