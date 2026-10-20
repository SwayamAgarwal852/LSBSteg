"""Hide a text message in an image or a video."""

from pathlib import Path

from bitutils import bytes_to_bits, embed_bits, text_to_bytes
from errors import FFmpegError, UnsupportedFormatError
from header import build_packet, embed_message, max_payload_bytes
from image_utils import carrier_bytes, load_image, save_png, with_carrier_bytes
from video_utils import FrameReader, FrameWriter, probe_video


# ---------------------------------------------------------------- image

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


# ---------------------------------------------------------------- video

def video_capacity_bytes(cover_path) -> int:
    """Maximum message size (UTF-8 bytes) this cover video can hold."""
    return max_payload_bytes(probe_video(cover_path).usable_bytes)


def encode_video(cover_path, message: str, output_path) -> Path:
    """Hide `message` in a video and save it as a lossless FFV1 MKV.

    The same LSB method as for images, applied frame after frame: the
    header + message bits fill frame 1 first, then frame 2, and so on.
    All frames are re-encoded (losslessly); the original audio is copied.
    """
    cover_path, output_path = Path(cover_path), Path(output_path)
    if output_path.suffix.lower() != ".mkv":
        raise UnsupportedFormatError("Output video must end in .mkv (lossless FFV1).")
    if output_path.resolve() == cover_path.resolve():
        raise ValueError("Output file must be different from the cover video.")

    # Every check happens BEFORE ffmpeg starts writing anything.
    info = probe_video(cover_path)
    if info.is_variable_frame_rate:
        raise UnsupportedFormatError(
            f"Variable frame rate video (r_frame_rate {info.frame_rate}, "
            f"average {info.avg_frame_rate}) is not supported."
        )
    bits = bytes_to_bits(build_packet(text_to_bytes(message), info.usable_bytes))

    with FrameReader(cover_path, info) as reader, \
            FrameWriter(output_path, info, audio_source=cover_path) as writer:
        pos = 0  # how many message bits are already hidden
        for frame in reader:
            if pos < bits.size:
                chunk = bits[pos:pos + info.frame_bytes]
                frame = embed_bits(frame.reshape(-1), chunk).reshape(frame.shape)
                pos += chunk.size
            writer.write(frame)  # frames after the message are copied unchanged
        if reader.frames_read != info.frame_count:
            raise FFmpegError(
                f"Read {reader.frames_read} frames but ffprobe counted {info.frame_count}."
            )
        return writer.finish()
