"""Tests for bitutils.py (SP2 acceptance)."""

import numpy as np
import pytest

from bitutils import (
    bits_to_bytes,
    bytes_to_bits,
    bytes_to_text,
    embed_bits,
    extract_bits,
    text_to_bytes,
)
from errors import CapacityError, CorruptedDataError, EmptyMessageError

MESSAGES = {
    "ascii": "Hello, World! 123",
    "hindi": "नमस्ते दुनिया",
    "emoji": "secret 🔒😀👍",
}


def random_cover(size, seed=0):
    """A reproducible random flat uint8 cover (stands in for image bytes)."""
    return np.random.default_rng(seed).integers(0, 256, size, dtype=np.uint8)


# ---------------------------------------------------------------- text <-> bytes <-> bits

@pytest.mark.parametrize("text", MESSAGES.values(), ids=MESSAGES.keys())
def test_text_round_trip(text):
    bits = bytes_to_bits(text_to_bytes(text))
    assert bytes_to_text(bits_to_bytes(bits)) == text


def test_utf8_byte_lengths():
    # Hindi letters are 3 bytes each and emoji 4 bytes in UTF-8.
    assert len(text_to_bytes("A")) == 1
    assert len(text_to_bytes("न")) == 3
    assert len(text_to_bytes("😀")) == 4


def test_bits_are_msb_first():
    # 'A' = 0x41 = 0b01000001 (assumption A2)
    assert bytes_to_bits(b"A").tolist() == [0, 1, 0, 0, 0, 0, 0, 1]


def test_empty_message_rejected():
    with pytest.raises(EmptyMessageError):
        text_to_bytes("")


def test_invalid_utf8_is_corrupted():
    with pytest.raises(CorruptedDataError):
        bytes_to_text(b"\xff\xfe")


def test_partial_byte_rejected():
    with pytest.raises(ValueError):
        bits_to_bytes(np.array([1, 0, 1], dtype=np.uint8))


# ---------------------------------------------------------------- embed / extract

@pytest.mark.parametrize("text", MESSAGES.values(), ids=MESSAGES.keys())
def test_embed_extract_full_message(text):
    cover = random_cover(1000)
    bits = bytes_to_bits(text_to_bytes(text))
    stego = embed_bits(cover, bits)
    out = extract_bits(stego, bits.size)
    assert np.array_equal(out, bits)
    assert bytes_to_text(bits_to_bytes(out)) == text


def test_embed_extract_random_bits_with_offset():
    cover = random_cover(50_000, seed=1)
    bits = np.random.default_rng(2).integers(0, 2, 30_000, dtype=np.uint8)
    stego = embed_bits(cover, bits, start=104)  # 104 = header size in bits
    assert np.array_equal(extract_bits(stego, bits.size, start=104), bits)
    # Bytes before the offset and after the payload are untouched.
    assert np.array_equal(stego[:104], cover[:104])
    assert np.array_equal(stego[104 + bits.size:], cover[104 + bits.size:])


def test_each_byte_changes_by_at_most_one():
    cover = random_cover(10_000, seed=3)
    bits = np.random.default_rng(4).integers(0, 2, 10_000, dtype=np.uint8)
    stego = embed_bits(cover, bits)
    # int16 so the subtraction cannot wrap around like uint8 would.
    diff = np.abs(stego.astype(np.int16) - cover.astype(np.int16))
    assert diff.max() <= 1


def test_extreme_byte_values():
    # 0 and 255 must not overflow/underflow when the LSB changes.
    cover = np.array([0, 0, 255, 255], dtype=np.uint8)
    stego = embed_bits(cover, np.array([0, 1, 0, 1], dtype=np.uint8))
    assert stego.tolist() == [0, 1, 254, 255]


def test_input_array_not_modified():
    cover = random_cover(1000, seed=5)
    original = cover.copy()
    stego = embed_bits(cover, np.ones(1000, dtype=np.uint8))
    assert np.array_equal(cover, original)
    assert not np.shares_memory(cover, stego)


def test_output_dtype_and_shape():
    cover = random_cover(100)
    stego = embed_bits(cover, np.ones(8, dtype=np.uint8))
    assert stego.dtype == np.uint8 and stego.shape == cover.shape


def test_exactly_at_capacity_fits():
    cover = random_cover(64)
    bits = np.ones(64, dtype=np.uint8)
    assert np.array_equal(extract_bits(embed_bits(cover, bits), 64), bits)


# ---------------------------------------------------------------- errors

def test_too_many_bits_raises_capacity_error():
    cover = random_cover(64)
    with pytest.raises(CapacityError):
        embed_bits(cover, np.ones(65, dtype=np.uint8))


def test_offset_pushes_past_capacity():
    with pytest.raises(CapacityError):
        embed_bits(random_cover(64), np.ones(10, dtype=np.uint8), start=60)


def test_extract_past_end_raises_capacity_error():
    with pytest.raises(CapacityError):
        extract_bits(random_cover(64), 65)


def test_bits_must_be_zero_or_one():
    with pytest.raises(ValueError):
        embed_bits(random_cover(64), np.array([0, 1, 2], dtype=np.uint8))


def test_cover_must_be_uint8():
    with pytest.raises(TypeError):
        embed_bits(np.zeros(64, dtype=np.int32), np.ones(8, dtype=np.uint8))


def test_cover_must_be_flat():
    with pytest.raises(ValueError):
        embed_bits(np.zeros((8, 8), dtype=np.uint8), np.ones(8, dtype=np.uint8))
