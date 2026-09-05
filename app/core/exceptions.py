"""Domain-specific errors surfaced as clear job failures or API responses."""


class ClipFactoryError(Exception):
    """Base exception for expected application failures."""


class InvalidInputError(ClipFactoryError):
    """Raised when an uploaded file or URL does not satisfy input requirements."""


class JobNotFoundError(ClipFactoryError):
    """Raised when a requested processing job is not present in local storage."""


class FFmpegError(ClipFactoryError):
    """Raised when FFmpeg cannot inspect, decode, or render source media."""


class LLMError(ClipFactoryError):
    """Raised when semantic clip selection cannot produce valid structured output."""


class NoSuitableClipsError(ClipFactoryError):
    """Raised when no valid, non-overlapping selections remain after validation."""
