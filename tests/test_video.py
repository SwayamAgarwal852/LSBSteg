"""Tests for the video pipeline: encode_video / decode_video (SP5).

PLAN.md SP5 acceptance items are marked [1]..[7]. Item [8] (OpenCV reader
comparison) was done in SP5 Stage A: bit-exact, but not needed, so
opencv-python was removed.
"""

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

import video_utils
from decoder import decode_video
from encoder import encode_video, video_capacity_bytes
from errors import (
    CapacityError,
    FFmpegError,
    FFmpegNotFoundError,
    NoHiddenMessageError,
    UnsupportedFormatError,
)
from video_utils import FrameReader, FrameWriter, VideoInfo, probe_video

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


# ---------------------------------------------------------------- helpers

def ffmpeg(*args):
    subprocess.run([FFMPEG, "-v", "error", "-y", *map(str, args)], check=True)


def ffprobe_streams(path):
    """Independent ffprobe call (not our probe_video) for checking results."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_entries",
         "stream=codec_type,codec_name,pix_fmt,width,height,r_frame_rate,avg_frame_rate,"
         "nb_read_frames:stream_side_data=rotation", "-of", "json", str(path)],
        capture_output=True, check=True).stdout
    return json.loads(out)["streams"]


def video_stream(path):
    return next(s for s in ffprobe_streams(path) if s["codec_type"] == "video")


def read_frames(path, w, h):
    """Independent frame reader (not our FrameReader)."""
    raw = subprocess.run([FFMPEG, "-v", "error", "-noautorotate", "-i", str(path),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def audio_hash(path):
    """SHA-256 of the audio packets (data only, so container timing does not matter)."""
    return subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a", "-c", "copy",
                           "-f", "streamhash", "-hash", "sha256", "-"],
                          capture_output=True, text=True, check=True).stdout.strip()


def files_in(folder):
    return sorted(p.name for p in folder.iterdir())


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    """Synthetic test clips (A14), made with the commands shown in the SP5 report."""
    d = tmp_path_factory.mktemp("clips")
    c = {k: d / f"{k}.mp4" for k in ("cfr_audio", "ntsc", "vfr", "rot90")}
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", c["cfr_audio"])
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x120:rate=30000/1001:duration=2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", c["ntsc"])
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=4",
           "-vf", "select='lt(n\\,25)+not(mod(n\\,4))'", "-fps_mode", "vfr",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", c["vfr"])
    ffmpeg("-display_rotation", "90", "-i", c["cfr_audio"], "-c", "copy", c["rot90"])
    return c


@pytest.fixture
def procs(monkeypatch):
    """Record every subprocess started, to check none is left running."""
    started = []
    real_popen = subprocess.Popen

    class SpyPopen(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    return started


def tool_names(started):
    return [Path(p.args[0]).stem.lower() for p in started]


# ---------------------------------------------------------------- [1] bit-exactness

@pytest.mark.parametrize("w, h", [(160, 120), (161, 121)])
def test_ffv1_bgr0_round_trip_is_bit_exact(tmp_path, w, h):
    rng = np.random.default_rng(1234)
    frames = [rng.integers(0, 256, (h, w, 3), dtype=np.uint8) for _ in range(8)]
    frames += [np.zeros((h, w, 3), np.uint8), np.full((h, w, 3), 255, np.uint8)]
    info = VideoInfo(w, h, "25/1", "25/1", len(frames), (), None)
    out = tmp_path / "exact.mkv"
    with FrameWriter(out, info) as writer:
        for f in frames:
            writer.write(f)
        writer.finish()
    assert video_stream(out)["pix_fmt"] == "bgr0"
    back = read_frames(out, w, h)
    assert len(back) == len(frames)
    assert all(np.array_equal(a, b) for a, b in zip(frames, back))
    with FrameReader(out, info) as reader:  # our reader gives the same
        assert all(np.array_equal(a, b) for a, b in zip(frames, reader))


# ---------------------------------------------------------------- [2] multi-frame round trip

def test_message_spanning_several_frames(clips, tmp_path):
    message = ("Secret नमस्ते 😀 " * 1100)[:20000]
    assert len(message.encode("utf-8")) > 20000  # > 20 KB, frame holds 7200 bytes
    cover_hash = hashlib.sha256(clips["cfr_audio"].read_bytes()).hexdigest()
    out = encode_video(clips["cfr_audio"], message, tmp_path / "stego.mkv")
    assert decode_video(out) == message
    assert hashlib.sha256(clips["cfr_audio"].read_bytes()).hexdigest() == cover_hash  # cover untouched

    cover = read_frames(clips["cfr_audio"], 160, 120)
    stego = read_frames(out, 160, 120)
    changed = [not np.array_equal(a, b) for a, b in zip(cover, stego)]
    bits = (13 + len(message.encode("utf-8"))) * 8
    expected = -(-bits // (160 * 120 * 3))  # ceiling division
    assert expected >= 3
    assert sum(changed) == expected and all(changed[:expected])  # only the first frames
    diff = np.abs(cover.astype(np.int16) - stego.astype(np.int16))
    assert diff.max() == 1


def test_one_byte_message_and_exact_capacity(clips, tmp_path):
    assert decode_video(encode_video(clips["ntsc"], "A", tmp_path / "a.mkv")) == "A"
    limit = video_capacity_bytes(clips["ntsc"])
    assert limit == (60 * 160 * 120 * 3 - 104) // 8
    out = encode_video(clips["ntsc"], "z" * limit, tmp_path / "full.mkv")
    assert decode_video(out) == "z" * limit


# ---------------------------------------------------------------- [3] frame count and rate

@pytest.mark.parametrize("name", ["cfr_audio", "ntsc"])
def test_frame_count_and_rate_preserved(clips, tmp_path, name):
    out = encode_video(clips[name], "hello", tmp_path / "stego.mkv")
    before, after = video_stream(clips[name]), video_stream(out)
    assert after["codec_name"] == "ffv1" and after["pix_fmt"] == "bgr0"
    for key in ("width", "height", "r_frame_rate", "avg_frame_rate", "nb_read_frames"):
        assert after[key] == before[key], key


# ---------------------------------------------------------------- [4] audio

def test_audio_copied_bit_identically(clips, tmp_path):
    out = encode_video(clips["cfr_audio"], "hello", tmp_path / "stego.mkv")
    audio_before = [s for s in ffprobe_streams(clips["cfr_audio"]) if s["codec_type"] == "audio"]
    audio_after = [s for s in ffprobe_streams(out) if s["codec_type"] == "audio"]
    assert [s["codec_name"] for s in audio_after] == [s["codec_name"] for s in audio_before] == ["aac"]
    assert audio_hash(out) == audio_hash(clips["cfr_audio"])


def test_video_without_audio_stays_without_audio(clips, tmp_path):
    out = encode_video(clips["ntsc"], "hello", tmp_path / "stego.mkv")
    assert [s["codec_type"] for s in ffprobe_streams(out)] == ["video"]


# ---------------------------------------------------------------- [5] VFR

def test_vfr_clip_rejected(clips, tmp_path):
    info = probe_video(clips["vfr"])
    assert info.frame_rate == "25/1" and info.avg_frame_rate != "25/1"
    with pytest.raises(UnsupportedFormatError, match="Variable frame rate"):
        encode_video(clips["vfr"], "hello", tmp_path / "stego.mkv")
    assert files_in(tmp_path) == []


def test_cfr_clips_not_flagged_as_vfr(clips):
    assert not probe_video(clips["cfr_audio"]).is_variable_frame_rate
    assert not probe_video(clips["ntsc"]).is_variable_frame_rate


# ---------------------------------------------------------------- [6] capacity before writing

def test_over_capacity_rejected_before_anything_is_written(clips, tmp_path, procs):
    limit = video_capacity_bytes(clips["cfr_audio"])
    procs.clear()
    with pytest.raises(CapacityError, match=f"{limit + 1} bytes.*at most {limit} bytes"):
        encode_video(clips["cfr_audio"], "z" * (limit + 1), tmp_path / "stego.mkv")
    assert files_in(tmp_path) == []
    assert tool_names(procs) == ["ffprobe"]  # ffmpeg was never started


# ---------------------------------------------------------------- [7] ffmpeg missing

def test_ffmpeg_missing(clips, tmp_path, monkeypatch):
    monkeypatch.setattr(video_utils.shutil, "which", lambda name: None)
    with pytest.raises(FFmpegNotFoundError, match="winget"):
        encode_video(clips["cfr_audio"], "hello", tmp_path / "stego.mkv")
    with pytest.raises(FFmpegNotFoundError):
        decode_video(clips["cfr_audio"])
    assert files_in(tmp_path) == []


# ---------------------------------------------------------------- processes and partial files

def test_decoder_stops_early_without_orphans(clips, tmp_path, procs):
    out = encode_video(clips["cfr_audio"], "short", tmp_path / "stego.mkv")
    readers = []
    original_exit = FrameReader.__exit__

    def spy_exit(self, *exc):
        readers.append(self)
        return original_exit(self, *exc)

    procs.clear()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FrameReader, "__exit__", spy_exit)
        assert decode_video(out) == "short"
    assert readers[0].frames_read == 1  # 1 of 50 frames was enough
    assert all(p.poll() is not None for p in procs)  # every ffmpeg/ffprobe has ended


def test_encoder_leaves_no_processes(clips, tmp_path, procs):
    encode_video(clips["cfr_audio"], "hello", tmp_path / "stego.mkv")
    assert sorted(set(tool_names(procs))) == ["ffmpeg", "ffprobe"]
    assert all(p.poll() is not None for p in procs)


def test_ffmpeg_crash_mid_write_leaves_no_file(clips, tmp_path, procs, monkeypatch):
    original_write = FrameWriter.write
    count = {"n": 0}

    def crashing_write(self, frame):
        count["n"] += 1
        if count["n"] == 10:
            self.proc.kill()  # the real ffmpeg writer dies half way
            self.proc.wait()
        original_write(self, frame)

    monkeypatch.setattr(FrameWriter, "write", crashing_write)
    with pytest.raises(FFmpegError):
        encode_video(clips["cfr_audio"], "hello", tmp_path / "stego.mkv")
    assert files_in(tmp_path) == []  # neither the output nor a .partial file
    assert all(p.poll() is not None for p in procs)


def test_python_error_mid_write_leaves_no_file(clips, tmp_path, procs, monkeypatch):
    original_write = FrameWriter.write
    count = {"n": 0}

    def failing_write(self, frame):
        count["n"] += 1
        if count["n"] == 5:
            raise RuntimeError("simulated failure")
        original_write(self, frame)

    monkeypatch.setattr(FrameWriter, "write", failing_write)
    with pytest.raises(RuntimeError):
        encode_video(clips["cfr_audio"], "hello", tmp_path / "stego.mkv")
    assert files_in(tmp_path) == []
    assert all(p.poll() is not None for p in procs)


# ---------------------------------------------------------------- rotation (D9)

def test_rotation_tag_carried_and_frames_not_rotated(clips, tmp_path):
    assert video_stream(clips["rot90"])["side_data_list"][0]["rotation"] == 90
    out = encode_video(clips["rot90"], "rotated", tmp_path / "stego.mkv")
    after = video_stream(out)
    assert after["side_data_list"][0]["rotation"] == 90
    assert (after["width"], after["height"]) == (160, 120)  # stored size, not rotated
    assert decode_video(out) == "rotated"


# ---------------------------------------------------------------- other inputs

def test_clean_video_has_no_hidden_message(clips):
    with pytest.raises(NoHiddenMessageError):
        decode_video(clips["cfr_audio"])


def test_path_with_spaces_and_non_ascii(clips, tmp_path):
    folder = tmp_path / "my videos नमस्ते é"
    folder.mkdir()
    cover = folder / "cover clip 😀.mp4"
    shutil.copy(clips["cfr_audio"], cover)
    out = encode_video(cover, "hello", folder / "stego ñ.mkv")
    assert decode_video(out) == "hello"


def test_output_must_be_mkv_and_not_the_cover(clips, tmp_path):
    with pytest.raises(UnsupportedFormatError, match=r"\.mkv"):
        encode_video(clips["cfr_audio"], "hello", tmp_path / "stego.mp4")
    cover = tmp_path / "same.mkv"
    encode_video(clips["cfr_audio"], "hello", cover)
    with pytest.raises(ValueError, match="different"):
        encode_video(cover, "hello", cover)


def test_not_a_video(tmp_path):
    fake = tmp_path / "notes.mp4"
    fake.write_text("not a video")
    with pytest.raises(UnsupportedFormatError):
        decode_video(fake)


# ---------------------------------------------------------------- timing

def test_timing_10s_640x480(tmp_path):
    cover = tmp_path / "ten_seconds.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x480:rate=25:duration=10",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", cover)
    message = "timing test " * 83_334  # 1,000,008 bytes -> spans 9 frames
    t0 = time.perf_counter()
    info = probe_video(cover)
    t1 = time.perf_counter()
    out = encode_video(cover, message, tmp_path / "stego.mkv")
    t2 = time.perf_counter()
    assert decode_video(out) == message
    t3 = time.perf_counter()
    print(f"\n10 s 640x480 @25 fps ({info.frame_count} frames, AAC audio), "
          f"{len(message):,} byte message - measured on this laptop:"
          f"\n  probe (ffprobe -count_frames) {t1 - t0:.2f} s"
          f"\n  encode (incl. its own probe)  {t2 - t1:.2f} s"
          f"\n  decode (incl. its own probe)  {t3 - t2:.2f} s"
          f"\n  cover {cover.stat().st_size:,} bytes (H.264) -> stego {out.stat().st_size:,} bytes (FFV1)")
