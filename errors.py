"""Custom exceptions for LSBSteg.

Each error has its own class so the GUI can show a specific, friendly
message for each case instead of a Python traceback.
"""


class StegoError(Exception):
    """Base class for all errors raised by this project."""


class CapacityError(StegoError):
    """The message does not fit into the cover image/video."""


class NoHiddenMessageError(StegoError):
    """The file does not contain a message made by this tool."""


class CorruptedDataError(StegoError):
    """A message header was found but the data is damaged."""


class UnsupportedFormatError(StegoError):
    """The input file type or pixel format cannot be used."""


class FFmpegNotFoundError(StegoError):
    """ffmpeg/ffprobe are not installed or not on PATH."""


class EmptyMessageError(StegoError):
    """The user tried to hide an empty message (nothing to hide)."""
