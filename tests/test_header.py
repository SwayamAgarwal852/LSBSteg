"""Tests for header.py (SP3 acceptance)."""

import struct
import zlib

import numpy as np
import pytest

import header
from bitutils import bytes_to_bits, embed_bits
from errors import (
    CapacityError,
    CorruptedDataError,
    EmptyMessageError,
    NoHiddenMessageError,
    StegoError,
    UnsupportedFormatError,
)
from header import (
    HEADER_BITS,
    HEADER_SIZE,
    build_packet,
    check_payload,
    embed_message,
    extract_message,
    max_payload_bytes,
    parse_header,
)


def random_cover(size, seed=0):
    return np.random.default_rng(seed).integers(0, 256, size, dtype=np.uint8)


def raw_header(magic=b"LSBS", version=1, length=5, crc=0):
    """Build a header by hand, so tests can create invalid ones."""
    return struct.pack(">4sBII", magic, version, length, crc)


def cover_with_packet(packet: bytes, size=2000, seed=0):
    """Write arbitrary (possibly invalid) bytes into a cover's LSBs."""
    return embed_bits(random_cover(size, seed), bytes_to_bits(packet))


# ---------------------------------------------------------------- layout and capacity

def test_header_is_13_bytes_104_bits():
    assert HEADER_SIZE == 13 and HEADER_BITS == 104


def test_capacity_hand_computed_100x100_rgb():
    usable = 100 * 100 * 3  # one bit per R, G, B byte
    assert usable == 30000
    assert max_payload_bytes(usable) == (30000 - 104) // 8 == 3737


@pytest.mark.parametrize(
    "usable, expected",
    [(0, 0), (103, 0), (104, 0), (111, 0), (112, 1), (100 * 100, 1237)],
)
def test_capacity_edge_cases(usable, expected):
    # 100x100 grayscale: (10000 - 104) // 8 = 1237
    assert max_payload_bytes(usable) == expected


def test_packet_layout_matches_plan():
    payload = b"hello"
    packet = build_packet(payload, 30000)
    assert packet[0:4] == b"LSBS"
    assert packet[4] == 1
    assert packet[5:9] == (5).to_bytes(4, "big")
    assert packet[9:13] == zlib.crc32(payload).to_bytes(4, "big")
    assert packet[13:] == payload


# ---------------------------------------------------------------- round trips

def test_build_parse_round_trip():
    payload = "नमस्ते 🔒".encode("utf-8")
    packet = build_packet(payload, 30000)
    length, crc = parse_header(packet[:HEADER_SIZE], 30000)
    assert check_payload(packet[HEADER_SIZE:], length, crc) == payload


@pytest.mark.parametrize("text", ["A", "Hello, World!", "नमस्ते दुनिया", "emoji 😀👍"])
def test_embed_extract_round_trip(text):
    assert extract_message(embed_message(random_cover(30000), text)) == text


def test_exactly_at_capacity():
    cover = random_cover(30000)
    text = "x" * 3737
    assert extract_message(embed_message(cover, text)) == text


def test_one_byte_over_capacity():
    with pytest.raises(CapacityError, match="3738 bytes.*3737"):
        embed_message(random_cover(30000), "x" * 3738)


def test_empty_payload_rejected():
    with pytest.raises(EmptyMessageError):
        build_packet(b"", 30000)


# ---------------------------------------------------------------- bad headers

def test_wrong_magic():
    with pytest.raises(NoHiddenMessageError):
        parse_header(raw_header(magic=b"XXXX"), 30000)


def test_unknown_version():
    with pytest.raises(UnsupportedFormatError, match="different version"):
        parse_header(raw_header(version=2), 30000)


def test_length_zero():
    with pytest.raises(CorruptedDataError):
        parse_header(raw_header(length=0), 30000)


def test_length_larger_than_capacity():
    with pytest.raises(CorruptedDataError):
        parse_header(raw_header(length=3738), 30000)
    # 3737 is the exact limit and is accepted
    assert parse_header(raw_header(length=3737), 30000)[0] == 3737


def test_length_too_large_is_rejected_without_reading_payload(monkeypatch):
    """The decoder must stop after the 104 header bits; spy on extract_bits."""
    cover = cover_with_packet(raw_header(length=0xFFFFFFFF), size=2000)
    reads = []
    original = header.extract_bits

    def spy(flat, n, start=0):
        reads.append((n, start))
        return original(flat, n, start)

    monkeypatch.setattr(header, "extract_bits", spy)
    with pytest.raises(CorruptedDataError):
        extract_message(cover)
    assert reads == [(104, 0)]  # only the header was read


def test_truncated_header():
    with pytest.raises(NoHiddenMessageError):
        parse_header(raw_header()[:12], 30000)


def test_truncated_payload():
    packet = build_packet(b"hello world", 30000)
    length, crc = parse_header(packet[:HEADER_SIZE], 30000)
    with pytest.raises(CorruptedDataError, match="truncated"):
        check_payload(packet[HEADER_SIZE:-1], length, crc)


def test_cover_smaller_than_header():
    with pytest.raises(NoHiddenMessageError):
        extract_message(random_cover(103))


# ---------------------------------------------------------------- corruption

def test_flipped_payload_bit():
    stego = embed_message(random_cover(30000), "secret message")
    damaged = stego.copy()
    damaged[HEADER_BITS + 20] ^= 1  # flip one LSB inside the payload
    with pytest.raises(CorruptedDataError, match="CRC"):
        extract_message(damaged)


def test_flipped_crc_bit():
    stego = embed_message(random_cover(30000), "secret message")
    damaged = stego.copy()
    damaged[9 * 8] ^= 1  # first bit of the CRC field
    with pytest.raises(CorruptedDataError):
        extract_message(damaged)


def test_valid_crc_but_invalid_utf8():
    payload = b"\xff\xfe\xfd"
    packet = raw_header(length=3, crc=zlib.crc32(payload)) + payload
    with pytest.raises(CorruptedDataError, match="UTF-8"):
        extract_message(cover_with_packet(packet))


# ---------------------------------------------------------------- never-encoded covers

def test_clean_random_array_reports_no_hidden_message():
    with pytest.raises(NoHiddenMessageError, match="No hidden message"):
        extract_message(random_cover(30000, seed=42))


@pytest.mark.parametrize("fill", [0, 255])
def test_clean_flat_colour_reports_no_hidden_message(fill):
    with pytest.raises(NoHiddenMessageError):
        extract_message(np.full(30000, fill, dtype=np.uint8))


def test_many_clean_random_arrays_never_return_text():
    """1000 never-encoded covers: each must raise our own error type, never crash
    with something else and never return a string."""
    for seed in range(1000):
        with pytest.raises(StegoError):
            extract_message(random_cover(500, seed=seed))
