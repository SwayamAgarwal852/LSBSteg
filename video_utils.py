"""FFmpeg helpers for the video pipeline: probing, frame reader and frame writer.

Video is handled as a stream of RGB frames, one at a time (never the whole
video in memory). FFmpeg does all decoding/encoding through pipes:

    reader: ffmpeg -i cover  -> raw rgb24 frames on stdout -> Python
    writer: Python -> raw rgb24 frames on stdin -> ffmpeg -> FFV1 (bgr0) MKV

FFV1 with pix_fmt bgr0 is lossless for rgb24 (proved bit-exact in SP5
Stage A), so every hidden LSB survives.
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from errors import FFmpegError, FFmpegNotFoundError, UnsupportedFormatError


# ---------------------------------------------------------------- tools

def find_tool(name: str) -> str:
    """Return the full path of ffmpeg/ffprobe, found on PATH (A12)."""
    path = shutil.which(name)
    if path is None:
        raise FFmpegNotFoundError(
            f"{name} was not found. Install FFmpeg (winget install --id Gyan.FFmpeg -e) "
            "and restart the terminal."
        )
    return path


def _log_tail(log, limit=1500) -> str:
    """Last part of an ffmpeg log file, for error messages."""
    log.seek(0)
    return log.read().decode("utf-8", errors="replace")[-limit:].strip()


def _stop(proc: subprocess.Popen) -> None:
    """Make sure an ffmpeg process is gone, so no orphan is left behind."""
    for pipe in (proc.stdin, proc.stdout):
        if pipe:
            try:
                pipe.close()
            except OSError:
                pass  # the pipe may already be broken; we are stopping anyway
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


# ---------------------------------------------------------------- probing

@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    frame_rate: str  # exact r_frame_rate from ffprobe, e.g. "30000/1001"
    avg_frame_rate: str
    frame_count: int  # counted by decoding (-count_frames), A11
    audio_codecs: tuple[str, ...]
    rotation: float | None  # display rotation tag in degrees, if any

    @property
    def frame_bytes(self) -> int:
        """Bytes per RGB frame = carrier bytes per frame (1 bit each)."""
        return self.width * self.height * 3

    @property
    def usable_bytes(self) -> int:
        return self.frame_count * self.frame_bytes

    @property
    def is_variable_frame_rate(self) -> bool:
        """A9 heuristic: real frame rate differs from the average frame rate."""
        return _rate(self.frame_rate) != _rate(self.avg_frame_rate)


def _rate(text: str) -> Fraction | None:
    """'30000/1001' -> Fraction; ffprobe uses '0/0' for 'unknown'."""
    num, _, den = text.partition("/")
    return None if int(den or 1) == 0 else Fraction(int(num), int(den or 1))


def probe_video(path) -> VideoInfo:
    """Read width, height, frame rates, exact frame count, audio and rotation."""
    cmd = [find_tool("ffprobe"), "-v", "error", "-count_frames",
           "-show_entries",
           "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,"
           "nb_read_frames:stream_side_data=side_data_type,rotation",
           "-of", "json", str(path)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise UnsupportedFormatError(f"'{Path(path).name}' is not a readable video.")
    streams = json.loads(result.stdout).get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    if not video or "nb_read_frames" not in video[0]:
        raise UnsupportedFormatError(f"'{Path(path).name}' has no video stream.")
    v = video[0]
    rotation = next((sd["rotation"] for sd in v.get("side_data_list", [])
                     if "rotation" in sd), None)
    return VideoInfo(
        width=v["width"],
        height=v["height"],
        frame_rate=v["r_frame_rate"],
        avg_frame_rate=v["avg_frame_rate"],
        frame_count=int(v["nb_read_frames"]),
        audio_codecs=tuple(s["codec_name"] for s in streams if s.get("codec_type") == "audio"),
        rotation=rotation,
    )


# ---------------------------------------------------------------- reader

class FrameReader:
    """Yield the frames of a video as (H, W, 3) uint8 RGB arrays.

    Use it in a `with` block: leaving the block (normally, by `break`, or by
    an error) always stops ffmpeg, so decoding can stop early safely.
    """

    def __init__(self, path, info: VideoInfo):
        self.info = info
        self.frames_read = 0
        # -noautorotate: give frames as STORED. Without it ffmpeg rotates
        #   frames of phone videos (verified), which would scramble the bits.
        # -fps_mode passthrough: one output frame per decoded frame, no
        #   duplicated or dropped frames.
        self.cmd = [find_tool("ffmpeg"), "-v", "error", "-noautorotate", "-i", str(path),
                    "-map", "0:v:0", "-fps_mode", "passthrough",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    def __enter__(self):
        # stderr goes to a temp FILE, not a pipe: a full stderr pipe that
        # nobody reads is the classic cause of a subprocess deadlock.
        self._log = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=self._log)
        return self

    def __iter__(self):
        size = self.info.frame_bytes
        while True:
            data = self.proc.stdout.read(size)  # blocks until a full frame or EOF
            if not data:
                return
            if len(data) != size:
                raise FFmpegError("Video ended in the middle of a frame.")
            self.frames_read += 1
            yield np.frombuffer(data, dtype=np.uint8).reshape(self.info.height, self.info.width, 3)

    def __exit__(self, *exc):
        _stop(self.proc)
        self._log.close()


# ---------------------------------------------------------------- writer

class FrameWriter:
    """Write RGB frames into a lossless FFV1 (bgr0) MKV, copying the audio.

    The video is written to a temporary file next to the output and only
    renamed to the real name after ffmpeg finished successfully, so a
    failure never leaves a half-written output file.
    """

    def __init__(self, output_path, info: VideoInfo, audio_source=None):
        self.output_path = Path(output_path)
        self.info = info
        self.audio_source = audio_source
        self._finished = False

    def _command(self, temp_path: Path) -> list[str]:
        cmd = [find_tool("ffmpeg"), "-v", "error", "-y"]
        if self.info.rotation:
            # Carry the display-rotation tag over (D9; verified to work into MKV).
            cmd += ["-noautorotate", "-display_rotation", f"{self.info.rotation:g}"]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{self.info.width}x{self.info.height}",
                "-framerate", self.info.frame_rate,  # exact fraction, e.g. 30000/1001
                "-i", "-"]
        if self.audio_source is not None:
            # Second input = the original file; '?' means "only if it has audio".
            cmd += ["-i", str(self.audio_source), "-map", "0:v", "-map", "1:a?", "-c:a", "copy"]
        cmd += ["-c:v", "ffv1", "-pix_fmt", "bgr0", "-f", "matroska", str(temp_path)]
        return cmd

    def __enter__(self):
        fd, name = tempfile.mkstemp(prefix=self.output_path.stem + ".",
                                    suffix=".partial", dir=self.output_path.parent)
        os.close(fd)
        self._temp = Path(name)
        self._log = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(self._command(self._temp), stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=self._log)
        return self

    def write(self, frame: np.ndarray) -> None:
        try:
            self.proc.stdin.write(frame.tobytes())
        except OSError as exc:  # BrokenPipeError: ffmpeg stopped reading
            self.proc.wait(timeout=10)
            raise FFmpegError(f"ffmpeg stopped while writing the video:\n{_log_tail(self._log)}") from exc

    def finish(self) -> Path:
        """Close the input, wait for ffmpeg, then move the file into place."""
        try:
            self.proc.stdin.close()  # end of input -> ffmpeg finalises the file
        except OSError:
            pass  # ffmpeg already died; its exit code below reports the failure
        if self.proc.wait() != 0:
            raise FFmpegError(f"ffmpeg failed while writing the video:\n{_log_tail(self._log)}")
        os.replace(self._temp, self.output_path)
        self._finished = True
        return self.output_path

    def __exit__(self, *exc):
        if not self._finished:
            _stop(self.proc)
            self._temp.unlink(missing_ok=True)  # never leave a broken file behind
        self._log.close()
