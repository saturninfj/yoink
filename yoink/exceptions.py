"""yoink exceptions."""


class YoinkError(Exception):
    """Base class for yoink errors."""


class ServerError(YoinkError):
    """Server returned an unexpected response."""


class UnsupportedRangeError(ServerError):
    """Server does not allow ranged downloads."""


class DownloadError(YoinkError):
    """A segment or download failed after all retries."""


class ResumeMismatchError(YoinkError):
    """Server-side file changed since last checkpoint; cannot resume safely."""
