"""Bit-level helpers for LSB steganography.

The pipeline is:  text -> bytes (UTF-8) -> bits -> written into the
least significant bit (LSB) of each cover byte, and the reverse.

All functions work on flat 1-D NumPy uint8 arrays (the image/frame
reshaped with .reshape(-1)), so the same code serves images and video.
"""

import numpy as np

from errors import CapacityError, CorruptedDataError, EmptyMessageError


# ---------------------------------------------------------------- text/bytes

def text_to_bytes(text: str) -> bytes:
    """Encode a message as UTF-8 bytes.

    UTF-8 is used because it handles every language (Hindi, emoji, ...),
    and plain English stays 1 byte per character.
    """
    if text == "":
        # Hiding nothing makes no sense, so refuse early (assumption A7).
        raise EmptyMessageError("The message is empty - nothing to hide.")
    return text.encode("utf-8")


def bytes_to_text(data: bytes) -> str:
    """Decode UTF-8 bytes back into a string.

    Bytes that are not valid UTF-8 cannot be a message we wrote,
    so they are reported as corrupted data instead of being guessed at.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptedDataError("Hidden data is not valid UTF-8 text.") from exc


# ---------------------------------------------------------------- bytes/bits

def bytes_to_bits(data: bytes) -> np.ndarray:
    """Turn bytes into a uint8 array of 0/1 values, 8 per byte.

    np.unpackbits writes the most significant bit first (assumption A2),
    e.g. b"A" (0x41) -> [0, 1, 0, 0, 0, 0, 0, 1].
    """
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: np.ndarray) -> bytes:
    """Turn a 0/1 array back into bytes (inverse of bytes_to_bits)."""
    bits = _as_bit_array(bits)
    # packbits would silently pad a partial byte with zeros; we never
    # want a made-up byte, so require whole bytes.
    if bits.size % 8 != 0:
        raise ValueError(f"Bit count must be a multiple of 8, got {bits.size}.")
    return np.packbits(bits).tobytes()


# ---------------------------------------------------------------- LSB embed/extract

def embed_bits(flat: np.ndarray, bits: np.ndarray, start: int = 0) -> np.ndarray:
    """Write `bits` into the LSBs of `flat`, beginning at index `start`.

    Returns a NEW array; `flat` itself is never modified, so the caller's
    original cover stays intact (useful for PSNR and for retrying).
    """
    _check_cover(flat)
    bits = _as_bit_array(bits)
    _check_fits(flat.size, start, bits.size)

    out = flat.copy()  # copy first, so we only ever write into our own array
    end = start + bits.size
    # & 0xFE clears the lowest bit (11111110), | bits sets it to the message bit.
    # Each byte therefore changes by at most 1 - invisible to the eye.
    out[start:end] = (out[start:end] & 0xFE) | bits
    return out


def extract_bits(flat: np.ndarray, n: int, start: int = 0) -> np.ndarray:
    """Read `n` LSBs from `flat`, beginning at index `start`."""
    _check_cover(flat)
    _check_fits(flat.size, start, n)
    # & 1 keeps only the lowest bit of each byte.
    return flat[start:start + n] & 1


# ---------------------------------------------------------------- validation

def _check_cover(flat: np.ndarray) -> None:
    """The cover must be a flat uint8 array (one entry per colour byte)."""
    if not isinstance(flat, np.ndarray) or flat.dtype != np.uint8:
        raise TypeError("Cover must be a NumPy uint8 array.")
    if flat.ndim != 1:
        raise ValueError("Cover must be 1-D; use array.reshape(-1) first.")


def _check_fits(size: int, start: int, n: int) -> None:
    """Check BEFORE touching data, so we never write or read past the end."""
    if start < 0 or n < 0:
        raise ValueError("start and n must not be negative.")
    if start + n > size:
        raise CapacityError(
            f"Need {n} bits starting at position {start}, "
            f"but the cover only has {size} usable bytes."
        )


def _as_bit_array(bits) -> np.ndarray:
    """Return `bits` as a uint8 array, refusing anything that is not 0 or 1."""
    bits = np.asarray(bits)
    if bits.ndim != 1:
        raise ValueError("Bits must be a 1-D array.")
    if bits.size and not np.isin(bits, (0, 1)).all():
        # A value like 2 would corrupt a neighbouring bit when OR-ed in.
        raise ValueError("Bits must contain only 0 and 1.")
    return bits.astype(np.uint8)
